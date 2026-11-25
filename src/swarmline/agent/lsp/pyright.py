"""Concrete pyright language server + per-scope factory (Task 8, REQ-SCA-072).

The server is discovered by executable on PATH (``shutil.which``), NOT a
mandatory ``pyproject`` dependency. When absent, ``ensure_started`` returns
``False`` (fail-open) and verification is skipped — never a crash.

A persistent ``pyright-langserver --stdio`` process lives across tool-calls and
is reaped at :meth:`close`. The process is scoped to one ``(tenant, workspace)``
pair via :class:`PyrightSessionFactory`; it is never shared across tenants.

The JSON-RPC transport (the process stdio) is injectable so the LSP framing /
diagnostic-parsing logic is unit-testable without pyright installed.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from swarmline.agent.lsp.diagnostics_wire import parse_diagnostic, read_text
from swarmline.agent.lsp.session import Diagnostic
from swarmline.agent.lsp.transport import (
    LspTransport,
    TransportSpawner,
    spawn_subprocess_transport,
)

if TYPE_CHECKING:
    from swarmline.workspace.types import WorkspaceSession

logger = logging.getLogger(__name__)

# Bound the JSON-RPC read loops so a misbehaving server can never hang the agent.
_MAX_MESSAGES = 200
_DEFAULT_TIMEOUT = 15.0

WhichFn = Callable[[str], str | None]


class PyrightLanguageServer:
    """A pyright ``LanguageServerSession`` discovered by PATH (fail-open).

    Structurally conforms to
    :class:`~swarmline.agent.lsp.session.LanguageServerSession`.
    """

    def __init__(
        self,
        *,
        workspace_root: str,
        executable: str = "pyright-langserver",
        which: WhichFn | None = None,
        spawner: TransportSpawner | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._workspace_root = workspace_root
        self._executable = executable
        self._which: WhichFn = which or shutil.which
        self._spawner: TransportSpawner = spawner or spawn_subprocess_transport
        self._timeout = timeout
        self._transport: LspTransport | None = None
        self._started = False
        self._request_id = 0
        # uri -> last document version sent. didOpen the first time a URI is seen,
        # didChange (incrementing the version) on every subsequent diagnostics().
        self._doc_versions: dict[str, int] = {}

    async def ensure_started(self, language: str) -> bool:
        """Start pyright for ``language``; ``False`` (fail-open) if unavailable."""
        if self._started:
            return True
        if language.lower() != "python":
            return False
        try:
            resolved = self._which(self._executable)
            if resolved is None:
                return False
            self._transport = await self._spawner(resolved, self._workspace_root)
            await self._initialize()
            self._started = True
            return True
        except Exception:
            logger.warning(
                "PyrightLanguageServer.ensure_started failed (fail-open)",
                exc_info=True,
            )
            await self._safe_close()
            return False

    async def diagnostics(self, file_path: str) -> tuple[Diagnostic, ...]:
        """Return pyright diagnostics for ``file_path`` (``()`` when not started)."""
        if not self._started or self._transport is None:
            return ()
        try:
            abs_path = self._resolve(file_path)
            uri = Path(abs_path).as_uri()
            # Re-read the file each call: content changes between the baseline and
            # the after-edit diagnostics on the SAME persistent session.
            text = await asyncio.to_thread(read_text, abs_path)
            await self._sync_document(uri, text)
            published = await self._receive_until(
                lambda m: (
                    m.get("method") == "textDocument/publishDiagnostics"
                    and m.get("params", {}).get("uri") == uri
                )
            )
            if published is None:
                return ()
            raw = published.get("params", {}).get("diagnostics", [])
            return tuple(parse_diagnostic(file_path, item) for item in raw)
        except Exception:
            logger.warning(
                "PyrightLanguageServer.diagnostics failed for %r (fail-open)",
                file_path,
                exc_info=True,
            )
            return ()

    async def close(self) -> None:
        """Politely shut down pyright, then reap the process."""
        if self._transport is not None:
            try:
                shutdown_id = self._next_id()
                await self._transport.send(
                    {"jsonrpc": "2.0", "id": shutdown_id, "method": "shutdown"}
                )
                await self._transport.send({"jsonrpc": "2.0", "method": "exit"})
            except Exception:
                logger.debug("pyright graceful shutdown failed; reaping", exc_info=True)
        await self._safe_close()

    # -- internals ---------------------------------------------------------

    async def _sync_document(self, uri: str, text: str) -> None:
        """Notify pyright of the document's current text.

        The FIRST time a URI is seen it is opened (``textDocument/didOpen``,
        version 1). Every subsequent call sends ``textDocument/didChange`` with
        the full new text and an incremented version. A second ``didOpen`` on an
        already-open URI is an LSP protocol violation, so the before/after
        ``edit_introduced`` flow (two ``diagnostics()`` calls on one persistent
        session) must use ``didChange`` for the after-edit read.
        """
        assert self._transport is not None
        if uri not in self._doc_versions:
            self._doc_versions[uri] = 1
            await self._transport.send(
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/didOpen",
                    "params": {
                        "textDocument": {
                            "uri": uri,
                            "languageId": "python",
                            "version": 1,
                            "text": text,
                        }
                    },
                }
            )
            return
        version = self._doc_versions[uri] + 1
        self._doc_versions[uri] = version
        await self._transport.send(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didChange",
                "params": {
                    "textDocument": {"uri": uri, "version": version},
                    "contentChanges": [{"text": text}],
                },
            }
        )

    async def _initialize(self) -> None:
        init_id = self._next_id()
        assert self._transport is not None
        await self._transport.send(
            {
                "jsonrpc": "2.0",
                "id": init_id,
                "method": "initialize",
                "params": {
                    "processId": None,
                    "rootUri": Path(self._workspace_root).as_uri(),
                    "capabilities": {},
                    "workspaceFolders": None,
                },
            }
        )
        await self._receive_until(lambda m: m.get("id") == init_id and "result" in m)
        await self._transport.send(
            {"jsonrpc": "2.0", "method": "initialized", "params": {}}
        )

    async def _receive_until(
        self, predicate: Callable[[Mapping[str, Any]], bool]
    ) -> Mapping[str, Any] | None:
        transport = self._transport
        if transport is None:
            return None

        async def _loop() -> Mapping[str, Any] | None:
            for _ in range(_MAX_MESSAGES):
                message = await transport.receive()
                if predicate(message):
                    return message
            return None

        try:
            return await asyncio.wait_for(_loop(), timeout=self._timeout)
        except (TimeoutError, EOFError, asyncio.IncompleteReadError):
            return None

    async def _safe_close(self) -> None:
        if self._transport is not None:
            try:
                await self._transport.aclose()
            except Exception:
                logger.debug("transport aclose failed", exc_info=True)
        self._transport = None
        self._started = False
        # A fresh process re-opens documents from scratch.
        self._doc_versions.clear()

    def _resolve(self, file_path: str) -> str:
        path = Path(file_path)
        if path.is_absolute():
            return str(path)
        return str(Path(self._workspace_root) / path)

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id


class PyrightSessionFactory:
    """Builds pyright sessions scoped to one ``(tenant, workspace)`` (REQ-SCA-072).

    Structurally conforms to
    :class:`~swarmline.agent.lsp.session.LanguageServerSessionFactory`. One
    process per scope; the same scope reuses the same session, distinct scopes
    (including the same workspace across different tenants) get isolated sessions
    that are never shared. :meth:`close_all` reaps every session.
    """

    def __init__(
        self,
        *,
        executable: str = "pyright-langserver",
        which: WhichFn | None = None,
        spawner: TransportSpawner | None = None,
    ) -> None:
        self._executable = executable
        self._which = which
        self._spawner = spawner
        self._sessions: dict[tuple[str, str], PyrightLanguageServer] = {}

    def for_workspace(
        self, session: WorkspaceSession, *, tenant_id: str, workspace_id: str
    ) -> PyrightLanguageServer:
        """Return the pyright session for the scope (one process per scope)."""
        key = (tenant_id, workspace_id)
        existing = self._sessions.get(key)
        if existing is not None:
            return existing
        root = session.worktree_path or session.repo_root
        server = PyrightLanguageServer(
            workspace_root=root,
            executable=self._executable,
            which=self._which,
            spawner=self._spawner,
        )
        self._sessions[key] = server
        return server

    async def close_all(self) -> None:
        """Reap every scoped session and clear the cache (run-end cleanup)."""
        for server in self._sessions.values():
            await server.close()
        self._sessions.clear()
