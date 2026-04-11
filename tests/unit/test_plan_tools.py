"""Tests plan_* tools - tooly planirovaniya for agent. TDD."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from swarmline.orchestration.plan_store import InMemoryPlanStore
from swarmline.orchestration.types import Plan, PlanStep


def _now() -> datetime:
    return datetime.now(tz=UTC)


@pytest.fixture()
def plan_store() -> InMemoryPlanStore:
    return InMemoryPlanStore()


@pytest.fixture()
def mock_planner(plan_store) -> AsyncMock:
    """Mocked PlannerMode."""
    planner = AsyncMock()
    _counter = {"n": 0}

    async def gen(goal, context=""):
        _counter["n"] += 1
        plan = Plan(
            id=f"p{_counter['n']}",
            goal=goal,
            steps=[
                PlanStep(id="s1", description="Шаг 1"),
                PlanStep(id="s2", description="Шаг 2"),
            ],
            created_at=_now(),
        )
        await plan_store.save(plan)
        return plan

    planner.generate_plan = AsyncMock(side_effect=gen)
    planner.approve = AsyncMock(side_effect=lambda p, by: p.approve(by=by))

    async def exec_all(plan):
        for s in plan.steps:
            yield s.complete("done")

    planner.execute_all = exec_all
    return planner


@pytest.fixture()
def tools(mock_planner, plan_store):
    from swarmline.orchestration.manager import PlanManager
    from swarmline.orchestration.plan_tools import create_plan_tools

    manager = PlanManager(planner=mock_planner, plan_store=plan_store)
    return create_plan_tools(manager, user_id="u1", topic_id="t1")


class TestPlanCreate:
    async def test_create_plan(self, tools) -> None:
        _specs, executors = tools
        result = await executors["plan_create"]({"goal": "Подобрать вклад"})
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["plan"]["goal"] == "Подобрать вклад"
        assert data["plan"]["status"] == "draft"
        assert len(data["plan"]["steps"]) == 2

    async def test_create_auto_execute(self, tools) -> None:
        _specs, executors = tools
        result = await executors["plan_create"]({"goal": "Задача", "auto_execute": True})
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["plan"]["status"] == "approved"

    async def test_create_empty_goal(self, tools) -> None:
        _specs, executors = tools
        result = await executors["plan_create"]({"goal": ""})
        data = json.loads(result)
        assert data["status"] == "error"


class TestPlanStatus:
    async def test_status(self, tools) -> None:
        _specs, executors = tools
        await executors["plan_create"]({"goal": "g"})
        result = await executors["plan_status"]({})
        data = json.loads(result)
        assert data["status"] == "ok"
        assert len(data["plans"]) >= 1

    async def test_status_empty(self, tools) -> None:
        _specs, executors = tools
        result = await executors["plan_status"]({})
        data = json.loads(result)
        assert data["plans"] == []


class TestPlanExecute:
    async def test_execute(self, tools) -> None:
        _specs, executors = tools
        create_result = await executors["plan_create"]({"goal": "g", "auto_execute": True})
        plan_id = json.loads(create_result)["plan"]["id"]
        result = await executors["plan_execute"]({"plan_id": plan_id})
        data = json.loads(result)
        assert data["status"] == "ok"
        assert len(data["completed_steps"]) == 2

    async def test_execute_missing(self, tools) -> None:
        _specs, executors = tools
        result = await executors["plan_execute"]({"plan_id": "missing"})
        data = json.loads(result)
        assert data["status"] == "error"


class TestToolSpecs:
    def test_all_specs(self, tools) -> None:
        specs, executors = tools
        assert "plan_create" in specs
        assert "plan_status" in specs
        assert "plan_execute" in specs
        assert set(specs.keys()) == set(executors.keys())

    def test_plan_create_schema(self, tools) -> None:
        specs, _ = tools
        schema = specs["plan_create"].parameters
        assert "goal" in schema["properties"]
        assert "auto_execute" in schema["properties"]
