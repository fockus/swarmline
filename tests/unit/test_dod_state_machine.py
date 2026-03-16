"""Tests for DoDStateMachine, CodeWorkflowEngine, and WorkflowPipeline protocol."""

from __future__ import annotations

import pytest
from _stubs import StubPlannerMode as PlannerMode
from cognitia.orchestration.code_workflow_engine import (
    CodeWorkflowEngine,
    WorkflowStatus,
)
from cognitia.orchestration.dod_state_machine import DoDStateMachine, DoDStatus
from cognitia.orchestration.verification_types import (
    VerificationResult,
    VerificationStatus,
)
from cognitia.orchestration.workflow_pipeline import WorkflowPipeline


class AlwaysPassVerifier:
    """Verifier that always passes all checks."""

    async def verify_contracts(self) -> VerificationResult:
        return VerificationResult(status=VerificationStatus.PASS)

    async def verify_tests_substantive(self) -> VerificationResult:
        return VerificationResult(status=VerificationStatus.PASS)

    async def verify_tests_before_code(self) -> VerificationResult:
        return VerificationResult(status=VerificationStatus.PASS)

    async def verify_linters(self) -> VerificationResult:
        return VerificationResult(status=VerificationStatus.PASS)

    async def verify_coverage(self, min_pct: int = 85) -> VerificationResult:
        return VerificationResult(status=VerificationStatus.PASS)


class FailThenPassVerifier:
    """Verifier that fails N times then passes."""

    def __init__(self, fail_count: int = 1) -> None:
        self._fail_count = fail_count
        self._call_count = 0

    async def verify_contracts(self) -> VerificationResult:
        return VerificationResult(status=VerificationStatus.PASS)

    async def verify_tests_substantive(self) -> VerificationResult:
        return VerificationResult(status=VerificationStatus.PASS)

    async def verify_tests_before_code(self) -> VerificationResult:
        return VerificationResult(status=VerificationStatus.PASS)

    async def verify_linters(self) -> VerificationResult:
        self._call_count += 1
        if self._call_count <= self._fail_count:
            return VerificationResult(
                status=VerificationStatus.FAIL, summary="lint error"
            )
        return VerificationResult(status=VerificationStatus.PASS)

    async def verify_coverage(self, min_pct: int = 85) -> VerificationResult:
        return VerificationResult(status=VerificationStatus.PASS)


class AlwaysFailVerifier:
    """Verifier that always fails linters."""

    async def verify_contracts(self) -> VerificationResult:
        return VerificationResult(status=VerificationStatus.PASS)

    async def verify_tests_substantive(self) -> VerificationResult:
        return VerificationResult(status=VerificationStatus.PASS)

    async def verify_tests_before_code(self) -> VerificationResult:
        return VerificationResult(status=VerificationStatus.PASS)

    async def verify_linters(self) -> VerificationResult:
        return VerificationResult(
            status=VerificationStatus.FAIL, summary="always fails"
        )

    async def verify_coverage(self, min_pct: int = 85) -> VerificationResult:
        return VerificationResult(status=VerificationStatus.PASS)


class TestDoDStateMachine:
    @pytest.mark.asyncio
    async def test_dod_pass_first_try(self) -> None:
        dod = DoDStateMachine(max_loops=3)
        verifier = AlwaysPassVerifier()
        result = await dod.verify_dod(("linters", "coverage"), verifier)
        assert result.status == DoDStatus.PASSED
        assert result.loop_count == 1
        assert "Loop 1" in result.verification_log

    @pytest.mark.asyncio
    async def test_dod_fail_then_retry_pass(self) -> None:
        dod = DoDStateMachine(max_loops=3)
        verifier = FailThenPassVerifier(fail_count=1)
        result = await dod.verify_dod(("linters",), verifier)
        assert result.status == DoDStatus.PASSED
        assert result.loop_count == 2
        assert "Loop 1" in result.verification_log
        assert "Loop 2" in result.verification_log

    @pytest.mark.asyncio
    async def test_dod_max_loops_exceeded(self) -> None:
        dod = DoDStateMachine(max_loops=2)
        verifier = AlwaysFailVerifier()
        result = await dod.verify_dod(("linters",), verifier)
        assert result.status == DoDStatus.MAX_LOOPS_EXCEEDED
        assert result.loop_count == 2

    @pytest.mark.asyncio
    async def test_dod_empty_criteria_passes_immediately(self) -> None:
        dod = DoDStateMachine(max_loops=3)
        verifier = AlwaysPassVerifier()
        result = await dod.verify_dod((), verifier)
        assert result.status == DoDStatus.PASSED
        assert result.loop_count == 0

    @pytest.mark.asyncio
    async def test_dod_unknown_criterion_does_not_pass(self) -> None:
        dod = DoDStateMachine(max_loops=1)
        verifier = AlwaysPassVerifier()

        result = await dod.verify_dod(("coverage 95%",), verifier)

        assert result.status == DoDStatus.MAX_LOOPS_EXCEEDED
        assert result.loop_count == 1
        assert "coverage 95%: skip" in result.verification_log


class TestCodeWorkflowEngine:
    @pytest.mark.asyncio
    async def test_workflow_engine_full_run(self) -> None:
        verifier = AlwaysPassVerifier()
        dod = DoDStateMachine(max_loops=3)
        planner = PlannerMode()
        engine = CodeWorkflowEngine(verifier=verifier, dod=dod, planner=planner)

        result = await engine.run("Fix bug", dod_criteria=("linters", "coverage"))
        assert result.status == WorkflowStatus.SUCCESS
        assert result.loop_count == 1
        assert "Plan for: Fix bug" in result.output

    @pytest.mark.asyncio
    async def test_workflow_engine_no_criteria(self) -> None:
        verifier = AlwaysPassVerifier()
        dod = DoDStateMachine(max_loops=3)
        planner = PlannerMode()
        engine = CodeWorkflowEngine(verifier=verifier, dod=dod, planner=planner)

        result = await engine.run("Quick fix")
        assert result.status == WorkflowStatus.SUCCESS
        assert result.dod_log == ""
        assert result.loop_count == 0

    @pytest.mark.asyncio
    async def test_workflow_engine_dod_not_met(self) -> None:
        verifier = AlwaysFailVerifier()
        dod = DoDStateMachine(max_loops=2)
        planner = PlannerMode()
        engine = CodeWorkflowEngine(verifier=verifier, dod=dod, planner=planner)

        result = await engine.run("Feature", dod_criteria=("linters",))
        assert result.status == WorkflowStatus.DOD_NOT_MET
        assert result.loop_count == 2

    @pytest.mark.asyncio
    async def test_workflow_engine_unknown_criterion_returns_dod_not_met(self) -> None:
        verifier = AlwaysPassVerifier()
        dod = DoDStateMachine(max_loops=1)
        planner = PlannerMode()
        engine = CodeWorkflowEngine(verifier=verifier, dod=dod, planner=planner)

        result = await engine.run("Feature", dod_criteria=("coverage 95%",))

        assert result.status == WorkflowStatus.DOD_NOT_MET
        assert result.loop_count == 1


class TestWorkflowPipelineProtocol:
    def test_workflow_pipeline_protocol(self) -> None:
        """WorkflowPipeline is a Protocol with 5 methods."""
        assert hasattr(WorkflowPipeline, "research")
        assert hasattr(WorkflowPipeline, "plan")
        assert hasattr(WorkflowPipeline, "execute")
        assert hasattr(WorkflowPipeline, "review")
        assert hasattr(WorkflowPipeline, "verify")
