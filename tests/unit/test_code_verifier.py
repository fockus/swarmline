"""Tests for CodeVerifier protocol, TddCodeVerifier, and PlanStep DoD fields."""

from __future__ import annotations

import pytest
from swarmline.orchestration.code_verifier import CommandResult
from swarmline.orchestration.coding_standards import CodingStandardsConfig
from swarmline.orchestration.tdd_code_verifier import TddCodeVerifier
from swarmline.orchestration.types import PlanStep
from swarmline.orchestration.verification_types import VerificationStatus


class FakeRunner:
    """Fake CommandRunner for testing."""

    def __init__(self, exit_code: int = 0, stdout: str = "", stderr: str = "") -> None:
        self._exit_code = exit_code
        self._stdout = stdout
        self._stderr = stderr
        self.commands: list[str] = []

    async def run(self, command: str) -> CommandResult:
        self.commands.append(command)
        return CommandResult(
            exit_code=self._exit_code,
            stdout=self._stdout,
            stderr=self._stderr,
        )


class TestTddVerifierDisabledChecks:
    @pytest.mark.asyncio
    async def test_tdd_verifier_disabled_check_returns_skip(self) -> None:
        config = CodingStandardsConfig.off()
        runner = FakeRunner()
        verifier = TddCodeVerifier(config, runner)

        result = await verifier.verify_coverage()
        assert result.status == VerificationStatus.SKIP
        assert "TDD disabled" in result.summary
        assert runner.commands == []

    @pytest.mark.asyncio
    async def test_verify_contracts_skip_when_solid_off(self) -> None:
        config = CodingStandardsConfig(tdd_enabled=True, solid_enabled=False)
        runner = FakeRunner()
        verifier = TddCodeVerifier(config, runner)

        result = await verifier.verify_contracts()
        assert result.status == VerificationStatus.SKIP
        assert runner.commands == []

    @pytest.mark.asyncio
    async def test_verify_tests_substantive_skip_when_tdd_off(self) -> None:
        config = CodingStandardsConfig.off()
        runner = FakeRunner()
        verifier = TddCodeVerifier(config, runner)

        result = await verifier.verify_tests_substantive()
        assert result.status == VerificationStatus.SKIP


class TestTddVerifierLinters:
    @pytest.mark.asyncio
    async def test_tdd_verifier_linters_pass(self) -> None:
        config = CodingStandardsConfig.strict()
        runner = FakeRunner(exit_code=0, stdout="All checks passed!")
        verifier = TddCodeVerifier(config, runner)

        result = await verifier.verify_linters()
        assert result.status == VerificationStatus.PASS
        assert result.passed is True
        assert len(result.checks) == 1
        assert result.checks[0].name == "ruff"
        assert "ruff check ." in runner.commands

    @pytest.mark.asyncio
    async def test_tdd_verifier_linters_fail(self) -> None:
        config = CodingStandardsConfig.strict()
        runner = FakeRunner(exit_code=1, stderr="E501: line too long")
        verifier = TddCodeVerifier(config, runner)

        result = await verifier.verify_linters()
        assert result.status == VerificationStatus.FAIL
        assert result.passed is False


class TestTddVerifierCoverage:
    @pytest.mark.asyncio
    async def test_tdd_verifier_coverage_below_threshold(self) -> None:
        config = CodingStandardsConfig.strict()
        runner = FakeRunner(exit_code=1, stderr="FAIL: coverage 80% < 95%")
        verifier = TddCodeVerifier(config, runner)

        result = await verifier.verify_coverage(min_pct=85)
        assert result.status == VerificationStatus.FAIL
        assert len(result.checks) == 1
        assert result.checks[0].name == "coverage"
        # strict config has min_coverage_pct=95, so effective min = max(85, 95) = 95
        assert "min=95%" in result.checks[0].message

    @pytest.mark.asyncio
    async def test_tdd_verifier_coverage_pass(self) -> None:
        config = CodingStandardsConfig.minimal()
        runner = FakeRunner(exit_code=0, stdout="Coverage: 92%")
        verifier = TddCodeVerifier(config, runner)

        result = await verifier.verify_coverage(min_pct=85)
        assert result.status == VerificationStatus.PASS
        # minimal has min_coverage_pct=70, effective = max(85, 70) = 85
        assert "pytest --cov --cov-fail-under=85" in runner.commands[0]


class TestPlanStepDodFields:
    def test_plan_step_dod_fields_default(self) -> None:
        step = PlanStep(id="s1", description="Do something")
        assert step.dod_criteria == ()
        assert step.dod_verified is False
        assert step.verification_log is None

    def test_plan_step_dod_fields_preserved_on_transition(self) -> None:
        step = PlanStep(
            id="s1",
            description="Implement feature",
            dod_criteria=("tests pass", "lint clean"),
            dod_verified=False,
        )
        started = step.start()
        assert started.status == "in_progress"
        assert started.dod_criteria == ("tests pass", "lint clean")
        assert started.dod_verified is False

        completed = started.complete("Done")
        assert completed.status == "completed"
        assert completed.dod_criteria == ("tests pass", "lint clean")

    def test_plan_step_with_verification_log(self) -> None:
        step = PlanStep(
            id="s1",
            description="Test",
            dod_criteria=("coverage 95%",),
            dod_verified=True,
            verification_log="All checks passed at 96%",
        )
        assert step.dod_verified is True
        assert step.verification_log == "All checks passed at 96%"
