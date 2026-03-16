"""Integration: CodeWorkflowEngine + DoDStateMachine + CodeVerifier.

Реальный DoDStateMachine, CodeVerifier как simple implementation (не mock).
CodeVerifier возвращает pass на все criteria.
Проверить: полный pipeline plan -> execute -> verify, result.status = success.
"""

from __future__ import annotations

import pytest

from _stubs import StubPlannerMode as PlannerMode
from cognitia.orchestration.code_workflow_engine import (
    CodeWorkflowEngine,
    WorkflowResult,
    WorkflowStatus,
)
from cognitia.orchestration.dod_state_machine import DoDStateMachine
from cognitia.orchestration.verification_types import (
    CheckDetail,
    VerificationResult,
    VerificationStatus,
)


class PassingCodeVerifier:
    """Реальная (не mock) реализация CodeVerifier — все проверки проходят."""

    async def verify_contracts(self) -> VerificationResult:
        return VerificationResult(
            status=VerificationStatus.PASS,
            checks=(
                CheckDetail(name="contracts", status=VerificationStatus.PASS, message="OK"),
            ),
            summary="All contracts verified",
        )

    async def verify_tests_substantive(self) -> VerificationResult:
        return VerificationResult(
            status=VerificationStatus.PASS,
            checks=(
                CheckDetail(name="tests", status=VerificationStatus.PASS, message="OK"),
            ),
            summary="Tests are substantive",
        )

    async def verify_tests_before_code(self) -> VerificationResult:
        return VerificationResult(
            status=VerificationStatus.PASS,
            checks=(
                CheckDetail(name="tdd", status=VerificationStatus.PASS, message="OK"),
            ),
            summary="TDD order verified",
        )

    async def verify_linters(self) -> VerificationResult:
        return VerificationResult(
            status=VerificationStatus.PASS,
            checks=(
                CheckDetail(name="linters", status=VerificationStatus.PASS, message="OK"),
            ),
            summary="All linters pass",
        )

    async def verify_coverage(self, min_pct: int = 85) -> VerificationResult:
        return VerificationResult(
            status=VerificationStatus.PASS,
            checks=(
                CheckDetail(
                    name="coverage",
                    status=VerificationStatus.PASS,
                    message=f"Coverage 95% >= {min_pct}%",
                ),
            ),
            summary=f"Coverage exceeds {min_pct}%",
        )


class FailThenPassVerifier:
    """CodeVerifier: первый вызов fail, далее pass. Для теста DoD retry."""

    def __init__(self) -> None:
        self._call_count = 0

    async def verify_contracts(self) -> VerificationResult:
        self._call_count += 1
        if self._call_count <= 1:
            return VerificationResult(
                status=VerificationStatus.FAIL,
                checks=(
                    CheckDetail(
                        name="contracts",
                        status=VerificationStatus.FAIL,
                        message="Missing contract test",
                    ),
                ),
            )
        return VerificationResult(
            status=VerificationStatus.PASS,
            checks=(
                CheckDetail(name="contracts", status=VerificationStatus.PASS, message="OK"),
            ),
        )

    async def verify_tests_substantive(self) -> VerificationResult:
        return VerificationResult(status=VerificationStatus.PASS)

    async def verify_tests_before_code(self) -> VerificationResult:
        return VerificationResult(status=VerificationStatus.PASS)

    async def verify_linters(self) -> VerificationResult:
        return VerificationResult(status=VerificationStatus.PASS)

    async def verify_coverage(self, min_pct: int = 85) -> VerificationResult:
        return VerificationResult(status=VerificationStatus.PASS)


class TestCodeWorkflowDoDVerification:
    """CodeWorkflowEngine + DoDStateMachine + real CodeVerifier."""

    @pytest.mark.asyncio
    async def test_code_workflow_dod_verification_all_pass(self) -> None:
        """Полный pipeline plan -> execute -> verify. Все criteria pass."""
        verifier = PassingCodeVerifier()
        dod = DoDStateMachine(max_loops=3)
        planner = PlannerMode()

        engine = CodeWorkflowEngine(
            verifier=verifier,
            dod=dod,
            planner=planner,
        )

        result = await engine.run(
            goal="Implement user registration",
            dod_criteria=("contracts", "tests", "linters", "coverage"),
        )

        assert result.status == WorkflowStatus.SUCCESS
        assert "pass" in result.dod_log.lower()

    @pytest.mark.asyncio
    async def test_code_workflow_no_criteria_succeeds(self) -> None:
        """Без DoD criteria -> success (verification skipped)."""
        verifier = PassingCodeVerifier()
        dod = DoDStateMachine(max_loops=3)
        planner = PlannerMode()

        engine = CodeWorkflowEngine(
            verifier=verifier,
            dod=dod,
            planner=planner,
        )

        result = await engine.run(goal="Quick fix", dod_criteria=())

        assert result.status == WorkflowStatus.SUCCESS
        assert result.dod_log == ""

    @pytest.mark.asyncio
    async def test_code_workflow_dod_retry_then_pass(self) -> None:
        """DoDStateMachine retry: первый loop fail, второй pass."""
        verifier = FailThenPassVerifier()
        dod = DoDStateMachine(max_loops=3)
        planner = PlannerMode()

        engine = CodeWorkflowEngine(
            verifier=verifier,
            dod=dod,
            planner=planner,
        )

        result = await engine.run(
            goal="Add feature X",
            dod_criteria=("contracts",),
        )

        assert result.status == WorkflowStatus.SUCCESS
        assert result.loop_count == 2
        # Log содержит оба loop
        assert "Loop 1" in result.dod_log
        assert "Loop 2" in result.dod_log
