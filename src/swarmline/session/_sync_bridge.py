"""Sync/async bridge helper for ``InMemorySessionManager``'s sync-facing APIs.

Mechanically extracted from ``session/manager.py`` (Stage C1.3 -- adding the
time-travel ergonomics would have pushed ``manager.py`` past the 400-line
cap; this piece is a pure utility with no manager state, so it moved
verbatim). Byte-equivalent behavior to the code it replaces.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable
from typing import Any


def run_awaitable_sync(awaitable: Awaitable[Any]) -> Any:
    """Synchronously execute a coroutine from a sync call site.

    No running loop -> ``asyncio.run`` inline. A loop IS running (e.g. this
    is called from within an async context) -> run the coroutine on a
    dedicated background thread's own loop, so the caller's loop is never
    blocked or deadlocked.
    """

    async def _await_value() -> Any:
        return await awaitable

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_await_value())

    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(_await_value())
        except BaseException as exc:  # pragma: no cover - defensive bridge
            error["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()

    if "error" in error:
        raise error["error"]
    return result.get("value")
