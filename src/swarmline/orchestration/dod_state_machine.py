"""DoDStateMachine - criteria-driven verification with max loop counter.

State machine: PENDING -> VERIFYING -> PASSED / FAILED / MAX_LOOPS_EXCEEDED.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from swarmline.orchestration.code_verifier import CodeVerifier
from swarmline.orchestration.verification_types import VerificationStatus


class DoDStatus(str, Enum):
    PENDING = "pending"
    VERIFYING = "verifying"
    PASSED = "passed"
    FAILED = "failed"
    MAX_LOOPS_EXCEEDED = "max_loops_exceeded"


@dataclass(frozen=True, slots=True)
class DoDResult:
    """Result of DoD verification cycle."""

    status: DoDStatus
    loop_count: int
    verification_log: str = ""


class DoDStateMachine:
    """Criteria-driven verification state machine.

  Runs verification checks in a loop up to max_loops times.
  If all checks pass -> PASSED. If max_loops exceeded -> MAX_LOOPS_EXCEEDED.
  """

    def __init__(self, max_loops: int = 3) -> None:
        if max_loops < 1:
            raise ValueError("max_loops must be >= 1")
        self._max_loops = max_loops

    async def verify_dod(
        self, criteria: tuple[str, ...], verifier: CodeVerifier
    ) -> DoDResult:
        """Run verification loop until all criteria pass or max loops exceeded."""
        if not criteria:
            return DoDResult(
                status=DoDStatus.PASSED, loop_count=0, verification_log="No criteria"
            )

        log_lines: list[str] = []

        for loop in range(1, self._max_loops + 1):
            log_lines.append(f"--- Loop {loop}/{self._max_loops} ---")
            all_passed = True

            for criterion in criteria:
                result = await self._run_criterion(criterion, verifier)
                log_lines.append(f"  {criterion}: {result.status.value}")
                if not result.passed:
                    all_passed = False

            if all_passed:
                return DoDResult(
                    status=DoDStatus.PASSED,
                    loop_count=loop,
                    verification_log="\n".join(log_lines),
                )

        return DoDResult(
            status=DoDStatus.MAX_LOOPS_EXCEEDED,
            loop_count=self._max_loops,
            verification_log="\n".join(log_lines),
        )

    async def _run_criterion(
        self, criterion: str, verifier: CodeVerifier
    ) -> _CriterionResult:
        """Map criterion name to verifier method and run it."""
        from swarmline.orchestration.verification_types import VerificationResult

        method_map: dict[str, str] = {
            "contracts": "verify_contracts",
            "tests": "verify_tests_substantive",
            "tdd": "verify_tests_before_code",
            "linters": "verify_linters",
            "coverage": "verify_coverage",
        }
        method_name = method_map.get(criterion.lower())
        if method_name is None:
            import logging

            logging.getLogger(__name__).warning(
                "Unknown DoD criterion: %s (skipping)", criterion
            )
            return _CriterionResult(status=VerificationStatus.SKIP, passed=False)
        method = getattr(verifier, method_name)
        result: VerificationResult = await method()
        return _CriterionResult(status=result.status, passed=result.passed)


@dataclass(frozen=True, slots=True)
class _CriterionResult:
    status: VerificationStatus
    passed: bool
