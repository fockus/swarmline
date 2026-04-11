"""DefaultKnowledgeSearcher -- word-overlap search over MemoryBankProvider."""

from __future__ import annotations

import json
import time
from typing import Any

from swarmline.memory_bank.frontmatter import parse_frontmatter
from swarmline.memory_bank.knowledge_types import IndexEntry, KnowledgeIndex


class DefaultKnowledgeSearcher:
    """KnowledgeSearcher wrapping MemoryBankProvider for search.

    SRP: search + index management over stored documents.
    """

    def __init__(self, provider: Any) -> None:
        self._provider = provider
        self._index: KnowledgeIndex | None = None

    async def search(self, query: str, *, top_k: int = 10) -> list[IndexEntry]:
        """Full-text word-overlap search across index entries."""
        index = await self.get_index()
        query_words = set(query.lower().split())
        if not query_words:
            return []
        scored: list[tuple[float, IndexEntry]] = []
        for entry in index.entries:
            text = f"{entry.summary} {' '.join(entry.tags)}".lower()
            text_words = set(text.split())
            overlap = len(query_words & text_words)
            if overlap > 0:
                scored.append((overlap / len(query_words), entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:top_k]]

    async def search_by_tags(
        self, tags: list[str], *, top_k: int = 10
    ) -> list[IndexEntry]:
        """Find entries matching any of the given tags."""
        index = await self.get_index()
        tag_set = {t.lower() for t in tags}
        results: list[IndexEntry] = []
        for entry in index.entries:
            entry_tags = {t.lower() for t in entry.tags}
            if tag_set & entry_tags:
                results.append(entry)
                if len(results) >= top_k:
                    break
        return results

    async def rebuild_index(self) -> KnowledgeIndex:
        """Rebuild full index by scanning all .md files in the provider."""
        files = await self._provider.list_files()
        entries: list[IndexEntry] = []
        for f in files:
            if f == "index.json" or not f.endswith(".md"):
                continue
            raw = await self._provider.read_file(f)
            if raw is None:
                continue
            meta, body = parse_frontmatter(raw)
            kind = meta.kind if meta else "note"
            tags = meta.tags if meta else ()
            importance = meta.importance if meta else "medium"
            updated = meta.updated if meta else ""
            entries.append(
                IndexEntry(
                    path=f,
                    kind=kind,
                    tags=tags,
                    importance=importance,
                    summary=body[:100],
                    updated=updated,
                )
            )
        self._index = KnowledgeIndex(
            version=1,
            updated=time.strftime("%Y-%m-%dT%H:%M:%S"),
            entries=tuple(entries),
        )
        # Persist index
        data = {
            "version": self._index.version,
            "updated": self._index.updated,
            "entries": [
                {
                    "path": e.path,
                    "kind": e.kind,
                    "tags": list(e.tags),
                    "importance": e.importance,
                    "summary": e.summary,
                    "updated": e.updated,
                }
                for e in self._index.entries
            ],
        }
        await self._provider.write_file(
            "index.json", json.dumps(data, indent=2, ensure_ascii=False)
        )
        return self._index

    async def get_index(self) -> KnowledgeIndex:
        """Get the current search index (load from storage or rebuild)."""
        if self._index is not None:
            return self._index
        raw = await self._provider.read_file("index.json")
        if raw:
            try:
                data = json.loads(raw)
                self._index = KnowledgeIndex(
                    version=data.get("version", 1),
                    updated=data.get("updated", ""),
                    entries=tuple(
                        IndexEntry(
                            path=e["path"],
                            kind=e.get("kind", "note"),
                            tags=tuple(e.get("tags", ())),
                            importance=e.get("importance", "medium"),
                            summary=e.get("summary", ""),
                            updated=e.get("updated", ""),
                        )
                        for e in data.get("entries", [])
                    ),
                )
                return self._index
            except (json.JSONDecodeError, KeyError):
                pass
        return await self.rebuild_index()
