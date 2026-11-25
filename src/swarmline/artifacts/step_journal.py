"""StepJournal -- append-only step log (``.journal.jsonl``).

Ported from Aura's ``application/components/workspace/step_journal.py``.
"""

from __future__ import annotations

import json

from swarmline.artifacts.run_root import ArtifactRoot
from swarmline.artifacts.types import StepJournalEntry


class StepJournal:
    """Append-only, JSONL-persisted journal of step executions."""

    def __init__(self, root: ArtifactRoot) -> None:
        self.root = root
        self.entries: list[StepJournalEntry] = []
        self._journal_path = root.path / ".journal.jsonl"
        self._load()

    def _load(self) -> None:
        if not self._journal_path.exists():
            return
        content = self._journal_path.read_text(encoding="utf-8").strip()
        if not content:
            return
        for line in content.split("\n"):
            if line.strip():
                self.entries.append(StepJournalEntry.from_dict(json.loads(line)))

    def _save_entry(self, entry: StepJournalEntry) -> None:
        with self._journal_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict()) + "\n")

    def append(self, entry: StepJournalEntry) -> None:
        """Append ``entry`` to the in-memory list and persist it (append-only)."""
        self.entries.append(entry)
        self._save_entry(entry)

    def get_recent(self, n: int) -> list[StepJournalEntry]:
        """The last ``n`` entries (all of them if fewer than ``n`` exist)."""
        return self.entries[-n:] if len(self.entries) >= n else self.entries[:]

    def get_all(self) -> list[StepJournalEntry]:
        """All entries."""
        return self.entries[:]

    def get_by_step_id(self, step_id: int) -> StepJournalEntry | None:
        """Find the entry for ``step_id``, or None."""
        for entry in self.entries:
            if entry.step_id == step_id:
                return entry
        return None

    def get_mutations_for_file(self, filename: str) -> list[StepJournalEntry]:
        """All entries whose ``mutations`` include ``filename``."""
        return [entry for entry in self.entries if filename in entry.mutations]

    def next_step_id(self) -> int:
        """``max(step_id) + 1``, or 1 if the journal is empty."""
        if not self.entries:
            return 1
        return max(entry.step_id for entry in self.entries) + 1
