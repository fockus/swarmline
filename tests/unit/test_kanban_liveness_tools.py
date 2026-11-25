"""Tests for the opt-in create_kanban_liveness_tools factory (Sprint J, AGR-007).

TDD: written before `create_kanban_liveness_tools` exists (must fail on
import first). Deliberately a SEPARATE factory from `create_kanban_tools` —
`create_kanban_tools` stays frozen at exactly six tools (REQ-ORC-012,
`test_kanban_tools.py::TestToolSpecs`) because
`infrastructure/orchestrator/dispatch_toolset.py` derives its dispatch-only
toolset's exact nine-tool contract (REQ-ORC-030) from it; the two liveness
tools below are additive, wired separately into the MAIN agent's runtime
toolset (`RuntimeToolFactory.build_kanban_tools`), not the dispatch-only one.
"""

from __future__ import annotations

import json

import pytest

from swarmline.kanban.inmemory import InMemoryKanbanStore
from swarmline.kanban.tools import create_kanban_liveness_tools

_TWO_TOOL_NAMES = {"kanban_claim", "kanban_heartbeat"}


@pytest.fixture()
def store() -> InMemoryKanbanStore:
    return InMemoryKanbanStore()


@pytest.fixture()
def tools(store: InMemoryKanbanStore):
    return create_kanban_liveness_tools(store)


class TestToolSpecs:
    def test_exactly_two_tools_in_specs_and_executors(self, tools) -> None:
        specs, executors = tools
        assert set(specs.keys()) == _TWO_TOOL_NAMES
        assert set(executors.keys()) == _TWO_TOOL_NAMES


class TestKanbanClaim:
    async def test_claim_records_assignee_and_liveness_timestamps(
        self, tools, store: InMemoryKanbanStore
    ) -> None:
        from swarmline.kanban.types import KanbanTask

        await store.create_task(KanbanTask(id="t1", title="Task"))
        _specs, executors = tools

        result = json.loads(
            await executors["kanban_claim"](
                {"task_id": "t1", "assignee": "claude-sonnet-4"}
            )
        )

        assert result["status"] == "ok"
        assert result["task"]["assignee"] == "claude-sonnet-4"
        assert result["task"]["claimed_at"] is not None
        assert result["task"]["last_heartbeat_at"] is not None

    async def test_claim_unknown_task_returns_error(self, tools) -> None:
        _specs, executors = tools
        result = json.loads(
            await executors["kanban_claim"]({"task_id": "missing", "assignee": "a"})
        )
        assert result["status"] == "error"

    async def test_claim_missing_assignee_returns_error(
        self, tools, store: InMemoryKanbanStore
    ) -> None:
        from swarmline.kanban.types import KanbanTask

        await store.create_task(KanbanTask(id="t1", title="Task"))
        _specs, executors = tools
        result = json.loads(
            await executors["kanban_claim"]({"task_id": "t1", "assignee": ""})
        )
        assert result["status"] == "error"


class TestKanbanHeartbeat:
    async def test_heartbeat_after_claim_bumps_liveness(
        self, tools, store: InMemoryKanbanStore
    ) -> None:
        from swarmline.kanban.types import KanbanTask

        await store.create_task(KanbanTask(id="t1", title="Task"))
        _specs, executors = tools
        claimed = json.loads(
            await executors["kanban_claim"](
                {"task_id": "t1", "assignee": "claude-sonnet-4"}
            )
        )
        first_beat = claimed["task"]["last_heartbeat_at"]

        result = json.loads(await executors["kanban_heartbeat"]({"task_id": "t1"}))

        assert result["status"] == "ok"
        assert result["task"]["last_heartbeat_at"] >= first_beat

    async def test_heartbeat_unclaimed_task_returns_error(
        self, tools, store: InMemoryKanbanStore
    ) -> None:
        from swarmline.kanban.types import KanbanTask

        await store.create_task(KanbanTask(id="t1", title="Task"))
        _specs, executors = tools
        result = json.loads(await executors["kanban_heartbeat"]({"task_id": "t1"}))
        assert result["status"] == "error"

    async def test_heartbeat_unknown_task_returns_error(self, tools) -> None:
        _specs, executors = tools
        result = json.loads(await executors["kanban_heartbeat"]({"task_id": "missing"}))
        assert result["status"] == "error"
