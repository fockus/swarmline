"""Integration: GenericWorkflowEngine - execute/verify retry loop. Real executor + real verifier (not mock).
1st attempt: executor returns incomplete -> verifier fail -> retry.
2nd attempt: executor returns complete -> verifier pass.
Check: status=success, loop_count=2, verification_log.
"""

from __future__ import annotations

from typing import Any

import pytest

from swarmline.orchestration.generic_workflow_engine import (
    GenericWorkflowEngine,
    GenericWorkflowStatus,
)

pytestmark = pytest.mark.integration


class TestGenericWorkflowExecuteVerifyLoop:
    """GenericWorkflowEngine with real executor and real verifier."""

    @pytest.mark.asyncio
    async def test_generic_workflow_execute_verify_loop(self) -> None:
        """1st attempt fail, 2nd attempt pass -> status=success, loop_count=2."""
        attempt_counter = 0

        async def real_executor(task: str, context: dict[str, Any]) -> str:
            """Executor: pervyy raz incomplete, vtoroy - complete."""
            nonlocal attempt_counter
            attempt_counter += 1
            if attempt_counter == 1:
                return "partial result: data gathered but no summary yet"
            return "Complete analysis. SUMMARY: market is bullish, growth 15% YoY"

        async def real_verifier(
            output: str, context: dict[str, Any]
        ) -> tuple[bool, str]:
            """Verifier: verifies nalichie markera 'SUMMARY:' in output."""
            if "SUMMARY:" in output:
                return True, "Verification passed: summary section present"
            return False, "Verification failed: missing SUMMARY section"

        engine = GenericWorkflowEngine(
            executor=real_executor,
            verifier=real_verifier,
            max_retries=3,
        )

        result = await engine.run("Analyze market trends")

        assert result.status == GenericWorkflowStatus.SUCCESS
        assert result.loop_count == 2
        assert "summary" in result.output.lower()
        assert "Verification passed" in result.verification_log
        assert "Verification failed" in result.verification_log

    @pytest.mark.asyncio
    async def test_generic_workflow_max_retries_exceeded(self) -> None:
        """Vse popytki fail -> status=max_retries_exceeded."""

        async def failing_executor(task: str, context: dict[str, Any]) -> str:
            return "always incomplete"

        async def strict_verifier(
            output: str, context: dict[str, Any]
        ) -> tuple[bool, str]:
            return False, "Missing required sections"

        engine = GenericWorkflowEngine(
            executor=failing_executor,
            verifier=strict_verifier,
            max_retries=2,
        )

        result = await engine.run("Write report")

        assert result.status == GenericWorkflowStatus.MAX_RETRIES_EXCEEDED
        assert result.loop_count == 2
        assert "Missing required sections" in result.verification_log
        # Verification log contains zapisi obeih popytok
        assert result.verification_log.count("Attempt") == 2

    @pytest.mark.asyncio
    async def test_generic_workflow_pass_on_first_try(self) -> None:
        """Pervaya popytka srazu prohodit -> loop_count=1."""

        async def good_executor(task: str, context: dict[str, Any]) -> str:
            return "Perfect output with all required data"

        async def lenient_verifier(
            output: str, context: dict[str, Any]
        ) -> tuple[bool, str]:
            return True, "All checks passed"

        engine = GenericWorkflowEngine(
            executor=good_executor,
            verifier=lenient_verifier,
            max_retries=5,
        )

        result = await engine.run("Simple task")

        assert result.status == GenericWorkflowStatus.SUCCESS
        assert result.loop_count == 1
        assert "All checks passed" in result.verification_log
