"""Episodic memory types — structured episodes with metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Episode:
    """A structured record of what happened during an agent interaction."""

    id: str
    summary: str
    key_decisions: tuple[str, ...] = ()
    tools_used: tuple[str, ...] = ()
    outcome: str = "unknown"  # success / failure / partial
    session_id: str = ""
    timestamp: datetime = field(default_factory=_utcnow)
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class EpisodicMemory(Protocol):
    """Protocol for episodic memory storage and retrieval."""

    async def store(self, episode: Episode) -> None:
        """Store an episode."""
        ...

    async def recall(self, query: str, *, top_k: int = 5) -> list[Episode]:
        """Recall episodes matching a text query (semantic/keyword search)."""
        ...

    async def recall_recent(self, n: int = 10) -> list[Episode]:
        """Recall the N most recent episodes."""
        ...

    async def recall_by_tag(self, tag: str) -> list[Episode]:
        """Recall all episodes with the given tag."""
        ...

    async def count(self) -> int:
        """Return total number of stored episodes."""
        ...
