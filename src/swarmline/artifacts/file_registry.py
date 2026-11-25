"""FileRegistry -- human/LLM-readable file index (``.registry.md``).

Ported from Aura's ``application/components/workspace/file_registry.py``. This
is the mechanism by which the agent KNOWS which artifacts exist: every file
gets a one-line description + category, rendered into ``.registry.md`` and
injected into context (see ``context/builder.py``'s ``available_files`` param).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from swarmline.artifacts.run_root import ArtifactRoot
from swarmline.artifacts.types import FileEntry

logger = logging.getLogger(__name__)

#: Display order of categories in the rendered markdown.
CATEGORY_ORDER: tuple[str, ...] = (
    "notes",
    "sources",
    "tool_outputs",
    "data",
    "code",
    "charts",
    "final",
)


class FileRegistry:
    """Registry of workspace files with descriptions, rendered to ``.registry.md``."""

    CATEGORY_ORDER = CATEGORY_ORDER

    def __init__(self, root: ArtifactRoot) -> None:
        self.root = root
        self._entries: list[FileEntry] = []
        self._registry_md_path = root.path / ".registry.md"
        self._registry_json_path = root.path / ".registry.json"
        self._load()

    def _load(self) -> None:
        if not self._registry_json_path.exists():
            return
        try:
            data = json.loads(self._registry_json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as err:
            logger.warning(
                "Could not load .registry.json, starting empty", exc_info=err
            )
            return
        self._entries = [
            FileEntry(
                path=item["path"],
                description=item["description"],
                category=item["category"],
                created_at=datetime.fromisoformat(item["created_at"]),
                size_bytes=item.get("size_bytes", 0),
            )
            for item in data.get("entries", [])
        ]

    def _save(self) -> None:
        data = {
            "entries": [
                {
                    "path": e.path,
                    "description": e.description,
                    "category": e.category,
                    "created_at": e.created_at.isoformat(),
                    "size_bytes": e.size_bytes,
                }
                for e in self._entries
            ]
        }
        self._registry_json_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def add(
        self, path: str, description: str, category: str, size_bytes: int = 0
    ) -> FileEntry:
        """Add (or update) a file entry, re-rendering the registry files."""
        existing = self.get_by_path(path)
        created_at = existing.created_at if existing is not None else datetime.now(UTC)
        entry = FileEntry(
            path=path,
            description=description,
            category=category,
            created_at=created_at,
            size_bytes=size_bytes,
        )
        if existing is not None:
            self._entries[self._entries.index(existing)] = entry
        else:
            self._entries.append(entry)
        self._save()
        self._write_markdown()
        return entry

    def remove(self, path: str) -> bool:
        """Remove an entry by path. Returns True if it was present."""
        for i, entry in enumerate(self._entries):
            if entry.path == path:
                del self._entries[i]
                self._save()
                self._write_markdown()
                return True
        return False

    def get_by_path(self, path: str) -> FileEntry | None:
        """Find an entry by exact path."""
        for entry in self._entries:
            if entry.path == path:
                return entry
        return None

    def get_by_category(self, category: str) -> list[FileEntry]:
        """All entries in the given category."""
        return [e for e in self._entries if e.category == category]

    def list_all(self) -> list[FileEntry]:
        """All entries."""
        return list(self._entries)

    def count(self) -> int:
        """Number of entries."""
        return len(self._entries)

    def search(self, query: str, max_results: int = 10) -> list[FileEntry]:
        """Lexical search over path + description + category.

        Scoring: +10 full-query substring match, +1 per matching word,
        +5 extra when the query matches the path. No embeddings.
        """
        if not query:
            return []

        query_lower = query.lower()
        query_words = query_lower.split()
        scored: list[tuple[FileEntry, int]] = []

        for entry in self._entries:
            score = 0
            text = f"{entry.path} {entry.description} {entry.category}".lower()
            if query_lower in text:
                score += 10
            score += sum(1 for word in query_words if word in text)
            if query_lower in entry.path.lower():
                score += 5
            if score > 0:
                scored.append((entry, score))

        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [entry for entry, _ in scored[:max_results]]

    def _write_markdown(self) -> None:
        lines = ["# File Registry", "", f"Total files: {len(self._entries)}", ""]

        seen_categories: set[str] = set()
        for category in self.CATEGORY_ORDER:
            seen_categories.add(category)
            entries = self.get_by_category(category)
            if not entries:
                continue
            lines.append(f"## {category.replace('_', ' ').title()}")
            lines.append("")
            for entry in sorted(entries, key=lambda e: e.created_at):
                desc = entry.description
                if len(desc) > 60:
                    desc = desc[:57] + "..."
                lines.append(f"- `{entry.path}`: {desc}")
            lines.append("")

        other_categories = {e.category for e in self._entries} - seen_categories
        for category in sorted(other_categories):
            entries = self.get_by_category(category)
            lines.append(f"## {category.title()}")
            lines.append("")
            for entry in entries:
                lines.append(f"- `{entry.path}`: {entry.description[:60]}")
            lines.append("")

        self._registry_md_path.write_text("\n".join(lines), encoding="utf-8")

    def get_markdown(self) -> str:
        """Return the rendered ``.registry.md`` content (empty if not written yet)."""
        if self._registry_md_path.exists():
            return self._registry_md_path.read_text(encoding="utf-8")
        return ""

    def update(self) -> None:
        """Force a re-render of ``.registry.md``."""
        self._write_markdown()
