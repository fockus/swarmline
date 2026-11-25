"""Tests ArtifactRoot: directory layout, create_child, read_parent_file - TDD."""

from __future__ import annotations

import pytest
from swarmline.artifacts.run_root import REQUIRED_DIRS, ArtifactRoot


class TestArtifactRootCreate:
    def test_create_builds_required_directory_layout(self, tmp_path) -> None:
        root = ArtifactRoot.create(tmp_path, run_id="run_1")

        assert root.path == tmp_path / "run_1"
        for sub in REQUIRED_DIRS:
            assert (root.path / sub).is_dir()

    def test_create_generates_run_id_when_not_given(self, tmp_path) -> None:
        root = ArtifactRoot.create(tmp_path)

        assert root.path.parent == tmp_path
        assert root.path.name.startswith("run_")

    def test_fresh_root_has_no_parent(self, tmp_path) -> None:
        root = ArtifactRoot.create(tmp_path, run_id="run_1")

        assert root.parent is None

    def test_create_rejects_path_traversal_run_id(self, tmp_path) -> None:
        """MAJOR 2 repro: a `../`-laden run_id must not escape base_path."""
        with pytest.raises(ValueError):
            ArtifactRoot.create(tmp_path, run_id="../evil")

        assert not (tmp_path.parent / "evil").exists()

    def test_create_rejects_absolute_run_id(self, tmp_path) -> None:
        with pytest.raises(ValueError):
            ArtifactRoot.create(tmp_path, run_id="/abs")

    def test_create_with_relative_base_path_resolves_to_absolute(
        self, tmp_path, monkeypatch
    ) -> None:
        """MAJOR 2 repro: a relative base_path must not leave `.path` relative
        -- downstream `file_path.relative_to(root.path)` calls assume both
        sides are resolved (build_isolated_path always resolves its result)."""
        monkeypatch.chdir(tmp_path)

        root = ArtifactRoot.create("relative_base", run_id="run_1")

        assert root.path.is_absolute()
        assert root.path == (tmp_path / "relative_base" / "run_1").resolve()


class TestSubAgentInheritance:
    def test_create_child_nests_under_children_directory(self, tmp_path) -> None:
        parent = ArtifactRoot.create(tmp_path, run_id="parent")

        child = parent.create_child(child_id="child_1")

        assert child.path == parent.path / "children" / "child_1"
        assert child.parent == parent.path
        for sub in REQUIRED_DIRS:
            assert (child.path / sub).is_dir()

    def test_child_reads_parent_live_file(self, tmp_path) -> None:
        parent = ArtifactRoot.create(tmp_path, run_id="parent")
        (parent.path / "plan.md").write_text(
            "# Plan\n\nDo the thing.", encoding="utf-8"
        )
        child = parent.create_child(child_id="child_1")

        content = child.read_parent_file("plan.md")

        assert content == "# Plan\n\nDo the thing."

    def test_child_reads_nested_parent_file(self, tmp_path) -> None:
        parent = ArtifactRoot.create(tmp_path, run_id="parent")
        (parent.path / "notes" / "step_001.md").write_text("note", encoding="utf-8")
        child = parent.create_child(child_id="child_1")

        assert child.read_parent_file("notes/step_001.md") == "note"

    def test_read_parent_file_missing_file_returns_none(self, tmp_path) -> None:
        parent = ArtifactRoot.create(tmp_path, run_id="parent")
        child = parent.create_child(child_id="child_1")

        assert child.read_parent_file("does_not_exist.md") is None

    def test_read_parent_file_without_parent_returns_none(self, tmp_path) -> None:
        root = ArtifactRoot.create(tmp_path, run_id="solo")

        assert root.read_parent_file("plan.md") is None

    def test_read_parent_file_rejects_path_traversal(self, tmp_path) -> None:
        """Security: a child must never escape the parent root via `../`."""
        parent = ArtifactRoot.create(tmp_path, run_id="parent")
        secret = tmp_path / "secret.txt"
        secret.write_text("top secret", encoding="utf-8")
        child = parent.create_child(child_id="child_1")

        assert child.read_parent_file("../secret.txt") is None
        assert child.read_parent_file("../../secret.txt") is None

    def test_create_child_rejects_path_traversal_child_id(self, tmp_path) -> None:
        """MAJOR 2 repro: a `../`-laden child_id must not escape parent/children/."""
        parent = ArtifactRoot.create(tmp_path, run_id="parent")

        with pytest.raises(ValueError):
            parent.create_child(child_id="../evil")

        assert not (tmp_path / "evil").exists()

    def test_create_child_rejects_absolute_child_id(self, tmp_path) -> None:
        parent = ArtifactRoot.create(tmp_path, run_id="parent")

        with pytest.raises(ValueError):
            parent.create_child(child_id="/abs")
