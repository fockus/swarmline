"""Tests StepJournal: append-only persistence (.journal.jsonl) - TDD."""

from __future__ import annotations

import pytest
from swarmline.artifacts.run_root import ArtifactRoot
from swarmline.artifacts.step_journal import StepJournal
from swarmline.artifacts.types import StepJournalEntry


@pytest.fixture
def root(tmp_path):
    return ArtifactRoot.create(tmp_path, run_id="run_1")


def _entry(step_id: int, **overrides) -> StepJournalEntry:
    defaults = dict(
        step_id=step_id, task="task", tool_name="workspace.write", tool_args={}
    )
    defaults.update(overrides)
    return StepJournalEntry(**defaults)


class TestAppend:
    def test_append_persists_to_journal_jsonl(self, root) -> None:
        journal = StepJournal(root)

        journal.append(_entry(1))

        assert (root.path / ".journal.jsonl").exists()
        assert len(journal.get_all()) == 1

    def test_append_survives_reload_from_disk(self, root) -> None:
        journal = StepJournal(root)
        journal.append(_entry(1, summary="first"))
        journal.append(_entry(2, summary="second"))

        reloaded = StepJournal(root)

        assert [e.step_id for e in reloaded.get_all()] == [1, 2]
        assert reloaded.get_all()[1].summary == "second"

    def test_journal_is_append_only_never_rewrites_prior_lines(self, root) -> None:
        journal = StepJournal(root)
        journal.append(_entry(1))
        journal.append(_entry(2))

        lines = (
            (root.path / ".journal.jsonl")
            .read_text(encoding="utf-8")
            .strip()
            .split("\n")
        )

        assert len(lines) == 2


class TestQueries:
    def test_get_recent_returns_last_n_entries(self, root) -> None:
        journal = StepJournal(root)
        for i in range(1, 6):
            journal.append(_entry(i))

        recent = journal.get_recent(2)

        assert [e.step_id for e in recent] == [4, 5]

    def test_get_by_step_id_finds_matching_entry(self, root) -> None:
        journal = StepJournal(root)
        journal.append(_entry(1))
        journal.append(_entry(2, tool_name="artifact.create"))

        entry = journal.get_by_step_id(2)

        assert entry is not None
        assert entry.tool_name == "artifact.create"

    def test_get_by_step_id_missing_returns_none(self, root) -> None:
        journal = StepJournal(root)

        assert journal.get_by_step_id(42) is None

    def test_get_mutations_for_file_filters_by_mutation(self, root) -> None:
        journal = StepJournal(root)
        journal.append(_entry(1, mutations=("todo.md",)))
        journal.append(_entry(2, mutations=("status.md",)))

        entries = journal.get_mutations_for_file("todo.md")

        assert [e.step_id for e in entries] == [1]

    def test_next_step_id_increments_from_max(self, root) -> None:
        journal = StepJournal(root)
        journal.append(_entry(1))
        journal.append(_entry(5))

        assert journal.next_step_id() == 6

    def test_next_step_id_starts_at_one_when_empty(self, root) -> None:
        journal = StepJournal(root)

        assert journal.next_step_id() == 1
