"""Unit tests for PipelineBuilder and Pipeline integration."""

from __future__ import annotations

import pytest

from swarmline.pipeline.builder import PipelineBuilder
from swarmline.pipeline.pipeline import Pipeline
from swarmline.pipeline.runner import PipelineRunner
from swarmline.pipeline.types import (
    BudgetPolicy,
    PhaseStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SIMPLE_GRAPH = {
    "id": "root",
    "name": "Root Agent",
    "role": "orchestrator",
    "lifecycle": "supervised",
    "children": [
        {
            "id": "worker1",
            "name": "Worker 1",
            "role": "worker",
            "lifecycle": "supervised",
        },
        {
            "id": "worker2",
            "name": "Worker 2",
            "role": "worker",
            "lifecycle": "supervised",
        },
    ],
}


async def _mock_runner(
    agent_id: str,
    task_id: str,
    goal: str,
    prompt: str,
) -> str:
    return f"Result from {agent_id}: {goal}"


# ---------------------------------------------------------------------------
# PipelineBuilder
# ---------------------------------------------------------------------------


class TestPipelineBuilder:
    async def test_minimal_build(self) -> None:
        pipeline = await (
            PipelineBuilder()
            .with_agents_from_dict(_SIMPLE_GRAPH)
            .with_runner(_mock_runner)
            .add_phase("p1", "Phase 1", "Do something")
            .build()
        )
        assert isinstance(pipeline, Pipeline)

    async def test_build_without_runner_raises(self) -> None:
        with pytest.raises(ValueError, match="Runner is required"):
            await (
                PipelineBuilder()
                .with_agents_from_dict(_SIMPLE_GRAPH)
                .add_phase("p1", "Phase 1", "Do something")
                .build()
            )

    async def test_build_with_budget(self) -> None:
        pipeline = await (
            PipelineBuilder()
            .with_agents_from_dict(_SIMPLE_GRAPH)
            .with_runner(_mock_runner)
            .add_phase("p1", "Phase 1", "Do something")
            .with_budget(BudgetPolicy(max_total_usd=10.0))
            .build()
        )
        assert pipeline._budget is not None

    async def test_build_with_circuit_breaker(self) -> None:
        pipeline = await (
            PipelineBuilder()
            .with_agents_from_dict(_SIMPLE_GRAPH)
            .with_runner(_mock_runner)
            .add_phase("p1", "Phase 1", "Do something")
            .with_circuit_breaker(threshold=2, cooldown=5.0)
            .build()
        )
        assert isinstance(pipeline, Pipeline)

    async def test_build_with_callback_gate(self) -> None:
        async def my_gate(phase_id: str, results: dict) -> bool:
            return True

        pipeline = await (
            PipelineBuilder()
            .with_agents_from_dict(_SIMPLE_GRAPH)
            .with_runner(_mock_runner)
            .add_phase("p1", "Phase 1", "Do something")
            .add_callback_gate("p1", "test_gate", my_gate)
            .build()
        )
        assert "p1" in pipeline._gates

    async def test_fluent_chain_returns_self(self) -> None:
        builder = PipelineBuilder()
        result = (
            builder.with_runner(_mock_runner)
            .add_phase("p1", "Phase 1", "goal")
            .with_budget(BudgetPolicy())
            .with_max_concurrent(3)
            .with_circuit_breaker()
        )
        assert result is builder

    async def test_multiple_phases_preserve_order(self) -> None:
        pipeline = await (
            PipelineBuilder()
            .with_agents_from_dict(_SIMPLE_GRAPH)
            .with_runner(_mock_runner)
            .add_phase("plan", "Planning", "Plan things")
            .add_phase("exec", "Execution", "Execute things")
            .add_phase("review", "Review", "Review things")
            .build()
        )
        phase_ids = [p.id for p in pipeline._phases]
        assert phase_ids == ["plan", "exec", "review"]


# ---------------------------------------------------------------------------
# Pipeline run
# ---------------------------------------------------------------------------


class TestPipelineRun:
    async def test_run_single_phase(self) -> None:
        pipeline = await (
            PipelineBuilder()
            .with_agents_from_dict(_SIMPLE_GRAPH)
            .with_runner(_mock_runner)
            .add_phase("p1", "Phase 1", "Do something")
            .build()
        )
        result = await pipeline.run("Test goal")
        assert result.status == "completed"
        assert len(result.phases) == 1
        assert result.phases[0].status == PhaseStatus.COMPLETED

    async def test_run_multiple_phases(self) -> None:
        pipeline = await (
            PipelineBuilder()
            .with_agents_from_dict(_SIMPLE_GRAPH)
            .with_runner(_mock_runner)
            .add_phase("p1", "Plan", "Plan")
            .add_phase("p2", "Execute", "Execute")
            .build()
        )
        result = await pipeline.run("Test goal")
        assert result.status == "completed"
        assert len(result.phases) == 2

    async def test_gate_failure_stops_pipeline(self) -> None:
        async def fail_gate(phase_id: str, results: dict) -> bool:
            return False

        pipeline = await (
            PipelineBuilder()
            .with_agents_from_dict(_SIMPLE_GRAPH)
            .with_runner(_mock_runner)
            .add_phase("p1", "Phase 1", "Do something")
            .add_phase("p2", "Phase 2", "Do more")
            .add_callback_gate("p1", "blocker", fail_gate)
            .build()
        )
        result = await pipeline.run("Test goal")
        assert result.status == "failed"
        assert result.phases[0].status == PhaseStatus.FAILED
        # Phase 2 should be recorded as SKIPPED (not executed)
        assert len(result.phases) == 2
        assert result.phases[1].status == PhaseStatus.SKIPPED

    async def test_gate_pass_continues(self) -> None:
        async def pass_gate(phase_id: str, results: dict) -> bool:
            return True

        pipeline = await (
            PipelineBuilder()
            .with_agents_from_dict(_SIMPLE_GRAPH)
            .with_runner(_mock_runner)
            .add_phase("p1", "Phase 1", "Do something")
            .add_phase("p2", "Phase 2", "Do more")
            .add_callback_gate("p1", "ok_gate", pass_gate)
            .build()
        )
        result = await pipeline.run("Test goal")
        assert result.status == "completed"
        assert len(result.phases) == 2

    async def test_pipeline_stop_marks_stopped(self) -> None:
        """Pipeline.stop() sets stopped flag, run() returns stopped status."""
        pipeline = await (
            PipelineBuilder()
            .with_agents_from_dict(_SIMPLE_GRAPH)
            .with_runner(_mock_runner)
            .add_phase("p1", "Phase 1", "Do something")
            .build()
        )
        status_before = pipeline.get_status()
        assert status_before["stopped"] is False
        await pipeline.stop()
        status_after = pipeline.get_status()
        assert status_after["stopped"] is True

    async def test_budget_exceeded_before_phase(self) -> None:
        pipeline = await (
            PipelineBuilder()
            .with_agents_from_dict(_SIMPLE_GRAPH)
            .with_runner(_mock_runner)
            .add_phase("p1", "Phase 1", "Do something")
            .with_budget(BudgetPolicy(max_total_usd=0.01))
            .build()
        )
        # Manually exhaust budget
        from swarmline.pipeline.types import CostRecord

        pipeline._budget.record(CostRecord(agent_id="a1", task_id="t0", cost_usd=1.0))

        result = await pipeline.run("Test goal")
        assert result.status == "failed"
        assert "budget" in result.phases[0].error.lower()


# ---------------------------------------------------------------------------
# PipelineRunner
# ---------------------------------------------------------------------------


class TestPipelineRunner:
    async def test_runner_run_all(self) -> None:
        pipeline = await (
            PipelineBuilder()
            .with_agents_from_dict(_SIMPLE_GRAPH)
            .with_runner(_mock_runner)
            .add_phase("p1", "Phase 1", "Do something")
            .build()
        )
        runner = PipelineRunner(pipeline)
        result = await runner.run_all("Test goal")
        assert result.status == "completed"

    async def test_runner_get_status(self) -> None:
        pipeline = await (
            PipelineBuilder()
            .with_agents_from_dict(_SIMPLE_GRAPH)
            .with_runner(_mock_runner)
            .add_phase("p1", "Phase 1", "Do something")
            .build()
        )
        runner = PipelineRunner(pipeline)
        status = runner.get_status()
        assert "total_phases" in status
        assert status["total_phases"] == 1

    async def test_runner_on_phase_complete(self) -> None:
        pipeline = await (
            PipelineBuilder()
            .with_agents_from_dict(_SIMPLE_GRAPH)
            .with_runner(_mock_runner)
            .add_phase("p1", "Phase 1", "Do something")
            .build()
        )
        runner = PipelineRunner(pipeline)
        events: list[dict] = []
        runner.on_phase_complete(lambda data: events.append(data))
        await runner.run_all("Test goal")
        assert len(events) >= 1
