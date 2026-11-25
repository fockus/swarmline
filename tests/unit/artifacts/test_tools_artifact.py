"""Tests artifact.create/artifact.load tool factory - TDD.

Split out of ``test_tools.py`` (MINOR 2, fix cycle 3) to respect the
file-size ceiling; see ``test_tools_workspace.py`` for the ``workspace.*``
tools.
"""

from __future__ import annotations

import json

import pytest
from swarmline.artifacts.file_registry import FileRegistry
from swarmline.artifacts.fs_store import FSArtifactStore
from swarmline.artifacts.registry import ArtifactRegistry
from swarmline.artifacts.run_root import ArtifactRoot
from swarmline.artifacts.tools_artifact import create_artifact_tools
from swarmline.artifacts.types import Artifact, ArtifactType

pytestmark = pytest.mark.asyncio


@pytest.fixture
def root(tmp_path):
    return ArtifactRoot.create(tmp_path / "root", run_id="run_1")


class TestArtifactTools:
    async def test_create_then_load_roundtrip(self, tmp_path) -> None:
        store = FSArtifactStore(base_path=tmp_path / "artifacts")
        _specs, executors = create_artifact_tools(store)

        create_result = json.loads(
            await executors["artifact.create"](
                {
                    "filename": "report.md",
                    "content": "# Report",
                    "mime_type": "text/markdown",
                }
            )
        )
        assert create_result["status"] == "ok"

        load_result = json.loads(
            await executors["artifact.load"](
                {"path": create_result["path"], "mime_type": "text/markdown"}
            )
        )
        assert load_result["status"] == "ok"
        assert "# Report" in load_result["preview"]

    async def test_create_registers_into_file_registry(self, tmp_path, root) -> None:
        store = FSArtifactStore(base_path=root.path / "tool_outputs")
        file_registry = FileRegistry(root)
        _specs, executors = create_artifact_tools(store, file_registry=file_registry)

        await executors["artifact.create"](
            {"filename": "report.md", "content": "# Report", "title": "Report"}
        )

        assert file_registry.count() == 1

    async def test_create_missing_filename_and_content_returns_error(
        self, tmp_path
    ) -> None:
        store = FSArtifactStore(base_path=tmp_path / "artifacts")
        _specs, executors = create_artifact_tools(store)

        result = json.loads(await executors["artifact.create"]({}))

        assert result["status"] == "error"

    async def test_create_multi_file_folder_requires_registry(self, tmp_path) -> None:
        store = FSArtifactStore(base_path=tmp_path / "artifacts")
        _specs, executors = create_artifact_tools(store)

        result = json.loads(
            await executors["artifact.create"](
                {"files": {"a.txt": "1"}, "title": "folder-artifact"}
            )
        )

        assert result["status"] == "error"

    async def test_create_single_file_with_registry_is_loadable_by_artifact_id(
        self, root
    ) -> None:
        """BLOCKER 2 repro: single-file create must index into the registry too,
        so artifact.load(artifact_id) can find what artifact.create just made."""
        store = FSArtifactStore(base_path=root.path / "tool_outputs")
        registry = ArtifactRegistry(root)
        _specs, executors = create_artifact_tools(store, registry=registry)

        create_result = json.loads(
            await executors["artifact.create"](
                {"filename": "report.md", "content": "# Report", "title": "Report"}
            )
        )
        assert create_result["status"] == "ok"

        load_result = json.loads(
            await executors["artifact.load"](
                {
                    "artifact_id": create_result["artifact_id"],
                    "mime_type": "text/markdown",
                }
            )
        )

        assert load_result["status"] == "ok"
        assert "# Report" in load_result["preview"]

    async def test_load_rejects_absolute_path_outside_store(self, tmp_path) -> None:
        """BLOCKER 1 repro: an absolute path outside the store must not be readable."""
        store = FSArtifactStore(base_path=tmp_path / "artifacts")
        _specs, executors = create_artifact_tools(store)
        secret = tmp_path / "secret.txt"
        secret.write_text("top secret", encoding="utf-8")

        result = json.loads(
            await executors["artifact.load"](
                {"path": str(secret), "mime_type": "text/plain"}
            )
        )

        assert result["status"] == "error"

    async def test_load_rejects_relative_path_traversal(self, tmp_path) -> None:
        """BLOCKER 1 repro: `../` must not escape the store's base_path."""
        store = FSArtifactStore(base_path=tmp_path / "artifacts")
        _specs, executors = create_artifact_tools(store)
        (tmp_path / "secret.txt").write_text("top secret", encoding="utf-8")

        result = json.loads(
            await executors["artifact.load"](
                {"path": "../secret.txt", "mime_type": "text/plain"}
            )
        )

        assert result["status"] == "error"

    async def test_load_rejects_well_known_absolute_paths(self, tmp_path) -> None:
        """BLOCKER 1 repro: classic /etc/passwd probe must be rejected."""
        store = FSArtifactStore(base_path=tmp_path / "artifacts")
        _specs, executors = create_artifact_tools(store)

        result = json.loads(
            await executors["artifact.load"](
                {"path": "/etc/passwd", "mime_type": "text/plain"}
            )
        )

        assert result["status"] == "error"

    async def test_create_multi_file_folder_with_registry(self, root) -> None:
        store = FSArtifactStore(base_path=root.path / "tool_outputs")
        registry = ArtifactRegistry(root)
        _specs, executors = create_artifact_tools(store, registry=registry)

        result = json.loads(
            await executors["artifact.create"](
                {"files": {"index.html": "<html/>"}, "title": "site", "type": "final"}
            )
        )

        assert result["status"] == "ok"
        assert (
            root.path / "final" / f"{result['artifact_id']}_site" / "index.html"
        ).exists()

    async def test_load_directory_artifact_returns_manifest(self, root) -> None:
        """MAJOR 3 repro: loading a folder artifact (no `file`) must return a
        manifest instead of crashing on Path.read_bytes() (IsADirectoryError)."""
        store = FSArtifactStore(base_path=root.path / "tool_outputs")
        registry = ArtifactRegistry(root)
        _specs, executors = create_artifact_tools(store, registry=registry)
        create_result = json.loads(
            await executors["artifact.create"](
                {
                    "files": {
                        "index.html": "<html/>",
                        "assets/app.js": "console.log(1)",
                    },
                    "title": "site",
                    "type": "final",
                }
            )
        )

        result = json.loads(
            await executors["artifact.load"](
                {"artifact_id": create_result["artifact_id"]}
            )
        )

        assert result["status"] == "ok"
        assert result["is_directory"] is True
        paths = {f["path"] for f in result["files"]}
        assert paths == {"index.html", "assets/app.js"}

    async def test_load_directory_artifact_with_file_returns_its_content(
        self, root
    ) -> None:
        """MAJOR 3 repro: the DoD's 'multi-file folder readable back' must
        work THROUGH artifact.load, not by bypassing it with a raw Path read."""
        store = FSArtifactStore(base_path=root.path / "tool_outputs")
        registry = ArtifactRegistry(root)
        _specs, executors = create_artifact_tools(store, registry=registry)
        create_result = json.loads(
            await executors["artifact.create"](
                {
                    "files": {
                        "index.html": "<html/>",
                        "assets/app.js": "console.log(1)",
                    },
                    "title": "site",
                    "type": "final",
                }
            )
        )

        result = json.loads(
            await executors["artifact.load"](
                {
                    "artifact_id": create_result["artifact_id"],
                    "file": "assets/app.js",
                    "mime_type": "text/javascript",
                }
            )
        )

        assert result["status"] == "ok"
        assert "console.log(1)" in result["preview"]

    async def test_load_directory_artifact_rejects_path_traversal_in_file(
        self, root
    ) -> None:
        secret = root.path / "final" / "secret.txt"
        secret.parent.mkdir(parents=True, exist_ok=True)
        secret.write_text("top secret", encoding="utf-8")
        store = FSArtifactStore(base_path=root.path / "tool_outputs")
        registry = ArtifactRegistry(root)
        _specs, executors = create_artifact_tools(store, registry=registry)
        create_result = json.loads(
            await executors["artifact.create"](
                {"files": {"index.html": "<html/>"}, "title": "site", "type": "final"}
            )
        )

        result = json.loads(
            await executors["artifact.load"](
                {"artifact_id": create_result["artifact_id"], "file": "../secret.txt"}
            )
        )

        assert result["status"] == "error"

    async def test_load_rejects_poisoned_registry_path_outside_roots(
        self, root
    ) -> None:
        """MAJOR 1(a) repro: a crafted `.artifacts.json` entry pointing outside
        the allowed roots must be rejected even though it resolves via
        registry.get(artifact_id) -- registry-resolved paths are NOT
        automatically trusted, they are validated like any other path."""
        store = FSArtifactStore(base_path=root.path / "tool_outputs")
        registry = ArtifactRegistry(root)
        _specs, executors = create_artifact_tools(store, registry=registry)

        outside = root.path.parent / "outside_root_secret.txt"
        outside.write_text("top secret", encoding="utf-8")
        # Poison the index directly (as if `.artifacts.json` had been
        # overwritten by an attacker via some other write path).
        registry._artifacts["art_poisoned"] = Artifact(
            id="art_poisoned",
            type=ArtifactType.FINAL,
            title="poisoned",
            path=outside,
        )

        result = json.loads(
            await executors["artifact.load"](
                {"artifact_id": "art_poisoned", "mime_type": "text/plain"}
            )
        )

        assert result["status"] == "error"
