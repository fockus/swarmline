"""Tests for the opt-in create_kanban_tools factory. TDD.

Written before `swarmline.kanban.tools` exists (must fail on import first),
per swarmline's contract-first convention.

Covers REQ-ORC-012 (exactly the six minimum tools — create/link/complete/
block/show/list — composed via the same opt-in factory pattern as
`create_plan_tools`) and REQ-ORC-014 (the swarmline core runtime path stays
byte-identical, with no kanban dependency imported, when the kanban module
is never registered).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from swarmline.kanban.inmemory import InMemoryKanbanStore
from swarmline.kanban.tools import create_kanban_tools
from swarmline.kanban.types import KanbanStatus

_SIX_TOOL_NAMES = {
    "kanban_create",
    "kanban_link",
    "kanban_complete",
    "kanban_block",
    "kanban_show",
    "kanban_list",
}


@pytest.fixture()
def store() -> InMemoryKanbanStore:
    return InMemoryKanbanStore()


@pytest.fixture()
def tools(store: InMemoryKanbanStore):
    return create_kanban_tools(store)


class TestToolSpecs:
    def test_exactly_six_tools_in_specs_and_executors(self, tools) -> None:
        specs, executors = tools
        assert set(specs.keys()) == _SIX_TOOL_NAMES
        assert set(executors.keys()) == _SIX_TOOL_NAMES


class TestKanbanCreateAndShow:
    async def test_create_then_show_returns_created_task(self, tools) -> None:
        _specs, executors = tools
        result = await executors["kanban_create"]({"id": "t1", "title": "First task"})
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["task"]["id"] == "t1"
        assert data["task"]["title"] == "First task"
        assert data["task"]["status"] == "todo"

        shown = json.loads(await executors["kanban_show"]({"task_id": "t1"}))
        assert shown["status"] == "ok"
        assert shown["task"]["id"] == "t1"

    async def test_create_missing_fields_returns_error(self, tools) -> None:
        _specs, executors = tools
        result = await executors["kanban_create"]({"id": "", "title": ""})
        data = json.loads(result)
        assert data["status"] == "error"

    async def test_unclaimed_task_dict_is_byte_identical_to_pre_liveness_shape(
        self, tools
    ) -> None:
        """Sprint J fix-cycle 1 (codex round 1, m-6): the six pre-existing
        tools' JSON response shape for an UNCLAIMED task must stay exactly
        what it was before `assignee`/`claimed_at`/`last_heartbeat_at` were
        added to `KanbanTask` — those three keys are omitted entirely (not
        emitted as `null`) unless actually set."""
        _specs, executors = tools
        result = json.loads(
            await executors["kanban_create"]({"id": "t1", "title": "First task"})
        )
        assert set(result["task"].keys()) == {
            "id",
            "title",
            "status",
            "parent_ids",
            "block_kind",
            "block_recurrences",
            "metadata",
        }

    async def test_show_unknown_task_returns_error(self, tools) -> None:
        _specs, executors = tools
        result = await executors["kanban_show"]({"task_id": "missing"})
        data = json.loads(result)
        assert data["status"] == "error"

    async def test_kanban_create_invalid_parent_ids_returns_error(self, tools) -> None:
        _specs, executors = tools
        result = await executors["kanban_create"](
            {"id": "t1", "title": "T", "parent_ids": 1}
        )
        data = json.loads(result)
        assert data["status"] == "error"

    async def test_kanban_create_invalid_metadata_returns_error(self, tools) -> None:
        _specs, executors = tools
        result = await executors["kanban_create"](
            {"id": "t1", "title": "T", "metadata": 1}
        )
        data = json.loads(result)
        assert data["status"] == "error"


class TestKanbanLink:
    async def test_link_then_show_child_reflects_parent(self, tools) -> None:
        _specs, executors = tools
        await executors["kanban_create"]({"id": "parent", "title": "Parent"})
        await executors["kanban_create"]({"id": "child", "title": "Child"})
        link_result = json.loads(
            await executors["kanban_link"]({"parent_id": "parent", "child_id": "child"})
        )
        assert link_result["status"] == "ok"

        shown = json.loads(await executors["kanban_show"]({"task_id": "child"}))
        assert shown["task"]["parent_ids"] == ["parent"]

    async def test_link_unknown_parent_returns_error(self, tools) -> None:
        _specs, executors = tools
        await executors["kanban_create"]({"id": "child", "title": "Child"})
        result = json.loads(
            await executors["kanban_link"]({"parent_id": "ghost", "child_id": "child"})
        )
        assert result["status"] == "error"


class TestKanbanComplete:
    async def test_complete_moves_task_to_done(self, tools) -> None:
        _specs, executors = tools
        await executors["kanban_create"]({"id": "t1", "title": "Task"})
        result = json.loads(await executors["kanban_complete"]({"task_id": "t1"}))
        assert result["status"] == "ok"
        assert result["task"]["status"] == "done"

    async def test_complete_promotes_parent_when_all_children_done(
        self, tools, store: InMemoryKanbanStore
    ) -> None:
        _specs, executors = tools
        await executors["kanban_create"]({"id": "parent", "title": "Parent"})
        await executors["kanban_create"](
            {"id": "child", "title": "Child", "parent_ids": ["parent"]}
        )

        result = json.loads(await executors["kanban_complete"]({"task_id": "child"}))
        assert result["status"] == "ok"
        assert result["promoted"] == ["parent"]

        parent_tasks = await store.list_tasks()
        parent = next(t for t in parent_tasks if t.id == "parent")
        assert parent.status == KanbanStatus.READY

    async def test_complete_unknown_task_returns_error(self, tools) -> None:
        _specs, executors = tools
        result = json.loads(await executors["kanban_complete"]({"task_id": "missing"}))
        assert result["status"] == "error"


class TestKanbanBlock:
    async def test_block_sets_typed_block_kind(self, tools) -> None:
        _specs, executors = tools
        await executors["kanban_create"]({"id": "t1", "title": "Task"})
        result = json.loads(
            await executors["kanban_block"](
                {"task_id": "t1", "block_kind": "needs_input"}
            )
        )
        assert result["status"] == "ok"
        assert result["task"]["status"] == "blocked"
        assert result["task"]["block_kind"] == "needs_input"

    async def test_block_invalid_block_kind_returns_error_without_crashing(
        self, tools
    ) -> None:
        _specs, executors = tools
        await executors["kanban_create"]({"id": "t1", "title": "Task"})
        result = json.loads(
            await executors["kanban_block"](
                {"task_id": "t1", "block_kind": "not_a_real_kind"}
            )
        )
        assert result["status"] == "error"

    async def test_block_missing_block_kind_returns_error(self, tools) -> None:
        _specs, executors = tools
        await executors["kanban_create"]({"id": "t1", "title": "Task"})
        result = json.loads(
            await executors["kanban_block"]({"task_id": "t1", "block_kind": ""})
        )
        assert result["status"] == "error"


class TestKanbanList:
    async def test_list_returns_created_tasks(self, tools) -> None:
        _specs, executors = tools
        await executors["kanban_create"]({"id": "t1", "title": "One"})
        await executors["kanban_create"]({"id": "t2", "title": "Two"})
        result = json.loads(await executors["kanban_list"]({}))
        assert result["status"] == "ok"
        assert {t["id"] for t in result["tasks"]} == {"t1", "t2"}

    async def test_list_status_filter_returns_only_matching(self, tools) -> None:
        _specs, executors = tools
        await executors["kanban_create"]({"id": "t1", "title": "One"})
        await executors["kanban_create"]({"id": "t2", "title": "Two"})
        await executors["kanban_complete"]({"task_id": "t2"})

        result = json.loads(await executors["kanban_list"]({"status": "done"}))
        assert [t["id"] for t in result["tasks"]] == ["t2"]


class TestCoreRuntimeStaysKanbanFree:
    """REQ-ORC-014: the swarmline core path never imports swarmline.kanban."""

    def test_importing_core_swarmline_package_does_not_load_kanban_module(self) -> None:
        """Import the real core entrypoint (`import swarmline`, which pulls in
        Agent/SwarmlineStack/RuntimeFactory — the public surface `bootstrap/`
        and `agent/` compose) in a **fresh subprocess** so `sys.modules` starts
        clean (other tests in this suite already import `swarmline.kanban`
        directly, which would poison an in-process check).
        """
        script = (
            "import sys\n"
            "import swarmline\n"
            "assert 'swarmline.kanban' not in sys.modules, "
            "sorted(m for m in sys.modules if 'kanban' in m)\n"
            "print('OK')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "OK"

    def test_no_core_module_imports_kanban(self) -> None:
        """Grep-style regression: no file outside `swarmline/kanban/` references
        `swarmline.kanban` or a relative `from .kanban` import. Mirrors the
        bounded verification command run for this task.
        """
        src_root = Path(__file__).resolve().parents[2] / "src" / "swarmline"
        offenders = []
        for path in src_root.rglob("*.py"):
            if "kanban" in path.relative_to(src_root).parts:
                continue
            text = path.read_text(encoding="utf-8")
            if "swarmline.kanban" in text or "from .kanban" in text:
                offenders.append(str(path))
        assert offenders == []
