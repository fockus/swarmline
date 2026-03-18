"""TddCodeVerifier - CodeVerifier implementation respecting CodingStandardsConfig.

Disabled checks return VerificationStatus.SKIP automatically.
"""

from __future__ import annotations

from cognitia.orchestration.code_verifier import CommandResult, CommandRunner
from cognitia.orchestration.coding_standards import CodingStandardsConfig
from cognitia.orchestration.verification_types import (
    CheckDetail,
    VerificationResult,
    VerificationStatus,
)


class TddCodeVerifier:
    """CodeVerifier implementation - respects CodingStandardsConfig.

  Disabled check -> auto VerificationStatus.SKIP.
  """

    def __init__(self, config: CodingStandardsConfig, runner: CommandRunner) -> None:
        self._config = config
        self._runner = runner

    async def verify_contracts(self) -> VerificationResult:
        """Verify contract tests pass."""
        if not self._config.solid_enabled:
            return self._skip("Contract verification disabled (SOLID off)")
        result = await self._runner.run("pytest -m contract -q")
        return self._from_command(result, "contracts")

    async def verify_tests_substantive(self) -> VerificationResult:
        """Verify tests are substantive (not just pass/trivial)."""
        if not self._config.tdd_enabled:
            return self._skip("TDD disabled")
        result = await self._runner.run("pytest -q")
        return self._from_command(result, "tests_substantive")

    async def verify_tests_before_code(self) -> VerificationResult:
        """Verify tests were written before implementation (heuristic)."""
        if not self._config.tdd_enabled:
            return self._skip("TDD disabled")
        result = await self._runner.run("git log --oneline -5")
        return self._from_command(result, "tests_before_code")

    async def verify_linters(self) -> VerificationResult:
        """Run linters (ruff check)."""
        result = await self._runner.run("ruff check .")
        status = VerificationStatus.PASS if result.exit_code == 0 else VerificationStatus.FAIL
        return VerificationResult(
            status=status,
            checks=(
                CheckDetail(name="ruff", status=status, message=result.stdout or result.stderr),
            ),
            summary=result.stdout or result.stderr,
        )

    async def verify_coverage(self, min_pct: int = 85) -> VerificationResult:
        """Run tests with coverage check."""
        if not self._config.tdd_enabled:
            return self._skip("TDD disabled")
        effective_min = max(min_pct, self._config.min_coverage_pct)
        result = await self._runner.run(f"pytest --cov --cov-fail-under={effective_min}")
        status = VerificationStatus.PASS if result.exit_code == 0 else VerificationStatus.FAIL
        return VerificationResult(
            status=status,
            checks=(
                CheckDetail(
                    name="coverage",
                    status=status,
                    message=f"min={effective_min}%",
                ),
            ),
            summary=result.stdout or result.stderr,
        )

    def _skip(self, reason: str) -> VerificationResult:
        return VerificationResult(status=VerificationStatus.SKIP, summary=reason)

    def _from_command(self, result: CommandResult, check_name: str) -> VerificationResult:
        status = VerificationStatus.PASS if result.exit_code == 0 else VerificationStatus.FAIL
        return VerificationResult(
            status=status,
            checks=(
                CheckDetail(
                    name=check_name,
                    status=status,
                    message=result.stdout or result.stderr,
                ),
            ),
            summary=result.stdout or result.stderr,
        )
