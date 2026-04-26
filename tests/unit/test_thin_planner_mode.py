"""Tests ThinPlannerMode - TDD: RED -> GREEN. Unit-tests with mocknutym LLM. Verify generate_plan, approve,
execute_step, execute_all, replan.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from swarmline.orchestration.plan_store import InMemoryPlanStore


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _make_plan_json(goal: str = "test") -> str:
    """JSON-response LLM with planom."""
    return json.dumps(
        {
            "goal": goal,
            "steps": [
                {"id": "s1", "description": "Шаг 1: анализ"},
                {"id": "s2", "description": "Шаг 2: реализация"},
                {"id": "s3", "description": "Шаг 3: проверка"},
            ],
        }
    )


def _make_step_result_json(step_id: str, result: str) -> str:
    """JSON-response LLM with resultom stepa."""
    return json.dumps({"step_id": step_id, "result": result})


@pytest.fixture()
def mock_llm() -> AsyncMock:
    """Mocked LLM - returns JSON-responsey."""
    llm = AsyncMock()
    llm.generate.return_value = _make_plan_json()
    return llm


@pytest.fixture()
def plan_store() -> InMemoryPlanStore:
    return InMemoryPlanStore()


@pytest.fixture()
def planner(mock_llm, plan_store):
    from swarmline.orchestration.thin_planner import ThinPlannerMode

    return ThinPlannerMode(llm=mock_llm, plan_store=plan_store)


class TestThinPlannerGenerate:
    """generate_plan: LLM → Plan."""

    async def test_generate_plan_basic(self, planner, mock_llm) -> None:
        plan = await planner.generate_plan("Подобрать вклад", "context")
        assert plan.goal == "Подобрать вклад"
        assert plan.status == "draft"
        assert len(plan.steps) == 3
        mock_llm.generate.assert_called_once()

    async def test_generate_plan_saves_to_store(self, planner, plan_store) -> None:
        plan = await planner.generate_plan("goal", "ctx")
        loaded = await plan_store.load(plan.id)
        assert loaded is not None
        assert loaded.goal == "goal"

    async def test_generate_plan_unique_ids(self, planner) -> None:
        p1 = await planner.generate_plan("g1", "c1")
        p2 = await planner.generate_plan("g2", "c2")
        assert p1.id != p2.id


class TestThinPlannerApprove:
    """approve: draft → approved."""

    async def test_approve_plan(self, planner) -> None:
        plan = await planner.generate_plan("g", "c")
        approved_plan = await planner.approve(plan, by="system")
        assert approved_plan.status == "approved"
        assert approved_plan.approved_by == "system"

    async def test_approve_saves_to_store(self, planner, plan_store) -> None:
        plan = await planner.generate_plan("g", "c")
        _approved = await planner.approve(plan, by="user")
        loaded = await plan_store.load(plan.id)
        assert loaded is not None
        assert loaded.status == "approved"


class TestThinPlannerExecuteStep:
    """execute_step: run odin step."""

    async def test_execute_step(self, planner, mock_llm) -> None:
        mock_llm.generate.side_effect = [
            _make_plan_json(),
            _make_step_result_json("s1", "Найдено 5 вкладов"),
        ]
        plan = await planner.generate_plan("g", "c")
        plan = await planner.approve(plan, by="system")

        step = await planner.execute_step(plan, "s1")
        assert step.status == "completed"
        assert step.result == "Найдено 5 вкладов"

    async def test_execute_step_updates_store(
        self, planner, mock_llm, plan_store
    ) -> None:
        mock_llm.generate.side_effect = [
            _make_plan_json(),
            _make_step_result_json("s1", "done"),
        ]
        plan = await planner.generate_plan("g", "c")
        plan = await planner.approve(plan, by="system")
        await planner.execute_step(plan, "s1")

        loaded = await plan_store.load(plan.id)
        assert loaded is not None
        assert loaded.steps[0].status == "completed"


class TestThinPlannerExecuteAll:
    """execute_all: run vse steps."""

    async def test_execute_all_steps(self, planner, mock_llm) -> None:
        mock_llm.generate.side_effect = [
            _make_plan_json(),
            _make_step_result_json("s1", "r1"),
            _make_step_result_json("s2", "r2"),
            _make_step_result_json("s3", "r3"),
        ]
        plan = await planner.generate_plan("g", "c")
        plan = await planner.approve(plan, by="system")

        results = []
        async for step in planner.execute_all(plan):
            results.append(step)

        assert len(results) == 3
        assert all(s.status == "completed" for s in results)

    async def test_execute_all_marks_plan_completed(
        self, planner, mock_llm, plan_store
    ) -> None:
        mock_llm.generate.side_effect = [
            _make_plan_json(),
            _make_step_result_json("s1", "r1"),
            _make_step_result_json("s2", "r2"),
            _make_step_result_json("s3", "r3"),
        ]
        plan = await planner.generate_plan("g", "c")
        plan = await planner.approve(plan, by="system")

        async for _step in planner.execute_all(plan):
            pass

        loaded = await plan_store.load(plan.id)
        assert loaded is not None
        assert loaded.status == "completed"

    async def test_execute_all_stops_on_failure(self, planner, mock_llm) -> None:
        mock_llm.generate.side_effect = [
            _make_plan_json(),
            _make_step_result_json("s1", "r1"),
            Exception("LLM failed"),
        ]
        plan = await planner.generate_plan("g", "c")
        plan = await planner.approve(plan, by="system")

        results = []
        async for step in planner.execute_all(plan):
            results.append(step)

        assert len(results) == 2
        assert results[0].status == "completed"
        assert results[1].status == "failed"

    async def test_execute_all_rejects_unapproved_plan(
        self, planner, mock_llm, plan_store
    ) -> None:
        """Draft plan must fail before any execution side effects."""
        plan = await planner.generate_plan("g", "c")
        mock_llm.generate.reset_mock()

        with pytest.raises(ValueError, match="approved"):
            async for _step in planner.execute_all(plan):
                pass

        loaded = await plan_store.load(plan.id)
        assert loaded is not None
        assert loaded.status == "draft"
        mock_llm.generate.assert_not_called()


class TestThinPlannerReplan:
    """replan: peregenotrirovat plan."""

    async def test_replan(self, planner, mock_llm) -> None:
        mock_llm.generate.side_effect = [
            _make_plan_json("original"),
            _make_plan_json("revised"),
        ]
        plan = await planner.generate_plan("original", "c")
        new_plan = await planner.replan(plan, "нужно другой подход")

        assert new_plan.id != plan.id
        assert new_plan.status == "draft"
        assert mock_llm.generate.call_count == 2


class TestThinPlannerProtocol:
    """ThinPlannerMode realizuet PlannerMode Protocol."""

    def test_isinstance(self, planner) -> None:
        # Verify structurally - vse metody est
        assert hasattr(planner, "generate_plan")
        assert hasattr(planner, "approve")
        assert hasattr(planner, "execute_step")
        assert hasattr(planner, "execute_all")
        assert hasattr(planner, "replan")
