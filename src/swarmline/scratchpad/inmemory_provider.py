"""InMemoryScratchpadProvider — default zero-dependency backend for tests and single-run agents."""

from __future__ import annotations

from datetime import datetime, timezone

from swarmline.scratchpad.types import ScratchpadEntry


class InMemoryScratchpadProvider:
    """Dict-backed scratchpad. Not thread-safe — intended for a single event loop."""

    def __init__(self) -> None:
        self._entries: dict[str, ScratchpadEntry] = {}

    async def write(
        self, key: str, content: str, tags: tuple[str, ...] = ()
    ) -> ScratchpadEntry:
        now = datetime.now(timezone.utc)
        existing = self._entries.get(key)
        created_at = existing.created_at if existing is not None else now
        entry = ScratchpadEntry(
            key=key,
            content=content,
            tags=tuple(tags),
            created_at=created_at,
            updated_at=now,
        )
        self._entries[key] = entry
        return entry

    async def read(
        self, key: str | None
    ) -> list[ScratchpadEntry] | ScratchpadEntry | None:
        if key is None:
            return list(self._entries.values())
        return self._entries.get(key)

    async def search(self, query: str) -> list[ScratchpadEntry]:
        if not query:
            return []
        needle = query.casefold()
        return [
            entry
            for entry in self._entries.values()
            if needle in entry.key.casefold()
            or needle in entry.content.casefold()
            or any(needle in tag.casefold() for tag in entry.tags)
        ]

    async def delete(self, key: str) -> bool:
        return self._entries.pop(key, None) is not None
