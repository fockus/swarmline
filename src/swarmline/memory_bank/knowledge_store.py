"""DefaultKnowledgeStore -- wraps MemoryBankProvider for typed document CRUD."""

from __future__ import annotations

import json
import time
from typing import Any

from swarmline.memory_bank.frontmatter import parse_frontmatter, render_frontmatter
from swarmline.memory_bank.knowledge_types import (
    DocumentKind,
    DocumentMeta,
    IndexEntry,
    KnowledgeEntry,
    KnowledgeIndex,
)


class DefaultKnowledgeStore:
    """KnowledgeStore implementation wrapping any MemoryBankProvider.

    SRP: typed document CRUD + automatic index management.
    """

    def __init__(self, provider: Any) -> None:
        self._provider = provider  # MemoryBankProvider

    async def save(self, entry: KnowledgeEntry) -> None:
        """Save entry with frontmatter, auto-update index."""
        content = render_frontmatter(entry.meta, entry.content)
        await self._provider.write_file(entry.path, content)
        await self._update_index_entry(entry)

    async def load(self, path: str) -> KnowledgeEntry | None:
        """Load entry by path. None if not found."""
        raw = await self._provider.read_file(path)
        if raw is None:
            return None
        meta, body = parse_frontmatter(raw)
        if meta is None:
            meta = DocumentMeta(kind="note")
        return KnowledgeEntry(
            path=path,
            meta=meta,
            content=body,
            size_bytes=len(raw.encode("utf-8")),
        )

    async def delete(self, path: str) -> None:
        """Delete entry and remove from index."""
        await self._provider.delete_file(path)
        await self._remove_index_entry(path)

    async def list_entries(self, kind: DocumentKind | None = None) -> list[IndexEntry]:
        """List entries, optionally filtered by kind."""
        index = await self._load_index()
        entries = list(index.entries)
        if kind is not None:
            entries = [e for e in entries if e.kind == kind]
        return entries

    async def exists(self, path: str) -> bool:
        """Check if entry exists."""
        raw = await self._provider.read_file(path)
        return raw is not None

    # --- Index management (private) ---

    async def _load_index(self) -> KnowledgeIndex:
        raw = await self._provider.read_file("index.json")
        if raw is None:
            return KnowledgeIndex()
        try:
            data = json.loads(raw)
            return KnowledgeIndex(
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
        except (json.JSONDecodeError, KeyError):
            return KnowledgeIndex()

    async def _save_index(self, index: KnowledgeIndex) -> None:
        data = {
            "version": index.version,
            "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "entries": [
                {
                    "path": e.path,
                    "kind": e.kind,
                    "tags": list(e.tags),
                    "importance": e.importance,
                    "summary": e.summary,
                    "updated": e.updated,
                }
                for e in index.entries
            ],
        }
        await self._provider.write_file(
            "index.json", json.dumps(data, indent=2, ensure_ascii=False)
        )

    async def _update_index_entry(self, entry: KnowledgeEntry) -> None:
        index = await self._load_index()
        ie = IndexEntry(
            path=entry.path,
            kind=entry.meta.kind,
            tags=entry.meta.tags,
            importance=entry.meta.importance,
            summary=entry.content[:100],
            updated=entry.meta.updated,
        )
        existing = [e for e in index.entries if e.path != entry.path]
        existing.append(ie)
        new_index = KnowledgeIndex(
            version=index.version,
            updated=time.strftime("%Y-%m-%dT%H:%M:%S"),
            entries=tuple(existing),
        )
        await self._save_index(new_index)

    async def _remove_index_entry(self, path: str) -> None:
        index = await self._load_index()
        remaining = [e for e in index.entries if e.path != path]
        if len(remaining) != len(index.entries):
            new_index = KnowledgeIndex(
                version=index.version,
                updated=time.strftime("%Y-%m-%dT%H:%M:%S"),
                entries=tuple(remaining),
            )
            await self._save_index(new_index)
