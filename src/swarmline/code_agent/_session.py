"""Session lifecycle persistence (code-agent-facade plan, Stage 5).

`FacadeSessionStore` is thin glue around the EXISTING `JsonlMessageStore`
(domain `MessageStore`, message history) + a flat `session.json` file
(`CodeRuntimeSession` snapshot fields plus the facade's own `cwd`/`model`/
`turn_count` extras) -- no new persistence Protocol, no new table (KISS).

Default store root: `~/.swarmline/code-sessions/` (override via the
`SWARMLINE_SESSIONS_DIR` env var); each session gets its own
`<root>/<session_id>/` subdirectory, created lazily on first `save()` --
constructing a `FacadeSessionStore` never touches the filesystem.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime

    from swarmline.code_runtime_types import CodeRuntimeSession, CodeSessionStatus
    from swarmline.runtime.types import Message

#: Fixed (user_id, topic_id) pair for the single JsonlMessageStore file each
#: session directory holds -- one CodeAgent session IS one conversation, so
#: there is no need for JsonlMessageStore's own multi-conversation keying.
_STORE_USER_ID = "code_agent"
_STORE_TOPIC_ID = "session"

_SESSION_FILE_NAME = "session.json"

#: `session_id` becomes a directory name (`<root>/<session_id>/`) -- this is
#: the ONLY thing standing between a caller-supplied string (via
#: `CodeAgent(session_id=...)` or `CodeAgent.resume(session_id)`) and a path
#: traversal (`"../../etc"` reaching `shutil.rmtree` in `delete()`, or
#: writing `session.json` outside the sessions root). Restricting to a
#: single safe path segment (letters/digits/`_`/`-`) admits UUID4 strings
#: (the only value this facade generates itself) and rejects everything
#: else -- no `/`, `\`, or `.` can ever reach a filesystem call.
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_session_id(session_id: str) -> str:
    """Fail closed: reject any `session_id` that isn't a single safe path
    segment, BEFORE it ever reaches a filesystem operation."""
    if not session_id or not _SESSION_ID_RE.match(session_id):
        raise ValueError(
            f"Invalid session_id {session_id!r}: must be a non-empty string "
            "of letters, digits, '_' or '-' only (path-traversal guard)"
        )
    return session_id


def _default_sessions_root() -> Path:
    """`SWARMLINE_SESSIONS_DIR` override, else `~/.swarmline/code-sessions/`
    (XDG-friendly default, read lazily -- never cached at import time)."""
    override = os.environ.get("SWARMLINE_SESSIONS_DIR")
    if override:
        return Path(override)
    return Path.home() / ".swarmline" / "code-sessions"


def _message_to_store_kwargs(message: Message) -> dict[str, Any]:
    """Map a `Message`'s fields onto `JsonlMessageStore.save_message`'s args."""
    return {
        "role": message.role,
        "content": message.content,
        "tool_calls": message.tool_calls,
        "name": message.name,
        "metadata": message.metadata,
        "content_blocks": (
            [block.to_dict() for block in message.content_blocks]
            if message.content_blocks
            else None
        ),
    }


def _capabilities_dict(hooks_enabled: bool) -> dict[str, Any]:
    """Shared `CodeRuntimeCapabilities` field values -- one place describing
    what a `CodeAgent` session can do, used by both `build_snapshot`
    (session.json) and `build_code_runtime_session` (the live value object)."""
    return {
        "provider": "thin",
        "mode": "code_agent",
        "approvals": False,
        "subagents": False,
        "hooks": hooks_enabled,
        "worktrees": False,
        "session_persistence": True,
        "sandbox": True,
    }


def build_snapshot(
    *,
    session_id: str,
    status: CodeSessionStatus,
    hooks_enabled: bool,
    created_at: datetime,
    cwd: str,
    model: str,
    turn_count: int,
) -> dict[str, Any]:
    """Build the flat `session.json` payload: `CodeRuntimeSession` fields
    (`session_id`/`provider`/`status`/`capabilities`/`created_at`) plus the
    facade's own `cwd`/`model`/`turn_count` extras."""
    return {
        "session_id": session_id,
        "provider": "thin",
        "status": status.value,
        "capabilities": _capabilities_dict(hooks_enabled),
        "created_at": created_at.isoformat(),
        "cwd": cwd,
        "model": model,
        "turn_count": turn_count,
    }


