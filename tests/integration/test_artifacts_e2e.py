"""Integration: artifact.create tool -> FSArtifactStore -> FileRegistry ->
context-builder "## Available Files" section.

Proves the full artifacts pipeline (Stage P1 DoD): a created artifact is
tracked, appears in ``.registry.md``, appears in the assembled context, and
is readable back by path -- for a plain file, a table/data file, an image, a
code file, AND a multi-file folder artifact (all four in one test).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from swarmline.artifacts.file_registry import FileRegistry
from swarmline.artifacts.fs_store import FSArtifactStore
from swarmline.artifacts.registry import ArtifactRegistry
from swarmline.artifacts.run_root import ArtifactRoot
from swarmline.artifacts.tools_artifact import create_artifact_tools
from swarmline.artifacts.types import ArtifactType
from swarmline.context.builder import ContextInput, DefaultContextBuilder

pytestmark = pytest.mark.integration


@pytest.fixture
def prompts_dir(tmp_path: Path) -> Path:
    (tmp_path / "identity.md").write_text("Identity.", encoding="utf-8")
    (tmp_path / "guardrails.md").write_text("Guardrails.", encoding="utf-8")
    return tmp_path


class TestToolToFileRegistryToContextBuilder:
    async def test_created_artifact_flows_through_to_available_files_section(
        self, tmp_path: Path, prompts_dir: Path
    ) -> None:
        root = ArtifactRoot.create(tmp_path / "run", run_id="run_1")
        file_registry = FileRegistry(root)
        store = FSArtifactStore(base_path=root.path / "tool_outputs")
        _specs, executors = create_artifact_tools(store, file_registry=file_registry)

        result = json.loads(
            await executors["artifact.create"](
                {
                    "filename": "report.md",
                    "content": "# Quarterly Report",
                    "title": "Quarterly Report",
                    "mime_type": "text/markdown",
                }
            )
        )
        assert result["status"] == "ok"

        # 1. Tracked in .registry.md
        registry_markdown = file_registry.get_markdown()
        assert "Quarterly Report" in registry_markdown

        # 2. Appears in assembled context "## Available Files"
        builder = DefaultContextBuilder(prompts_dir)
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="none",
            user_text="hi",
            active_skill_ids=[],
        )
        built = await builder.build(inp, available_files=registry_markdown)
        assert "## Available Files" in built.system_prompt
        assert "Quarterly Report" in built.system_prompt

        # 3. Readable back by path
        load_result = json.loads(
            await executors["artifact.load"](
                {"path": result["path"], "mime_type": "text/markdown"}
            )
        )
        assert load_result["status"] == "ok"
        assert "Quarterly Report" in load_result["preview"]


class TestAllArtifactKindsE2E:
    """One test proving all four DoD properties for every artifact kind."""

    @pytest.fixture
    def wired(self, tmp_path: Path):
        root = ArtifactRoot.create(tmp_path / "run", run_id="run_1")
        file_registry = FileRegistry(root)
        registry = ArtifactRegistry(root)
        store = FSArtifactStore(base_path=root.path / "tool_outputs")
        return root, file_registry, registry, store

    async def test_markdown_table_image_code_and_folder_all_flow_through(
        self, tmp_path: Path, prompts_dir: Path, wired
    ) -> None:
        root, file_registry, registry, store = wired
        _specs, executors = create_artifact_tools(
            store, registry=registry, file_registry=file_registry
        )

        created: list[dict] = []

        # md
        created.append(
            json.loads(
                await executors["artifact.create"](
                    {"filename": "notes.md", "content": "# Notes", "title": "Notes"}
                )
            )
        )
        # table (csv)
        created.append(
            json.loads(
                await executors["artifact.create"](
                    {
                        "filename": "prices.csv",
                        "content": "a,b\n1,2",
                        "title": "Prices Table",
                    }
                )
            )
        )
        # image (svg text content, binary-ish mime)
        created.append(
            json.loads(
                await executors["artifact.create"](
                    {
                        "filename": "chart.svg",
                        "content": "<svg/>",
                        "title": "Revenue Chart",
                        "mime_type": "image/svg+xml",
                    }
                )
            )
        )
        # code
        created.append(
            json.loads(
                await executors["artifact.create"](
                    {
                        "filename": "script.py",
                        "content": "print('hi')",
                        "title": "Analysis Script",
                    }
                )
            )
        )
        # multi-file folder
        folder_result = json.loads(
            await executors["artifact.create"](
                {
                    "files": {
                        "index.html": "<html/>",
                        "assets/app.js": "console.log(1)",
                    },
                    "title": "Static Site",
                    "type": ArtifactType.FINAL.value,
                }
            )
        )
        created.append(folder_result)

        for result in created:
            assert result["status"] == "ok"

        # 1. All tracked in .registry.md
        registry_markdown = file_registry.get_markdown()
        for title in (
            "Notes",
            "Prices Table",
            "Revenue Chart",
            "Analysis Script",
            "Static Site",
        ):
            assert title in registry_markdown

        # 2. All appear in assembled context "## Available Files"
        builder = DefaultContextBuilder(prompts_dir)
        inp = ContextInput(
            user_id="u1",
            topic_id="t1",
            role_id="none",
            user_text="hi",
            active_skill_ids=[],
        )
        built = await builder.build(inp, available_files=registry_markdown)
        assert "## Available Files" in built.system_prompt
        assert "Static Site" in built.system_prompt

        # 3. Readable back by path -- EVERY non-folder artifact goes through
        # artifact.load (MINOR 1 fix: csv/svg/py used to only be created, not
        # read back through the tool -- only markdown was). Plus the
        # multi-file folder's contents, THROUGH artifact.load (not by
        # bypassing it with a raw Path read -- MAJOR 3 fix: directory
        # artifacts get a manifest + per-file reads via the `file` param).
        non_folder_checks = [
            (created[0], "text/markdown", "# Notes"),
            (created[1], "text/csv", "a,b"),
            (created[2], "image/svg+xml", None),  # image mime -> no text preview
            (created[3], "text/x-python", "print"),
        ]
        for result, mime_type, expected_snippet in non_folder_checks:
            load_result = json.loads(
                await executors["artifact.load"](
                    {"path": result["path"], "mime_type": mime_type}
                )
            )
            assert load_result["status"] == "ok"
            assert load_result["size_bytes"] > 0
            if expected_snippet is not None:
                assert expected_snippet in load_result["preview"]

        manifest = json.loads(
            await executors["artifact.load"](
                {"artifact_id": folder_result["artifact_id"]}
            )
        )
        assert manifest["status"] == "ok"
        assert manifest["is_directory"] is True
        assert {f["path"] for f in manifest["files"]} == {"index.html", "assets/app.js"}

        index_load = json.loads(
            await executors["artifact.load"](
                {
                    "artifact_id": folder_result["artifact_id"],
                    "file": "index.html",
                    "mime_type": "text/html",
                }
            )
        )
        assert index_load["status"] == "ok"
        assert "<html/>" in index_load["preview"]

        app_js_load = json.loads(
            await executors["artifact.load"](
                {
                    "artifact_id": folder_result["artifact_id"],
                    "file": "assets/app.js",
                    "mime_type": "text/javascript",
                }
            )
        )
        assert app_js_load["status"] == "ok"
        assert "console.log(1)" in app_js_load["preview"]
