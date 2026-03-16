"""TDD RED: CodeWorkflowEngine delegates to GenericWorkflowEngine.

W1 fix: CodeWorkflowEngine must be a thin wrapper over GenericWorkflowEngine,
not a standalone implementation with its own plan/execute/verify logic.
"""

from __future__ import annotations

import pytest
from _stubs import StubPlannerMode as PlannerMode
from cognitia.orchestration.code_workflow_engine import (
    CodeWorkflowEngine,
    WorkflowStatus,
)
from cognitia.orchestration.dod_state_machine import DoDStateMachine
from cognitia.orchestration.generic_workflow_engine import GenericWorkflowEngine
from cognitia.orchestration.verification_types import (
    VerificationResult,
    VerificationStatus,
)


class _PassVerifier:
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


class TestCodeWorkflowDelegatesToGeneric:
    """CodeWorkflowEngine must hold a GenericWorkflowEngine internally."""

    def test_code_workflow_has_generic_engine_attribute(self) -> None:
        engine = CodeWorkflowEngine(
            verifier=_PassVerifier(),
            dod=DoDStateMachine(max_loops=3),
            planner=PlannerMode(),
        )
        assert hasattr(engine, "_generic"), (
            "CodeWorkflowEngine must hold _generic: GenericWorkflowEngine"
        )
        assert isinstance(engine._generic, GenericWorkflowEngine)

    @pytest.mark.asyncio
    async def test_delegation_produces_same_success_result(self) -> None:
        engine = CodeWorkflowEngine(
            verifier=_PassVerifier(),
            dod=DoDStateMachine(max_loops=3),
            planner=PlannerMode(),
        )
        result = await engine.run("Build feature", dod_criteria=("linters",))
        assert result.status == WorkflowStatus.SUCCESS
        assert "Plan for: Build feature" in result.output
        assert result.loop_count == 1

    @pytest.mark.asyncio
    async def test_delegation_no_criteria_skips_verification(self) -> None:
        engine = CodeWorkflowEngine(
            verifier=_PassVerifier(),
            dod=DoDStateMachine(max_loops=3),
            planner=PlannerMode(),
        )
        result = await engine.run("Quick task")
        assert result.status == WorkflowStatus.SUCCESS
        assert result.dod_log == ""
        assert result.loop_count == 0
