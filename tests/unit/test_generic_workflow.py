"""TDD RED: GenericWorkflowEngine — pluggable VerifierPort + ExecutorPort.

CRP-5.2: Обобщение CodeWorkflowEngine для произвольных verifiers.
"""

from __future__ import annotations

from typing import Any


class TestGenericWorkflowPassFirstTry:
    """execute → verify pass → done."""

    async def test_generic_workflow_pass_first_try(self) -> None:
        from cognitia.orchestration.generic_workflow_engine import (
            GenericWorkflowEngine,
            GenericWorkflowResult,
            GenericWorkflowStatus,
        )

        async def executor(task: str, context: dict[str, Any]) -> str:
            return "execution output"

        async def verifier(output: str, context: dict[str, Any]) -> tuple[bool, str]:
            return True, "All checks passed"

        engine = GenericWorkflowEngine(executor=executor, verifier=verifier, max_retries=3)
        result = await engine.run("do something", context={})

        assert isinstance(result, GenericWorkflowResult)
        assert result.status == GenericWorkflowStatus.SUCCESS
        assert result.output == "execution output"
        assert result.loop_count == 1


class TestGenericWorkflowRetryOnFail:
    """execute → verify fail → retry → pass."""

    async def test_generic_workflow_retry_on_fail(self) -> None:
        from cognitia.orchestration.generic_workflow_engine import (
            GenericWorkflowEngine,
            GenericWorkflowStatus,
        )

        call_count = 0

        async def executor(task: str, context: dict[str, Any]) -> str:
            nonlocal call_count
            call_count += 1
            return f"attempt {call_count}"

        async def verifier(output: str, context: dict[str, Any]) -> tuple[bool, str]:
            if "attempt 2" in output:
                return True, "Passed on retry"
            return False, "Quality check failed"

        engine = GenericWorkflowEngine(executor=executor, verifier=verifier, max_retries=5)
        result = await engine.run("task", context={})

        assert result.status == GenericWorkflowStatus.SUCCESS
        assert result.loop_count == 2
        assert call_count == 2


class TestGenericWorkflowMaxRetriesExceeded:
    """3 fails → max_retries_exceeded status."""

    async def test_generic_workflow_max_retries_exceeded(self) -> None:
        from cognitia.orchestration.generic_workflow_engine import (
            GenericWorkflowEngine,
            GenericWorkflowStatus,
        )

        async def executor(task: str, context: dict[str, Any]) -> str:
            return "always bad"

        async def verifier(output: str, context: dict[str, Any]) -> tuple[bool, str]:
            return False, "Still failing"

        engine = GenericWorkflowEngine(executor=executor, verifier=verifier, max_retries=3)
        result = await engine.run("task", context={})

        assert result.status == GenericWorkflowStatus.MAX_RETRIES_EXCEEDED
        assert result.loop_count == 3


class TestGenericWorkflowCustomVerifier:
    """Pluggable verifier (content quality check)."""

    async def test_generic_workflow_custom_verifier(self) -> None:
        from cognitia.orchestration.generic_workflow_engine import (
            GenericWorkflowEngine,
            GenericWorkflowStatus,
        )

        async def content_executor(task: str, context: dict[str, Any]) -> str:
            return "This is a well-written article about Python."

        async def quality_verifier(output: str, context: dict[str, Any]) -> tuple[bool, str]:
            checks = []
            if len(output) > 10:
                checks.append("length OK")
            else:
                return False, "Too short"
            if "python" in output.lower():
                checks.append("topic OK")
            else:
                return False, "Off-topic"
            return True, "; ".join(checks)

        engine = GenericWorkflowEngine(
            executor=content_executor, verifier=quality_verifier, max_retries=1
        )
        result = await engine.run("Write about Python", context={})

        assert result.status == GenericWorkflowStatus.SUCCESS
        assert "OK" in result.verification_log


class TestGenericWorkflowCodeVerifierBackwardCompat:
    """CodeWorkflowEngine works as before (backward compat)."""

    async def test_generic_workflow_code_verifier_backward_compat(self) -> None:
        from _stubs import StubPlannerMode as PlannerMode
        from cognitia.orchestration.code_workflow_engine import (
            CodeWorkflowEngine,
            WorkflowStatus,
        )
        from cognitia.orchestration.dod_state_machine import DoDStateMachine

        # Minimal mock verifier
        class MockVerifier:
            async def verify_contracts(self):
                from cognitia.orchestration.verification_types import (
                    VerificationResult,
                    VerificationStatus,
                )

                return VerificationResult(status=VerificationStatus.PASS, checks=(), summary="ok")

            async def verify_tests_substantive(self):
                from cognitia.orchestration.verification_types import (
                    VerificationResult,
                    VerificationStatus,
                )

                return VerificationResult(status=VerificationStatus.PASS, checks=(), summary="ok")

            async def verify_tests_before_code(self):
                from cognitia.orchestration.verification_types import (
                    VerificationResult,
                    VerificationStatus,
                )

                return VerificationResult(status=VerificationStatus.PASS, checks=(), summary="ok")

            async def verify_linters(self):
                from cognitia.orchestration.verification_types import (
                    VerificationResult,
                    VerificationStatus,
                )

                return VerificationResult(status=VerificationStatus.PASS, checks=(), summary="ok")

            async def verify_coverage(self, min_pct=85):
                from cognitia.orchestration.verification_types import (
                    VerificationResult,
                    VerificationStatus,
                )

                return VerificationResult(status=VerificationStatus.PASS, checks=(), summary="ok")

        verifier = MockVerifier()
        dod = DoDStateMachine(max_loops=3)
        planner = PlannerMode()

        engine = CodeWorkflowEngine(verifier=verifier, dod=dod, planner=planner)
        result = await engine.run("build feature X")

        assert result.status == WorkflowStatus.SUCCESS
        assert result.output != ""


class TestGenericWorkflowWithWorkflowGraphNode:
    """GenericWorkflowEngine as node in WorkflowGraph."""

    async def test_generic_workflow_with_workflow_graph_node(self) -> None:
        from cognitia.orchestration.generic_workflow_engine import GenericWorkflowEngine
        from cognitia.orchestration.workflow_graph import WorkflowGraph

        async def executor(task: str, context: dict[str, Any]) -> str:
            return f"executed: {task}"

        async def verifier(output: str, context: dict[str, Any]) -> tuple[bool, str]:
            return True, "OK"

        engine = GenericWorkflowEngine(executor=executor, verifier=verifier, max_retries=2)

        async def engine_node(state: dict[str, Any]) -> dict[str, Any]:
            result = await engine.run(state.get("task", "default"), context=state)
            state["engine_result"] = result.output
            state["engine_status"] = result.status.value
            return state

        wf = WorkflowGraph("engine-in-graph")
        wf.add_node("run_engine", engine_node)
        wf.set_entry("run_engine")

        result = await wf.execute({"task": "build feature"})
        assert result["engine_status"] == "success"
        assert "executed" in result["engine_result"]
