"""E2E: GenericWorkflowEngine + CodeWorkflowEngine.

Pluggable execute/verify loop с real components.
Fake executor/verifier через simple async callables и classes (DI).
"""

from __future__ import annotations

from typing import Any

import pytest

from cognitia.orchestration.code_verifier import CodeVerifier
from cognitia.orchestration.code_workflow_engine import (
    CodeWorkflowEngine,
    WorkflowResult,
    WorkflowStatus,
)
from cognitia.orchestration.dod_state_machine import DoDResult, DoDStateMachine, DoDStatus
from cognitia.orchestration.generic_workflow_engine import (
    GenericWorkflowEngine,
    GenericWorkflowResult,
    GenericWorkflowStatus,
)
from cognitia.orchestration.verification_types import (
    CheckDetail,
    VerificationResult,
    VerificationStatus,
)


# ---------------------------------------------------------------------------
# 1. GenericWorkflowEngine — full cycle
# ---------------------------------------------------------------------------


class TestGenericWorkflowE2E:
    """GenericWorkflowEngine: executor -> verifier -> retry -> pass."""

    @pytest.mark.asyncio
    async def test_generic_workflow_full_cycle_pass_on_third(self) -> None:
        """Executor вызывается 3 раза, verifier пропускает на 3-й попытке.

        Проверяем: status, output, verification_log, loop_count.
        """
        attempt = 0

        async def executor(task: str, ctx: dict[str, Any]) -> str:
            nonlocal attempt
            attempt += 1
            return f"output_v{attempt}"

        async def verifier(output: str, ctx: dict[str, Any]) -> tuple[bool, str]:
            # Пропускаем только третью попытку
            if "v3" in output:
                return True, "All checks passed"
            return False, f"Failed: {output} not good enough"

        engine = GenericWorkflowEngine(
            executor=executor,
            verifier=verifier,
            max_retries=5,
        )

        result = await engine.run("Build feature X")

        assert result.status == GenericWorkflowStatus.SUCCESS
        assert result.output == "output_v3"
        assert result.loop_count == 3
        assert "Attempt 1" in result.verification_log
        assert "Attempt 2" in result.verification_log
        assert "Attempt 3" in result.verification_log
        assert "All checks passed" in result.verification_log

    @pytest.mark.asyncio
    async def test_generic_workflow_max_retries_exceeded(self) -> None:
        """Все попытки fail -> MAX_RETRIES_EXCEEDED."""
        async def executor(task: str, ctx: dict[str, Any]) -> str:
            return "always_failing_output"

        async def verifier(output: str, ctx: dict[str, Any]) -> tuple[bool, str]:
            return False, "Still broken"

        engine = GenericWorkflowEngine(
            executor=executor,
            verifier=verifier,
            max_retries=3,
        )

        result = await engine.run("Impossible task")

        assert result.status == GenericWorkflowStatus.MAX_RETRIES_EXCEEDED
        assert result.loop_count == 3
        assert result.output == "always_failing_output"
        assert "Still broken" in result.verification_log

    @pytest.mark.asyncio
    async def test_generic_workflow_pass_first_try(self) -> None:
        """Verifier пропускает с первой попытки."""
        async def executor(task: str, ctx: dict[str, Any]) -> str:
            return "perfect_output"

        async def verifier(output: str, ctx: dict[str, Any]) -> tuple[bool, str]:
            return True, "Perfect"

        engine = GenericWorkflowEngine(
            executor=executor,
            verifier=verifier,
            max_retries=3,
        )

        result = await engine.run("Easy task")

        assert result.status == GenericWorkflowStatus.SUCCESS
        assert result.loop_count == 1
        assert result.output == "perfect_output"

    @pytest.mark.asyncio
    async def test_generic_workflow_with_port_objects(self) -> None:
        """Executor и Verifier как объекты с execute()/verify() методами."""

        class FakeExecutor:
            def __init__(self) -> None:
                self.call_count = 0

            async def execute(self, goal: str) -> str:
                self.call_count += 1
                return f"executed_{self.call_count}"

        class FakeVerifier:
            async def verify(self, output: str) -> tuple[bool, str]:
                if "2" in output:
                    return True, "Passed on second try"
                return False, "Not yet"

        exec_obj = FakeExecutor()
        verify_obj = FakeVerifier()

        engine = GenericWorkflowEngine(
            executor=exec_obj,
            verifier=verify_obj,
            max_retries=5,
        )

        result = await engine.run("Test goal")

        assert result.status == GenericWorkflowStatus.SUCCESS
        assert result.loop_count == 2
        assert exec_obj.call_count == 2

    @pytest.mark.asyncio
    async def test_generic_workflow_context_passed_to_callables(self) -> None:
        """Context dict передаётся в executor и verifier."""
        received_contexts: list[dict[str, Any]] = []

        async def executor(task: str, ctx: dict[str, Any]) -> str:
            received_contexts.append({"type": "executor", **ctx})
            return "output"

        async def verifier(output: str, ctx: dict[str, Any]) -> tuple[bool, str]:
            received_contexts.append({"type": "verifier", **ctx})
            return True, "ok"

        engine = GenericWorkflowEngine(executor=executor, verifier=verifier)

        await engine.run("task", context={"project": "cognitia", "env": "test"})

        assert len(received_contexts) == 2
        assert received_contexts[0]["project"] == "cognitia"
        assert received_contexts[1]["env"] == "test"


# ---------------------------------------------------------------------------
# 2. CodeWorkflowEngine — delegates to GenericWorkflowEngine
# ---------------------------------------------------------------------------


