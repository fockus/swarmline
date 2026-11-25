"""ScratchpadProvider Protocol — pluggable backend for ephemeral working memory."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from swarmline.scratchpad.types import ScratchpadEntry


@runtime_checkable
class ScratchpadProvider(Protocol):
    """Pluggable backend for the scratchpad (within-run working memory).

    Implementations: InMemory (testing), OpenViking (production with AGFS).
    All methods are async. Entries are keyed by string; key-level upsert on write.
    """

    async def write(
        self, key: str, content: str, tags: tuple[str, ...] = ()
    ) -> ScratchpadEntry:
        """Create or update entry by key. Returns the stored entry."""

    async def read(
        self, key: str | None
    ) -> list[ScratchpadEntry] | ScratchpadEntry | None:
        """Read one entry by key, or list all when key is None.

        Returns:
            - list[ScratchpadEntry] when key is None (may be empty)
            - ScratchpadEntry when key matches
            - None when key does not match
        """

    async def search(self, query: str) -> list[ScratchpadEntry]:
        """Return entries whose key/content/tags contain the query (case-insensitive)."""

    async def delete(self, key: str) -> bool:
        """Remove entry by key. Returns True if removed, False if absent."""
