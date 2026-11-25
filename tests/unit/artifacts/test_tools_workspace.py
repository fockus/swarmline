"""Tests workspace.* tool factory - TDD.

Split out of ``test_tools.py`` (MINOR 2, fix cycle 3) to respect the
file-size ceiling; see ``test_tools_artifact.py`` for the ``artifact.*``
tools.
"""

from __future__ import annotations

import json

import pytest
from swarmline.artifacts.file_registry import FileRegistry
from swarmline.artifacts.live_files import LiveFilesManager
from swarmline.artifacts.run_root import ArtifactRoot
from swarmline.artifacts.tools_workspace import create_workspace_tools

pytestmark = pytest.mark.asyncio


@pytest.fixture
def root(tmp_path):
    return ArtifactRoot.create(tmp_path / "root", run_id="run_1")


class TestWorkspaceTools:
    @pytest.fixture
    def wired(self, root):
        file_registry = FileRegistry(root)
        live_files = LiveFilesManager(root)
        specs, executors = create_workspace_tools(root, file_registry, live_files)
        return root, file_registry, specs, executors

    async def test_write_then_read_roundtrip(self, wired) -> None:
        _root, _fr, _specs, executors = wired

        write_result = json.loads(
            await executors["workspace.write"](
                {"filename": "notes/analysis.md", "content": "insights"}
            )
        )
        assert write_result["status"] == "ok"

        read_result = json.loads(
            await executors["workspace.read"]({"filename": "notes/analysis.md"})
        )
        assert read_result["content"] == "insights"

    async def test_write_registers_into_file_registry(self, wired) -> None:
        _root, file_registry, _specs, executors = wired

        await executors["workspace.write"](
            {"filename": "notes/a.md", "content": "note body"}
        )

        assert file_registry.get_by_path("notes/a.md") is not None

    async def test_write_rejects_protected_directory(self, wired) -> None:
        _root, _fr, _specs, executors = wired

        result = json.loads(
            await executors["workspace.write"](
                {"filename": "tool_outputs/hack.json", "content": "{}"}
            )
        )

        assert result["status"] == "error"

    async def test_write_rejects_path_traversal(self, wired) -> None:
        _root, _fr, _specs, executors = wired

        result = json.loads(
            await executors["workspace.write"](
                {"filename": "../../etc/passwd", "content": "pwned"}
            )
        )

        assert result["status"] == "error"

    async def test_write_rejects_in_root_traversal_into_protected_dir(
        self, wired
    ) -> None:
        """MAJOR 1 repro: `notes/../tool_outputs/hack.json` resolves inside the
        root (build_isolated_path allows it) but must still be recognized as
        `tool_outputs/` -- checks must run on the canonical, not raw, path."""
        root, _fr, _specs, executors = wired

        result = json.loads(
            await executors["workspace.write"](
                {"filename": "notes/../tool_outputs/hack.json", "content": "{}"}
            )
        )

        assert result["status"] == "error"
        assert not (root.path / "tool_outputs" / "hack.json").exists()

    async def test_write_in_root_traversal_to_live_file_goes_through_versioning(
        self, wired
    ) -> None:
        """MAJOR 1 repro: `notes/../plan.md` must be treated as the live file
        `plan.md` (versioned write), not as a raw notes/-relative bypass."""
        root, _fr, _specs, executors = wired

        result = json.loads(
            await executors["workspace.write"](
                {"filename": "notes/../plan.md", "content": "sneaky plan"}
            )
        )

        assert result["status"] == "ok"
        assert "version" in result
        assert (root.path / "plan.md").read_text(encoding="utf-8") == "sneaky plan"

    async def test_write_rejects_internal_index_file_artifacts_json(
        self, wired
    ) -> None:
        """MAJOR 1(b) repro: `.artifacts.json` must not be writable through
        workspace.write -- it's not in _PROTECTED_TOP_DIRS (root-level file,
        not a directory), but overwriting it would let an attacker poison the
        artifact_id -> path index read by artifact.load."""
        root, _fr, _specs, executors = wired

        result = json.loads(
            await executors["workspace.write"](
                {"filename": ".artifacts.json", "content": '{"artifacts": []}'}
            )
        )

        assert result["status"] == "error"

    async def test_write_rejects_internal_registry_and_journal_files(
        self, wired
    ) -> None:
        _root, _fr, _specs, executors = wired

        for filename in (".registry.md", ".registry.json", ".journal.jsonl"):
            result = json.loads(
                await executors["workspace.write"](
                    {"filename": filename, "content": "poison"}
                )
            )
            assert result["status"] == "error", filename

    async def test_read_rejects_path_traversal(self, wired) -> None:
        _root, _fr, _specs, executors = wired

        result = json.loads(
            await executors["workspace.read"]({"filename": "../secret.txt"})
        )

        assert result["status"] == "error"

    async def test_update_todo_and_update_plan_version(self, wired) -> None:
        _root, _fr, _specs, executors = wired

        first = json.loads(
            await executors["workspace.update_todo"]({"content": "todo v1"})
        )
        second = json.loads(
            await executors["workspace.update_todo"]({"content": "todo v2"})
        )
        plan = json.loads(
            await executors["workspace.update_plan"]({"content": "plan v1"})
        )

        assert first["version"] == 0
        assert second["version"] == 1
        assert plan["status"] == "ok"

    async def test_search_finds_registered_files(self, wired) -> None:
        _root, file_registry, _specs, executors = wired
        file_registry.add(
            path="notes/rev.md", description="revenue analysis", category="notes"
        )

        result = json.loads(await executors["workspace.search"]({"query": "revenue"}))

        assert result["status"] == "ok"
        assert any(r["path"] == "notes/rev.md" for r in result["results"])

    async def test_list_files_lists_written_files(self, wired) -> None:
        _root, _fr, _specs, executors = wired
        await executors["workspace.write"]({"filename": "notes/a.md", "content": "x"})

        result = json.loads(
            await executors["workspace.list_files"]({"directory": "notes"})
        )

        assert "notes/a.md" in result["files"] or "a.md" in result["files"]

    async def test_list_files_rejects_relative_path_traversal(self, wired) -> None:
        """MAJOR 1 repro: `directory="../"` must not escape the workspace root."""
        _root, _fr, _specs, executors = wired

        result = json.loads(
            await executors["workspace.list_files"]({"directory": "../"})
        )

        assert result["status"] == "error"

    async def test_list_files_rejects_absolute_directory(self, wired) -> None:
        """MAJOR 1 repro: an absolute directory must not be listable."""
        _root, _fr, _specs, executors = wired

        result = json.loads(
            await executors["workspace.list_files"]({"directory": "/tmp"})
        )

        assert result["status"] == "error"

    async def test_write_and_list_files_with_relative_base_path(
        self, tmp_path, monkeypatch
    ) -> None:
        """MAJOR 2 repro: workspace.write/list_files must return normal JSON
        (not raise) when the ArtifactRoot was created from a relative
        base_path -- the unresolved root.path previously broke
        file_path.relative_to(root.path) with an uncaught ValueError."""
        monkeypatch.chdir(tmp_path)
        root = ArtifactRoot.create("relative_base", run_id="run_1")
        file_registry = FileRegistry(root)
        live_files = LiveFilesManager(root)
        _specs, executors = create_workspace_tools(root, file_registry, live_files)

        write_result = json.loads(
            await executors["workspace.write"](
                {"filename": "notes/a.md", "content": "hello"}
            )
        )
        list_result = json.loads(
            await executors["workspace.list_files"]({"directory": "notes"})
        )

        assert write_result["status"] == "ok"
        assert list_result["status"] == "ok"
        assert "notes/a.md" in list_result["files"]


class TestWorkspaceMemoryPrompt:
    """Without this reminder + the tools above, the registry is invisible to the model."""

    def test_prompt_mentions_all_tool_names(self) -> None:
        from swarmline.artifacts.tools import WORKSPACE_MEMORY_PROMPT

        for tool_name in (
            "workspace.read",
            "workspace.write",
            "workspace.update_todo",
            "workspace.update_plan",
            "workspace.search",
            "workspace.list_files",
            "artifact.create",
            "artifact.load",
        ):
            assert tool_name in WORKSPACE_MEMORY_PROMPT

    def test_prompt_is_a_markdown_heading_block(self) -> None:
        from swarmline.artifacts.tools import WORKSPACE_MEMORY_PROMPT

        assert WORKSPACE_MEMORY_PROMPT.startswith("## WORKSPACE MEMORY")
