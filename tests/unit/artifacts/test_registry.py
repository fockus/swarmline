"""Tests ArtifactRegistry: directory routing, single-file + folder create - TDD."""

from __future__ import annotations

import pytest
from swarmline.artifacts.registry import ArtifactRegistry
from swarmline.artifacts.run_root import ArtifactRoot
from swarmline.artifacts.types import ArtifactType


@pytest.fixture
def root(tmp_path):
    return ArtifactRoot.create(tmp_path, run_id="run_1")


class TestCreateSingleFile:
    def test_create_routes_to_type_directory(self, root) -> None:
        registry = ArtifactRegistry(root)

        artifact = registry.create(
            type=ArtifactType.CHART,
            title="Revenue chart",
            content="<svg/>",
            filename="revenue.svg",
        )

        assert artifact.path == root.path / "charts" / "revenue.svg"
        assert artifact.path.read_text() == "<svg/>"
        assert artifact.size_bytes == len("<svg/>")

    def test_create_live_type_routes_to_root(self, root) -> None:
        registry = ArtifactRegistry(root)

        artifact = registry.create(
            type=ArtifactType.PLAN, title="Plan", content="# Plan", filename="plan.md"
        )

        assert artifact.path == root.path / "plan.md"

    def test_create_persists_to_artifacts_json_index(self, root) -> None:
        registry = ArtifactRegistry(root)
        artifact = registry.create(
            type=ArtifactType.STEP_NOTE, title="Note", content="hello", filename="n1.md"
        )

        reloaded = ArtifactRegistry(root)

        assert reloaded.get(artifact.id) is not None
        assert reloaded.get(artifact.id).title == "Note"

    def test_create_requires_content_and_filename_or_files(self, root) -> None:
        registry = ArtifactRegistry(root)

        with pytest.raises(ValueError):
            registry.create(type=ArtifactType.FINAL, title="oops")

    def test_create_single_file_rejects_path_traversal_in_filename(self, root) -> None:
        """BLOCKER 3 repro: a `../` filename must not escape the typed directory."""
        registry = ArtifactRegistry(root)

        with pytest.raises(ValueError):
            registry.create(
                type=ArtifactType.CHART,
                title="evil",
                content="pwned",
                filename="../../escape.txt",
            )

        assert not (root.path.parent.parent / "escape.txt").exists()


class TestCreateMultiFileFolder:
    def test_create_with_files_writes_all_entries_under_one_folder(self, root) -> None:
        registry = ArtifactRegistry(root)

        artifact = registry.create(
            type=ArtifactType.FINAL,
            title="Static Site",
            files={"index.html": "<html/>", "assets/app.js": "console.log(1)"},
        )

        assert artifact.path.is_dir()
        assert (artifact.path / "index.html").read_text() == "<html/>"
        assert (artifact.path / "assets" / "app.js").read_text() == "console.log(1)"
        assert artifact.size_bytes == len("<html/>") + len("console.log(1)")

    def test_create_folder_rejects_path_traversal_in_file_keys(self, root) -> None:
        registry = ArtifactRegistry(root)

        with pytest.raises(ValueError):
            registry.create(
                type=ArtifactType.FINAL,
                title="evil",
                files={"../../escape.txt": "pwned"},
            )


class TestQueries:
    def test_get_live_and_get_immutable_partition_artifacts(self, root) -> None:
        registry = ArtifactRegistry(root)
        registry.create(
            type=ArtifactType.PLAN, title="Plan", content="p", filename="plan.md"
        )
        registry.create(
            type=ArtifactType.CHART, title="Chart", content="c", filename="c.svg"
        )

        live_paths = {a.path.name for a in registry.get_live()}
        immutable_paths = {a.path.name for a in registry.get_immutable()}

        assert "plan.md" in live_paths
        assert "c.svg" in immutable_paths

    def test_get_by_type_filters_correctly(self, root) -> None:
        registry = ArtifactRegistry(root)
        registry.create(
            type=ArtifactType.CHART, title="c1", content="a", filename="a.svg"
        )
        registry.create(
            type=ArtifactType.CHART, title="c2", content="b", filename="b.svg"
        )
        registry.create(
            type=ArtifactType.DRAFT, title="d1", content="x", filename="x.md"
        )

        charts = registry.get_by_type(ArtifactType.CHART)

        assert len(charts) == 2
        assert all(a.type == ArtifactType.CHART for a in charts)

    def test_list_all_returns_every_artifact(self, root) -> None:
        registry = ArtifactRegistry(root)
        registry.create(
            type=ArtifactType.CHART, title="c1", content="a", filename="a.svg"
        )

        assert len(registry.list_all()) == 1

    def test_register_live_files_discovers_existing_files_on_init(self, root) -> None:
        (root.path / "goal.md").write_text("# Goal", encoding="utf-8")

        registry = ArtifactRegistry(root)

        goals = registry.get_by_type(ArtifactType.GOAL)
        assert len(goals) == 1
        assert goals[0].path == root.path / "goal.md"
