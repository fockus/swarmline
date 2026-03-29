"""DefaultProgressLog -- append-only log via MemoryBankProvider."""

from __future__ import annotations

import time
from typing import Any

_PROGRESS_PATH = "progress.md"


class DefaultProgressLog:
    """ProgressLog wrapping MemoryBankProvider.

    SRP: append-only log entries with optional timestamps.
    """

    def __init__(self, provider: Any, path: str = _PROGRESS_PATH) -> None:
        self._provider = provider
        self._path = path

    async def append(self, entry: str, *, timestamp: bool = True) -> None:
        """Append a log entry, optionally with timestamp prefix."""
        if timestamp:
            ts = time.strftime("%Y-%m-%d %H:%M")
            entry = f"[{ts}] {entry}"
        await self._provider.append_to_file(self._path, entry + "\n")

    async def get_recent(self, n: int = 20) -> list[str]:
        """Get the N most recent entries."""
        raw = await self._provider.read_file(self._path)
        if not raw:
            return []
        lines = [line for line in raw.strip().split("\n") if line.strip()]
        return lines[-n:]

    async def get_all(self) -> str:
        """Get the full log as text."""
        raw = await self._provider.read_file(self._path)
        return raw or ""
