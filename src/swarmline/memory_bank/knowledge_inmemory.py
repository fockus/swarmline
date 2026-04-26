"""In-memory implementations of knowledge bank protocols -- for tests and dev."""

from __future__ import annotations

import time
from dataclasses import replace

from swarmline.memory_bank.knowledge_types import (
    ChecklistItem,
    DocumentKind,
    IndexEntry,
    KnowledgeEntry,
    KnowledgeIndex,
    QualityCriterion,
)


class InMemoryKnowledgeStore:
    """Dict-based KnowledgeStore."""

    def __init__(self) -> None:
        self._entries: dict[str, KnowledgeEntry] = {}

    async def save(self, entry: KnowledgeEntry) -> None:
        self._entries[entry.path] = entry

    async def load(self, path: str) -> KnowledgeEntry | None:
        return self._entries.get(path)

    async def delete(self, path: str) -> None:
        self._entries.pop(path, None)

    async def list_entries(self, kind: DocumentKind | None = None) -> list[IndexEntry]:
        results: list[IndexEntry] = []
        for e in self._entries.values():
            if kind is not None and e.meta.kind != kind:
                continue
            results.append(
                IndexEntry(
                    path=e.path,
                    kind=e.meta.kind,
                    tags=e.meta.tags,
                    importance=e.meta.importance,
                    summary=e.content[:100],
                    updated=e.meta.updated,
                )
            )
        return results

    async def exists(self, path: str) -> bool:
        return path in self._entries


class InMemoryKnowledgeSearcher:
    """Word-overlap search over InMemoryKnowledgeStore."""

    def __init__(self, store: InMemoryKnowledgeStore) -> None:
        self._store = store
        self._index: KnowledgeIndex | None = None

    async def search(self, query: str, *, top_k: int = 10) -> list[IndexEntry]:
        query_words = set(query.lower().split())
        if not query_words:
            return []
        scored: list[tuple[float, IndexEntry]] = []
        for e in self._store._entries.values():
            text = f"{e.content} {' '.join(e.meta.tags)}".lower()
            text_words = set(text.split())
            overlap = len(query_words & text_words)
            if overlap > 0:
                score = overlap / len(query_words)
                scored.append(
                    (
                        score,
                        IndexEntry(
                            path=e.path,
                            kind=e.meta.kind,
                            tags=e.meta.tags,
                            importance=e.meta.importance,
                            summary=e.content[:100],
                            updated=e.meta.updated,
                        ),
                    )
                )
        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:top_k]]

    async def search_by_tags(
        self, tags: list[str], *, top_k: int = 10
    ) -> list[IndexEntry]:
        tag_set = {t.lower() for t in tags}
        results: list[IndexEntry] = []
        for e in self._store._entries.values():
            entry_tags = {t.lower() for t in e.meta.tags}
            if tag_set & entry_tags:
                results.append(
                    IndexEntry(
                        path=e.path,
                        kind=e.meta.kind,
                        tags=e.meta.tags,
                        importance=e.meta.importance,
                        summary=e.content[:100],
                        updated=e.meta.updated,
                    )
                )
                if len(results) >= top_k:
                    break
        return results

    async def rebuild_index(self) -> KnowledgeIndex:
        entries = await self._store.list_entries()
        self._index = KnowledgeIndex(
            version=1,
            updated=time.strftime("%Y-%m-%dT%H:%M:%S"),
            entries=tuple(entries),
        )
        return self._index

    async def get_index(self) -> KnowledgeIndex:
        if self._index is None:
            return await self.rebuild_index()
        return self._index


class InMemoryProgressLog:
    """List-based ProgressLog."""

    def __init__(self) -> None:
        self._entries: list[str] = []

    async def append(self, entry: str, *, timestamp: bool = True) -> None:
        if timestamp:
            ts = time.strftime("%Y-%m-%d %H:%M")
            entry = f"[{ts}] {entry}"
        self._entries.append(entry)

    async def get_recent(self, n: int = 20) -> list[str]:
        return self._entries[-n:]

    async def get_all(self) -> str:
        return "\n".join(self._entries)


class InMemoryChecklistManager:
    """List-based ChecklistManager."""

    def __init__(self) -> None:
        self._items: list[ChecklistItem] = []

    async def add_item(self, item: ChecklistItem) -> None:
        self._items.append(item)

    async def toggle_item(self, text_prefix: str) -> bool:
        prefix_lower = text_prefix.lower()
        for i, item in enumerate(self._items):
            if item.text.lower().startswith(prefix_lower):
                self._items[i] = replace(item, done=not item.done)
                return True
        return False

    async def get_items(self, *, done: bool | None = None) -> list[ChecklistItem]:
        if done is None:
            return list(self._items)
        return [item for item in self._items if item.done == done]

    async def clear_done(self) -> int:
        before = len(self._items)
        self._items = [item for item in self._items if not item.done]
        return before - len(self._items)


class NullVerifier:
    """No-op VerificationStrategy -- all criteria pass."""

    async def verify(self, criteria: list[QualityCriterion]) -> list[QualityCriterion]:
        return [replace(c, met=True, evidence="auto-verified") for c in criteria]

    async def suggest_criteria(self, plan_content: str) -> list[QualityCriterion]:
        return []
