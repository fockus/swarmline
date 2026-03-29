"""DefaultChecklistManager -- markdown checklist via MemoryBankProvider."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from cognitia.memory_bank.knowledge_types import ChecklistItem

_CHECKLIST_PATH = "checklist.md"


class DefaultChecklistManager:
    """ChecklistManager wrapping MemoryBankProvider.

    SRP: parse/serialize markdown checklists, delegate storage to provider.
    """

    def __init__(self, provider: Any, path: str = _CHECKLIST_PATH) -> None:
        self._provider = provider
        self._path = path

    async def add_item(self, item: ChecklistItem) -> None:
        """Add a checklist item (appends to end)."""
        items = await self._load_items()
        items.append(item)
        await self._save_items(items)

    async def toggle_item(self, text_prefix: str) -> bool:
        """Toggle done status of first item matching prefix. Returns True if found."""
        items = await self._load_items()
        prefix_lower = text_prefix.lower()
        for i, item in enumerate(items):
            if item.text.lower().startswith(prefix_lower):
                items[i] = replace(item, done=not item.done)
                await self._save_items(items)
                return True
        return False

    async def get_items(self, *, done: bool | None = None) -> list[ChecklistItem]:
        """Get items, optionally filtered by done status."""
        items = await self._load_items()
        if done is None:
            return items
        return [item for item in items if item.done == done]

    async def clear_done(self) -> int:
        """Remove all done items. Returns count removed."""
        items = await self._load_items()
        remaining = [item for item in items if not item.done]
        removed = len(items) - len(remaining)
        if removed > 0:
            await self._save_items(remaining)
        return removed

    # --- Parse/serialize markdown (private) ---

    async def _load_items(self) -> list[ChecklistItem]:
        raw = await self._provider.read_file(self._path)
        if not raw:
            return []
        items: list[ChecklistItem] = []
        for line in raw.strip().split("\n"):
            line = line.strip()
            if line.startswith("- [x] ") or line.startswith("- [X] "):
                items.append(ChecklistItem(text=line[6:].strip(), done=True))
            elif line.startswith("- [ ] "):
                items.append(ChecklistItem(text=line[6:].strip(), done=False))
        return items

    async def _save_items(self, items: list[ChecklistItem]) -> None:
        lines: list[str] = []
        for item in items:
            marker = "x" if item.done else " "
            lines.append(f"- [{marker}] {item.text}")
        await self._provider.write_file(self._path, "\n".join(lines) + "\n")