def build_code_runtime_session(
    *,
    session_id: str,
    status: CodeSessionStatus,
    hooks_enabled: bool,
    created_at: datetime,
) -> CodeRuntimeSession:
    """Build the `CodeRuntimeSession` value object `CodeAgent.session()`
    returns -- reused as-is, no new type (see the plan's Stage 5 reuse
    table)."""
    from swarmline.code_runtime_types import CodeRuntimeCapabilities, CodeRuntimeSession

    return CodeRuntimeSession(
        session_id=session_id,
        provider="thin",
        status=status,
        capabilities=CodeRuntimeCapabilities(**_capabilities_dict(hooks_enabled)),
        created_at=created_at,
    )


class FacadeSessionStore:
    """Persists a `CodeAgent`'s session snapshot + message history.

    `snapshot` is a plain `dict` (the flat `session.json` payload) -- the
    facade owns building/parsing it (`CodeAgent._snapshot`/`.session()`);
    this store only knows how to read and write the file plus the message
    history, never the `CodeRuntimeSession` value object itself.
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base_dir = (
            Path(base_dir) if base_dir is not None else _default_sessions_root()
        )

    def _session_dir(self, session_id: str) -> Path:
        return self._base_dir / _validate_session_id(session_id)

    async def save(self, snapshot: dict[str, Any], messages: list[Message]) -> None:
        """Write `session.json` and append any messages not yet persisted.

        Incremental: only messages beyond what is already on disk are
        appended to the JSONL file, so calling `save()` after every turn
        with the FULL accumulated history never duplicates prior turns.
        """
        from swarmline.session.jsonl_store import JsonlMessageStore

        session_dir = self._session_dir(snapshot["session_id"])
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / _SESSION_FILE_NAME).write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2)
        )

        store = JsonlMessageStore(session_dir)
        already_saved = await store.count_messages(_STORE_USER_ID, _STORE_TOPIC_ID)
        for message in messages[already_saved:]:
            await store.save_message(
                _STORE_USER_ID, _STORE_TOPIC_ID, **_message_to_store_kwargs(message)
            )

    async def load(self, session_id: str) -> tuple[dict[str, Any], list[Message]]:
        """Load `(snapshot, messages)`.

        Raises:
            FileNotFoundError: no `session.json` for `session_id`.
            ValueError: `session.json` exists but is not valid JSON.
        """
        from swarmline.runtime.types import Message
        from swarmline.session.jsonl_store import JsonlMessageStore

        session_dir = self._session_dir(session_id)
        session_file = session_dir / _SESSION_FILE_NAME
        if not session_file.exists():
            raise FileNotFoundError(
                f"No CodeAgent session found for id {session_id!r} under "
                f"{self._base_dir}"
            )
        try:
            snapshot: dict[str, Any] = json.loads(session_file.read_text())
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Corrupt session.json for session {session_id!r}: {exc}"
            ) from exc

        store = JsonlMessageStore(session_dir)
        count = await store.count_messages(_STORE_USER_ID, _STORE_TOPIC_ID)
        memory_messages = await store.get_messages(
            _STORE_USER_ID, _STORE_TOPIC_ID, limit=count
        )
        messages = [Message.from_memory_message(mm) for mm in memory_messages]
        return snapshot, messages

    async def delete(self, session_id: str) -> None:
        """Remove the session directory entirely. No-op if it never existed."""
        session_dir = self._session_dir(session_id)
        if session_dir.exists():
            shutil.rmtree(session_dir)
