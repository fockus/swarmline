"""Unit tests for BudgetTracker."""

from __future__ import annotations

import pytest

from swarmline.pipeline.budget import BudgetExceededError, BudgetTracker
from swarmline.pipeline.types import BudgetPolicy, CostRecord


class TestBudgetTracker:
    def test_empty_tracker(self) -> None:
        t = BudgetTracker(BudgetPolicy())
        assert t.total_cost() == 0.0
        assert t.check_budget() is True

    def test_record_accumulates(self) -> None:
        t = BudgetTracker(BudgetPolicy())
        t.record(CostRecord(agent_id="a1", task_id="t1", cost_usd=0.5))
        t.record(CostRecord(agent_id="a2", task_id="t2", cost_usd=0.3))
        assert t.total_cost() == pytest.approx(0.8)

    def test_phase_cost(self) -> None:
        t = BudgetTracker(BudgetPolicy())
        t.record(CostRecord(agent_id="a1", task_id="t1", phase_id="plan", cost_usd=0.1))
        t.record(CostRecord(agent_id="a1", task_id="t2", phase_id="exec", cost_usd=0.2))
        t.record(CostRecord(agent_id="a2", task_id="t3", phase_id="plan", cost_usd=0.3))
        assert t.phase_cost("plan") == pytest.approx(0.4)
        assert t.phase_cost("exec") == pytest.approx(0.2)

    def test_agent_cost(self) -> None:
        t = BudgetTracker(BudgetPolicy())
        t.record(CostRecord(agent_id="a1", task_id="t1", cost_usd=0.1))
        t.record(CostRecord(agent_id="a1", task_id="t2", cost_usd=0.2))
        t.record(CostRecord(agent_id="a2", task_id="t3", cost_usd=0.5))
        assert t.agent_cost("a1") == pytest.approx(0.3)
        assert t.agent_cost("a2") == pytest.approx(0.5)

    def test_total_budget_exceeded(self) -> None:
        t = BudgetTracker(BudgetPolicy(max_total_usd=1.0))
        t.record(CostRecord(agent_id="a1", task_id="t1", cost_usd=0.6))
        assert t.check_budget() is True
        t.record(CostRecord(agent_id="a1", task_id="t2", cost_usd=0.5))
        assert t.check_budget() is False
        assert t.is_exceeded() is True

    def test_agent_budget_exceeded(self) -> None:
        t = BudgetTracker(BudgetPolicy(max_per_agent_usd=0.5))
        t.record(CostRecord(agent_id="a1", task_id="t1", cost_usd=0.6))
        assert t.is_agent_exceeded("a1") is True
        assert t.is_agent_exceeded("a2") is False

    def test_phase_budget_exceeded(self) -> None:
        t = BudgetTracker(BudgetPolicy(max_per_phase_usd=0.5))
        t.record(CostRecord(agent_id="a1", task_id="t1", phase_id="plan", cost_usd=0.6))
        assert t.is_phase_exceeded("plan") is True
        assert t.is_phase_exceeded("exec") is False

    def test_get_all_records(self) -> None:
        t = BudgetTracker(BudgetPolicy())
        t.record(CostRecord(agent_id="a1", task_id="t1", cost_usd=0.1))
        t.record(CostRecord(agent_id="a2", task_id="t2", cost_usd=0.2))
        records = t.get_all_records()
        assert len(records) == 2
        assert records[0].agent_id == "a1"


class TestWrapRunner:
    async def test_wrap_runner_records_cost(self) -> None:
        t = BudgetTracker(BudgetPolicy())

        async def mock_runner(
            agent_id: str,
            task_id: str,
            goal: str,
            prompt: str,
        ) -> str:
            return "done"

        wrapped = t.wrap_runner(mock_runner)
        result = await wrapped("a1", "t1", "test", "prompt")
        assert result == "done"
        assert len(t.get_all_records()) == 1
        assert t.get_all_records()[0].agent_id == "a1"
        assert t.get_all_records()[0].duration_seconds > 0

    async def test_wrap_runner_raises_on_exceeded(self) -> None:
        t = BudgetTracker(BudgetPolicy(max_total_usd=0.1))
        t.record(CostRecord(agent_id="a1", task_id="t0", cost_usd=0.2))

        async def mock_runner(
            agent_id: str,
            task_id: str,
            goal: str,
            prompt: str,
        ) -> str:
            return "done"

        wrapped = t.wrap_runner(mock_runner)
        with pytest.raises(BudgetExceededError):
            await wrapped("a1", "t1", "test", "prompt")

    async def test_wrap_runner_raises_on_agent_exceeded(self) -> None:
        t = BudgetTracker(BudgetPolicy(max_per_agent_usd=0.1))
        t.record(CostRecord(agent_id="a1", task_id="t0", cost_usd=0.2))

        async def mock_runner(
            agent_id: str,
            task_id: str,
            goal: str,
            prompt: str,
        ) -> str:
            return "done"

        wrapped = t.wrap_runner(mock_runner)
        with pytest.raises(BudgetExceededError):
            await wrapped("a1", "t1", "test", "prompt")

    async def test_wrap_runner_with_phase_id(self) -> None:
        t = BudgetTracker(BudgetPolicy())

        async def mock_runner(
            agent_id: str,
            task_id: str,
            goal: str,
            prompt: str,
        ) -> str:
            return "done"

        wrapped = t.wrap_runner(mock_runner, phase_id="plan")
        await wrapped("a1", "t1", "test", "prompt")
        assert t.get_all_records()[0].phase_id == "plan"
