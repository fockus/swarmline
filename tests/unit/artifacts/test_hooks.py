"""Tests PostStepHookRunner: post-step bookkeeping - TDD."""

from __future__ import annotations

import json

import pytest
from swarmline.artifacts.hooks import PostStepHookRunner
from swarmline.artifacts.run_root import ArtifactRoot

pytestmark = pytest.mark.asyncio


@pytest.fixture
def root(tmp_path):
    return ArtifactRoot.create(tmp_path, run_id="run_1")


class TestPostStepHookRunner:
    async def test_run_saves_raw_tool_output(self, root) -> None:
        runner = PostStepHookRunner(root)

        entry = await runner.run(
            step_id=1,
            task="fetch data",
            tool_name="web.search",
            tool_args={"query": "x"},
            tool_output={"results": []},
            status="ok",
        )

        output_path = root.path / entry.raw_output_path
        assert output_path.exists()
        saved = json.loads(output_path.read_text())
        assert saved["results"] == {"results": []}

    async def test_run_creates_step_note_with_summary(self, root) -> None:
        runner = PostStepHookRunner(root)

        entry = await runner.run(
            step_id=1,
            task="analyze",
            tool_name="workspace.write",
            tool_args={},
            tool_output=None,
            status="ok",
            summary="analysis complete",
        )

        note_path = root.path / entry.notes_path
        assert "analysis complete" in note_path.read_text()

    async def test_run_updates_todo_with_completed_step(self, root) -> None:
        runner = PostStepHookRunner(root)

        await runner.run(
            step_id=1,
            task="write report",
            tool_name="artifact.create",
            tool_args={},
            tool_output=None,
            status="ok",
        )

        todo_content = (root.path / "todo.md").read_text()
        assert "Step 1: write report" in todo_content

    async def test_run_marks_failed_steps_distinctly(self, root) -> None:
        runner = PostStepHookRunner(root)

        await runner.run(
            step_id=1,
            task="risky op",
            tool_name="sandbox.exec",
            tool_args={},
            tool_output=None,
            status="error",
        )

        assert "(FAILED)" in (root.path / "todo.md").read_text()

    async def test_run_appends_journal_entry_with_mutations(self, root) -> None:
        runner = PostStepHookRunner(root)

        entry = await runner.run(
            step_id=1,
            task="t",
            tool_name="workspace.write",
            tool_args={},
            tool_output=None,
            status="ok",
        )

        assert entry.mutations == ("todo.md", "status.md")
        assert runner.journal.get_by_step_id(1) is not None

    async def test_run_records_artifacts_created(self, root) -> None:
        runner = PostStepHookRunner(root)

        entry = await runner.run(
            step_id=1,
            task="t",
            tool_name="artifact.create",
            tool_args={},
            tool_output=None,
            status="ok",
            artifacts_created=["art_123"],
        )

        assert entry.artifacts_created == ("art_123",)

    async def test_multiple_steps_accumulate_in_todo(self, root) -> None:
        runner = PostStepHookRunner(root)

        await runner.run(
            step_id=1,
            task="first",
            tool_name="t1",
            tool_args={},
            tool_output=None,
            status="ok",
        )
        await runner.run(
            step_id=2,
            task="second",
            tool_name="t2",
            tool_args={},
            tool_output=None,
            status="ok",
        )

        todo_content = (root.path / "todo.md").read_text()
        assert "Step 1: first" in todo_content
        assert "Step 2: second" in todo_content
