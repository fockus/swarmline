"""Tests LiveFilesManager: versioned CRUD + rollback - TDD."""

from __future__ import annotations

import pytest
from swarmline.artifacts.live_files import LiveFilesManager
from swarmline.artifacts.run_root import ArtifactRoot


@pytest.fixture
def root(tmp_path):
    return ArtifactRoot.create(tmp_path, run_id="run_1")


class TestVersionedUpdate:
    def test_first_update_writes_file_and_returns_version_zero(self, root) -> None:
        manager = LiveFilesManager(root)

        version = manager.update_todo("# TODO\n\n- [ ] task 1")

        assert version == 0
        assert (root.path / "todo.md").read_text() == "# TODO\n\n- [ ] task 1"

    def test_second_update_versions_the_prior_content(self, root) -> None:
        manager = LiveFilesManager(root)
        manager.update_todo("version A")

        version = manager.update_todo("version B")

        assert version == 1
        assert (root.path / "todo.md").read_text() == "version B"

    def test_update_plan_and_update_status_are_independent(self, root) -> None:
        manager = LiveFilesManager(root)

        manager.update_plan("my plan")
        manager.update_status("my status")

        assert (root.path / "plan.md").read_text() == "my plan"
        assert (root.path / "status.md").read_text() == "my status"

    def test_generic_update_file_versions_any_live_filename(self, root) -> None:
        manager = LiveFilesManager(root)

        manager.update_file("goal.md", "goal A")
        version = manager.update_file("goal.md", "goal B")

        assert version == 1
        assert (root.path / "goal.md").read_text() == "goal B"


class TestVersionHistoryAndRollback:
    def test_get_version_history_lists_all_saved_versions(self, root) -> None:
        manager = LiveFilesManager(root)
        manager.update_todo("A")
        manager.update_todo("B")
        manager.update_todo("C")

        history = manager.get_version_history("todo.md")

        assert [h["version"] for h in history] == [1, 2]

    def test_get_version_returns_historical_content_for_rollback(self, root) -> None:
        manager = LiveFilesManager(root)
        manager.update_todo("A")
        manager.update_todo("B")

        rolled_back = manager.get_version("todo.md", 1)

        assert rolled_back == "A"

    def test_get_version_missing_version_returns_none(self, root) -> None:
        manager = LiveFilesManager(root)
        manager.update_todo("A")

        assert manager.get_version("todo.md", 99) is None

    def test_version_counters_survive_reload_from_disk(self, root) -> None:
        manager = LiveFilesManager(root)
        manager.update_todo("A")
        manager.update_todo("B")

        reloaded = LiveFilesManager(root)
        version = reloaded.update_todo("C")

        assert version == 2
