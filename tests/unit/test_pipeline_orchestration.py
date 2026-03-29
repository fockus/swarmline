"""Unit tests for Pipeline._execute_phase_orchestration — false-green detection."""

from __future__ import annotations

from unittest.mock import AsyncMock

from cognitia.pipeline.pipeline import Pipeline
from cognitia.pipeline.types import PhaseStatus, PipelinePhase


class TestPipelineOrchestrationFailureDetection:
    """Bug #4: Pipeline ignores wait_for_task() return value.

    When the root agent fails, wait_for_task() returns None.
    Pipeline must detect this and mark the phase as FAILED,
    not blindly mark it COMPLETED.
    """

    async def test_phase_fails_when_root_task_returns_none(self) -> None:
        """If wait_for_task returns None, phase must be FAILED."""
        orch = AsyncMock()
        orch.start = AsyncMock(return_value="run-1")
        orch.wait_for_task = AsyncMock(return_value=None)
        orch.stop = AsyncMock()

        board = AsyncMock()

        phase = PipelinePhase(id="p1", name="Planning", goal="Plan it", order=0)
        pipeline = Pipeline(
            phases=[phase],
            orchestrator=orch,
            task_board=board,
        )

        result = await pipeline.run("Build something")
        assert len(result.phases) == 1
        assert result.phases[0].status == PhaseStatus.FAILED
        assert result.status == "failed"

    async def test_phase_succeeds_when_root_task_returns_result(self) -> None:
        """If wait_for_task returns a result string, phase is COMPLETED."""
        orch = AsyncMock()
        orch.start = AsyncMock(return_value="run-1")
        orch.wait_for_task = AsyncMock(return_value="Task completed successfully")
        orch.stop = AsyncMock()

        board = AsyncMock()

        phase = PipelinePhase(id="p1", name="Planning", goal="Plan it", order=0)
        pipeline = Pipeline(
            phases=[phase],
            orchestrator=orch,
            task_board=board,
        )

        result = await pipeline.run("Build something")
        assert len(result.phases) == 1
        assert result.phases[0].status == PhaseStatus.COMPLETED
        assert result.status == "completed"

    async def test_failed_phase_skips_remaining_phases(self) -> None:
        """When phase fails due to None result, remaining phases are SKIPPED."""
        orch = AsyncMock()
        orch.start = AsyncMock(return_value="run-1")
        orch.wait_for_task = AsyncMock(return_value=None)
        orch.stop = AsyncMock()

        board = AsyncMock()

        phases = [
            PipelinePhase(id="p1", name="Plan", goal="Plan it", order=0),
            PipelinePhase(id="p2", name="Execute", goal="Do it", order=1),
        ]
        pipeline = Pipeline(
            phases=phases,
            orchestrator=orch,
            task_board=board,
        )

        result = await pipeline.run("Build")
        assert len(result.phases) == 2
        assert result.phases[0].status == PhaseStatus.FAILED
        assert result.phases[1].status == PhaseStatus.SKIPPED
