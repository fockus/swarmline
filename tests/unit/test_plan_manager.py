"""Tests PlanManager - programmnoe upravlenie planami. TDD: RED -> GREEN. DIP: zavisit ot Protocol'ov."""

from __future__ import annotations

import json
from datetime import UTC
from unittest.mock import AsyncMock

import pytest
from swarmline.orchestration.plan_store import InMemoryPlanStore
from swarmline.orchestration.types import Plan, PlanStep


def _plan_json() -> str:
    return json.dumps(
        {
            "goal": "test",
            "steps": [{"id": "s1", "description": "step 1"}],
        }
    )


@pytest.fixture()
def mock_planner() -> AsyncMock:
    """Mocked PlannerMode."""
    from datetime import datetime

    planner = AsyncMock()

    _counter = {"n": 0}

    async def gen(goal, context=""):
        _counter["n"] += 1
        return Plan(
            id=f"p{_counter['n']}",
            goal=goal,
            steps=[PlanStep(id="s1", description="step")],
            created_at=datetime.now(tz=UTC),
        )

    planner.generate_plan = AsyncMock(side_effect=gen)
    planner.approve = AsyncMock(side_effect=lambda p, by: p.approve(by=by))

    async def exec_step(plan, step_id):
        step = next(s for s in plan.steps if s.id == step_id)
        return step.complete("done")

    planner.execute_step = AsyncMock(side_effect=exec_step)

    async def exec_all(plan):
        for s in plan.steps:
            yield s.complete("done")

    planner.execute_all = exec_all
    return planner


@pytest.fixture()
def store() -> InMemoryPlanStore:
    return InMemoryPlanStore()


@pytest.fixture()
def manager(mock_planner, store):
    from swarmline.orchestration.manager import PlanManager

    return PlanManager(planner=mock_planner, plan_store=store)


class TestPlanManagerCreate:
    """create_plan: createdie planov."""

    async def test_create_plan(self, manager) -> None:
        plan = await manager.create_plan("Подобрать вклад", user_id="u1", topic_id="t1")
        assert plan.status == "draft"
        assert plan.goal == "Подобрать вклад"

    async def test_create_auto_approve(self, manager) -> None:
        plan = await manager.create_plan(
            "g", user_id="u", topic_id="t", auto_approve=True
        )
        assert plan.status == "approved"

    async def test_create_saves_to_store(self, manager, store) -> None:
        plan = await manager.create_plan("g", user_id="u", topic_id="t")
        loaded = await store.load(plan.id)
        assert loaded is not None


class TestPlanManagerApprove:
    """approve_plan: programmnoe odobrenie."""

    async def test_approve_by_system(self, manager) -> None:
        plan = await manager.create_plan("g", "u", "t")
        approved = await manager.approve_plan(plan.id, by="system")
        assert approved.status == "approved"

    async def test_approve_nonexistent(self, manager) -> None:
        with pytest.raises(ValueError, match="не найден"):
            await manager.approve_plan("missing", by="system")


class TestPlanManagerExecute:
    """execute_plan: striming vypolnotniya."""

    async def test_execute_plan(self, manager) -> None:
        plan = await manager.create_plan("g", "u", "t", auto_approve=True)
        results = []
        async for step in manager.execute_plan(plan.id):
            results.append(step)
        assert len(results) == 1
        assert results[0].status == "completed"


class TestPlanManagerCancel:
    """cancel_plan: cancellation."""

    async def test_cancel(self, manager, store) -> None:
        plan = await manager.create_plan("g", "u", "t")
        cancelled = await manager.cancel_plan(plan.id)
        assert cancelled.status == "cancelled"

        loaded = await store.load(plan.id)
        assert loaded is not None
        assert loaded.status == "cancelled"


class TestPlanManagerGetList:
    """get_plan, list_plans."""

    async def test_get_plan(self, manager) -> None:
        plan = await manager.create_plan("g", "u", "t")
        loaded = await manager.get_plan(plan.id)
        assert loaded is not None
        assert loaded.id == plan.id

    async def test_list_plans(self, manager) -> None:
        await manager.create_plan("g1", "u", "t")
        await manager.create_plan("g2", "u", "t")
        plans = await manager.list_plans("u", "t")
        assert len(plans) == 2