class TestCodeWorkflowE2E:
    """CodeWorkflowEngine: plan -> execute -> DoD verify."""

    @pytest.mark.asyncio
    async def test_code_workflow_delegates_to_generic(self) -> None:
        """CodeWorkflowEngine использует GenericWorkflowEngine внутри.

        Проверяем: result correct, uses planner + DoD verifier.
        """

        class FakePlanner:
            """Fake CodePlannerPort: create_plan -> execute_plan."""

            def __init__(self) -> None:
                self.plan_created = False
                self.plan_executed = False

            async def create_plan(self, goal: str) -> str:
                self.plan_created = True
                return f"Plan for: {goal}"

            async def execute_plan(self, plan: str) -> str:
                self.plan_executed = True
                return f"Executed: {plan}"

        class FakeCodeVerifier:
            """Fake CodeVerifier: все проверки проходят."""

            async def verify_contracts(self) -> VerificationResult:
                return VerificationResult(
                    status=VerificationStatus.PASS,
                    checks=(CheckDetail(name="contracts", status=VerificationStatus.PASS),),
                )

            async def verify_tests_substantive(self) -> VerificationResult:
                return VerificationResult(
                    status=VerificationStatus.PASS,
                    checks=(CheckDetail(name="tests", status=VerificationStatus.PASS),),
                )

            async def verify_tests_before_code(self) -> VerificationResult:
                return VerificationResult(
                    status=VerificationStatus.PASS,
                    checks=(CheckDetail(name="tdd", status=VerificationStatus.PASS),),
                )

            async def verify_linters(self) -> VerificationResult:
                return VerificationResult(
                    status=VerificationStatus.PASS,
                    checks=(CheckDetail(name="linters", status=VerificationStatus.PASS),),
                )

            async def verify_coverage(self, min_pct: int = 85) -> VerificationResult:
                return VerificationResult(
                    status=VerificationStatus.PASS,
                    checks=(CheckDetail(name="coverage", status=VerificationStatus.PASS),),
                )

        planner = FakePlanner()
        verifier = FakeCodeVerifier()
        dod = DoDStateMachine(max_loops=3)

        engine = CodeWorkflowEngine(
            verifier=verifier,
            dod=dod,
            planner=planner,
        )

        result = await engine.run(
            goal="Implement feature X",
            dod_criteria=("contracts", "tests", "linters"),
        )

        assert result.status == WorkflowStatus.SUCCESS
        assert planner.plan_created, "Planner.create_plan должен быть вызван"
        assert planner.plan_executed, "Planner.execute_plan должен быть вызван"
        assert "Executed" in result.output

    @pytest.mark.asyncio
    async def test_code_workflow_no_dod_criteria(self) -> None:
        """Без DoD criteria -> SUCCESS без верификации."""

        class FakePlanner:
            async def create_plan(self, goal: str) -> str:
                return "plan"

            async def execute_plan(self, plan: str) -> str:
                return "output without verification"

        class FakeCodeVerifier:
            async def verify_contracts(self) -> VerificationResult:
                return VerificationResult(status=VerificationStatus.FAIL)

            async def verify_tests_substantive(self) -> VerificationResult:
                return VerificationResult(status=VerificationStatus.FAIL)

            async def verify_tests_before_code(self) -> VerificationResult:
                return VerificationResult(status=VerificationStatus.FAIL)

            async def verify_linters(self) -> VerificationResult:
                return VerificationResult(status=VerificationStatus.FAIL)

            async def verify_coverage(self, min_pct: int = 85) -> VerificationResult:
                return VerificationResult(status=VerificationStatus.FAIL)

        engine = CodeWorkflowEngine(
            verifier=FakeCodeVerifier(),
            dod=DoDStateMachine(),
            planner=FakePlanner(),
        )

        # Без criteria — верификация пропускается
        result = await engine.run(goal="Quick fix", dod_criteria=())

        assert result.status == WorkflowStatus.SUCCESS
        assert result.output == "output without verification"

    @pytest.mark.asyncio
    async def test_code_workflow_dod_not_met(self) -> None:
        """DoD criteria не проходят -> DOD_NOT_MET."""

        class FakePlanner:
            async def create_plan(self, goal: str) -> str:
                return "plan"

            async def execute_plan(self, plan: str) -> str:
                return "buggy output"

        class FailingVerifier:
            """Все проверки проваливаются."""

            async def verify_contracts(self) -> VerificationResult:
                return VerificationResult(
                    status=VerificationStatus.FAIL,
                    checks=(
                        CheckDetail(
                            name="contracts",
                            status=VerificationStatus.FAIL,
                            message="No contracts found",
                        ),
                    ),
                )

            async def verify_tests_substantive(self) -> VerificationResult:
                return VerificationResult(status=VerificationStatus.FAIL)

            async def verify_tests_before_code(self) -> VerificationResult:
                return VerificationResult(status=VerificationStatus.FAIL)

            async def verify_linters(self) -> VerificationResult:
                return VerificationResult(
                    status=VerificationStatus.FAIL,
                    checks=(
                        CheckDetail(
                            name="linters",
                            status=VerificationStatus.FAIL,
                            message="ruff found errors",
                        ),
                    ),
                )

            async def verify_coverage(self, min_pct: int = 85) -> VerificationResult:
                return VerificationResult(status=VerificationStatus.FAIL)

        engine = CodeWorkflowEngine(
            verifier=FailingVerifier(),
            dod=DoDStateMachine(max_loops=2),
            planner=FakePlanner(),
        )

        result = await engine.run(
            goal="Implement broken feature",
            dod_criteria=("contracts", "linters"),
        )

        assert result.status == WorkflowStatus.DOD_NOT_MET
        assert result.loop_count >= 1
        assert result.dod_log, "DoD log не должен быть пустым"
