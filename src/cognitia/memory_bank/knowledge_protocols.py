"""Knowledge bank protocols -- ISP-compliant interfaces for knowledge management."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cognitia.memory_bank.knowledge_types import (
    ChecklistItem,
    DocumentKind,
    IndexEntry,
    KnowledgeEntry,
    KnowledgeIndex,
    QualityCriterion,
)


@runtime_checkable
class KnowledgeStore(Protocol):
    """CRUD for typed knowledge documents. ISP: 5 methods."""

    async def save(self, entry: KnowledgeEntry) -> None:
        """Save or update a knowledge entry."""
        ...

    async def load(self, path: str) -> KnowledgeEntry | None:
        """Load entry by path. None if not found."""
        ...

    async def delete(self, path: str) -> None:
        """Delete entry. Graceful if not found."""
        ...

    async def list_entries(self, kind: DocumentKind | None = None) -> list[IndexEntry]:
        """List entries, optionally filtered by kind."""
        ...

    async def exists(self, path: str) -> bool:
        """Check if entry exists."""
        ...


@runtime_checkable
class KnowledgeSearcher(Protocol):
    """Search and index for the knowledge bank. ISP: 4 methods."""

    async def search(self, query: str, *, top_k: int = 10) -> list[IndexEntry]:
        """Full-text search across entries."""
        ...

    async def search_by_tags(self, tags: list[str], *, top_k: int = 10) -> list[IndexEntry]:
        """Find entries matching any of the given tags."""
        ...

    async def rebuild_index(self) -> KnowledgeIndex:
        """Rebuild the full search index."""
        ...

    async def get_index(self) -> KnowledgeIndex:
        """Get the current search index."""
        ...


@runtime_checkable
class ProgressLog(Protocol):
    """Append-only execution log. ISP: 3 methods."""

    async def append(self, entry: str, *, timestamp: bool = True) -> None:
        """Append a log entry."""
        ...

    async def get_recent(self, n: int = 20) -> list[str]:
        """Get the N most recent entries."""
        ...

    async def get_all(self) -> str:
        """Get the full log as text."""
        ...


@runtime_checkable
class ChecklistManager(Protocol):
    """Task tracking via checklist items. ISP: 4 methods."""

    async def add_item(self, item: ChecklistItem) -> None:
        """Add a checklist item."""
        ...

    async def toggle_item(self, text_prefix: str) -> bool:
        """Toggle done status of item matching prefix. Returns True if found."""
        ...

    async def get_items(self, *, done: bool | None = None) -> list[ChecklistItem]:
        """Get items, optionally filtered by done status."""
        ...

    async def clear_done(self) -> int:
        """Remove all done items. Returns count removed."""
        ...


@runtime_checkable
class VerificationStrategy(Protocol):
    """Pluggable quality verification. ISP: 2 methods."""

    async def verify(self, criteria: list[QualityCriterion]) -> list[QualityCriterion]:
        """Verify criteria, returning updated list with met/evidence filled."""
        ...

    async def suggest_criteria(self, plan_content: str) -> list[QualityCriterion]:
        """Suggest quality criteria from plan content."""
        ...
