"""LSP JSON-RPC transport — the external process-stdio boundary (Task 8).

Separated from the pyright session logic (SRP): this file owns the wire format
(Content-Length framing over a subprocess' stdio) and nothing about pyright or
diagnostics. It is the single mockable seam in the LSP-verify path — unit tests
inject a fake :class:`LspTransport`, so framing/parsing run without pyright.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class LspTransport(Protocol):
    """JSON-RPC message transport (the external process-stdio boundary)."""

    async def send(self, message: Mapping[str, Any]) -> None: ...
    async def receive(self) -> Mapping[str, Any]: ...
    async def aclose(self) -> None: ...


# (executable_path, workspace_root) -> transport
TransportSpawner = Callable[[str, str], Awaitable[LspTransport]]


async def spawn_subprocess_transport(
    executable: str, workspace_root: str
) -> LspTransport:
    """Spawn ``<executable> --stdio`` and wrap its stdio as an LSP transport."""
    proc = await asyncio.create_subprocess_exec(
        executable,
        "--stdio",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        cwd=workspace_root,
    )
    return SubprocessLspTransport(proc)


class SubprocessLspTransport:
    """LSP framing over an asyncio subprocess' stdio (Content-Length headers)."""

    def __init__(
        self, proc: asyncio.subprocess.Process, *, close_timeout: float = 5.0
    ) -> None:
        self._proc = proc
        self._close_timeout = close_timeout

    async def send(self, message: Mapping[str, Any]) -> None:
        if self._proc.stdin is None:
            raise RuntimeError("language-server stdin is closed")
        body = json.dumps(message).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        self._proc.stdin.write(header + body)
        await self._proc.stdin.drain()

    async def receive(self) -> Mapping[str, Any]:
        if self._proc.stdout is None:
            raise EOFError("language-server stdout is closed")
        content_length = 0
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                raise EOFError("language-server stdout closed mid-message")
            stripped = line.strip()
            if not stripped:
                break
            name, _, value = stripped.partition(b":")
            if name.strip().lower() == b"content-length":
                content_length = int(value.strip())
        body = await self._proc.stdout.readexactly(content_length)
        return json.loads(body.decode("utf-8"))

    async def aclose(self) -> None:
        if self._proc.stdin is not None:
            try:
                self._proc.stdin.close()
            except Exception:
                logger.debug("closing language-server stdin failed", exc_info=True)
        try:
            self._proc.terminate()
        except ProcessLookupError:
            return
        except Exception:
            logger.debug("terminating language-server failed", exc_info=True)
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=self._close_timeout)
        except (TimeoutError, asyncio.TimeoutError):
            try:
                self._proc.kill()
            except ProcessLookupError:
                return  # already exited between terminate() and kill() — reaped
            except Exception:
                logger.debug("killing language-server failed", exc_info=True)
                return
            # A SIGKILL is not synchronous: the OS reaps the child only after we
            # await wait() again. Without this the process can linger as a zombie,
            # violating the DoD "close() reaps at run end".
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=self._close_timeout)
            except (TimeoutError, asyncio.TimeoutError):
                logger.debug(
                    "language-server did not exit after SIGKILL", exc_info=True
                )
