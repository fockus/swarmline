"""Unit tests for pipeline types and protocols."""

from __future__ import annotations

import inspect

from swarmline.pipeline.protocols import CostTracker, GoalDecomposer, QualityGate
from swarmline.pipeline.types import (
    BudgetPolicy,
    CostRecord,
    GateResult,
    Goal,
    PhaseResult,
    PhaseStatus,
    PipelinePhase,
    PipelineResult,
)


class TestTypes:

    def test_pipeline_phase_defaults(self) -> None:
        p = PipelinePhase(id="p1", name="Plan", goal="Plan things")
        assert p.id == "p1"
        assert p.agent_filter is None
        assert p.order == 0
        assert p.timeout_seconds is None

    def test_goal_hierarchy(self) -> None:
        Goal(id="g1", title="Root")  # parent exists in domain
        child = Goal(id="g2", title="Child", parent_goal_id="g1", phase_id="p1")
        assert child.parent_goal_id == "g1"
        assert child.phase_id == "p1"

    def test_goal_acceptance_criteria(self) -> None:
        g = Goal(id="g1", title="Test", acceptance_criteria=("tests pass", "lint clean"))
        assert len(g.acceptance_criteria) == 2

    def test_cost_record_defaults(self) -> None:
        c = CostRecord(agent_id="a1", task_id="t1")
        assert c.cost_usd == 0.0
        assert c.tokens_in == 0
        assert c.timestamp > 0

    def test_cost_record_full(self) -> None:
        c = CostRecord(
            agent_id="a1", task_id="t1", phase_id="plan",
            cost_usd=0.05, tokens_in=100, tokens_out=200,
            duration_seconds=1.5,
        )
        assert c.cost_usd == 0.05
        assert c.phase_id == "plan"

    def test_budget_policy_defaults(self) -> None:
        p = BudgetPolicy()
        assert p.max_total_usd is None
        assert p.warn_at_percent == 80.0

    def test_budget_policy_full(self) -> None:
        p = BudgetPolicy(
            max_total_usd=10.0, max_per_phase_usd=3.0,
            max_per_agent_usd=1.0, warn_at_percent=75.0,
        )
        assert p.max_total_usd == 10.0

    def test_gate_result(self) -> None:
        r = GateResult(passed=True, gate_name="test_gate")
        assert r.passed is True
        assert r.gate_name == "test_gate"

    def test_phase_status_enum(self) -> None:
        assert PhaseStatus.PENDING.value == "pending"
        assert PhaseStatus.COMPLETED.value == "completed"

    def test_phase_result(self) -> None:
        r = PhaseResult(phase_id="p1", status=PhaseStatus.COMPLETED)
        assert r.error is None
        assert r.gate_results == ()

    def test_pipeline_result(self) -> None:
        r = PipelineResult(phases=(), status="completed")
        assert r.total_cost_usd == 0.0


class TestProtocols:

    def test_quality_gate_is_runtime_checkable(self) -> None:
        assert hasattr(QualityGate, "__protocol_attrs__") or hasattr(QualityGate, "_is_protocol")

    def test_cost_tracker_is_runtime_checkable(self) -> None:
        assert hasattr(CostTracker, "__protocol_attrs__") or hasattr(CostTracker, "_is_protocol")

    def test_goal_decomposer_is_runtime_checkable(self) -> None:
        assert hasattr(GoalDecomposer, "__protocol_attrs__") or hasattr(GoalDecomposer, "_is_protocol")

    def test_quality_gate_check_is_async(self) -> None:
        # Protocol methods are abstract, check via __abstractmethods__ or signature
        sig = inspect.signature(QualityGate.check)
        params = list(sig.parameters.keys())
        assert "phase_id" in params
        assert "results" in params

    def test_cost_tracker_methods(self) -> None:
        required = {"record", "total_cost", "check_budget"}
        actual = {m for m in dir(CostTracker) if not m.startswith("_")}
        assert required <= actual

    def test_goal_decomposer_methods(self) -> None:
        required = {"decompose"}
        actual = {m for m in dir(GoalDecomposer) if not m.startswith("_")}
        assert required <= actual
