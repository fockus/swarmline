"""Coverage tests: TddCodeVerifier - vse verify_* metody + skip paths."""

from __future__ import annotations

from swarmline.orchestration.code_verifier import CommandResult
from swarmline.orchestration.coding_standards import CodingStandardsConfig
from swarmline.orchestration.tdd_code_verifier import TddCodeVerifier
from swarmline.orchestration.verification_types import VerificationStatus


class FakeRunner:
    """InMemory CommandRunner - returns zadannyy result."""

    def __init__(
        self, exit_code: int = 0, stdout: str = "ok", stderr: str = ""
    ) -> None:
        self._result = CommandResult(exit_code=exit_code, stdout=stdout, stderr=stderr)
        self.commands: list[str] = []

    async def run(self, command: str) -> CommandResult:
        self.commands.append(command)
        return self._result


def _config(
    tdd: bool = True,
    solid: bool = True,
    coverage: int = 85,
) -> CodingStandardsConfig:
    return CodingStandardsConfig(
        tdd_enabled=tdd,
        solid_enabled=solid,
        min_coverage_pct=coverage,
    )


class TestVerifyContracts:
    """verify_contracts: solid_enabled → run, else skip."""

    async def test_verify_contracts_pass(self) -> None:
        runner = FakeRunner(exit_code=0, stdout="3 passed")
        v = TddCodeVerifier(_config(solid=True), runner)
        result = await v.verify_contracts()
        assert result.status == VerificationStatus.PASS
        assert "contract" in runner.commands[0]

    async def test_verify_contracts_fail(self) -> None:
        runner = FakeRunner(exit_code=1, stdout="1 failed")
        v = TddCodeVerifier(_config(solid=True), runner)
        result = await v.verify_contracts()
        assert result.status == VerificationStatus.FAIL

    async def test_verify_contracts_skip_when_solid_off(self) -> None:
        runner = FakeRunner()
        v = TddCodeVerifier(_config(solid=False), runner)
        result = await v.verify_contracts()
        assert result.status == VerificationStatus.SKIP
        assert runner.commands == []


class TestVerifyTestsSubstantive:
    """verify_tests_substantive: tdd_enabled → run, else skip."""

    async def test_verify_tests_substantive_pass(self) -> None:
        runner = FakeRunner(exit_code=0)
        v = TddCodeVerifier(_config(tdd=True), runner)
        result = await v.verify_tests_substantive()
        assert result.status == VerificationStatus.PASS

    async def test_verify_tests_substantive_skip_when_tdd_off(self) -> None:
        runner = FakeRunner()
        v = TddCodeVerifier(_config(tdd=False), runner)
        result = await v.verify_tests_substantive()
        assert result.status == VerificationStatus.SKIP


class TestVerifyTestsBeforeCode:
    """verify_tests_before_code: tdd_enabled → git log heuristic."""

    async def test_verify_tests_before_code_pass(self) -> None:
        runner = FakeRunner(exit_code=0, stdout="abc test: add tests\ndef feat: impl")
        v = TddCodeVerifier(_config(tdd=True), runner)
        result = await v.verify_tests_before_code()
        assert result.status == VerificationStatus.PASS
        assert "git log" in runner.commands[0]

    async def test_verify_tests_before_code_skip(self) -> None:
        runner = FakeRunner()
        v = TddCodeVerifier(_config(tdd=False), runner)
        result = await v.verify_tests_before_code()
        assert result.status == VerificationStatus.SKIP


class TestVerifyLinters:
    """verify_linters: always runs (no skip path)."""

    async def test_verify_linters_pass(self) -> None:
        runner = FakeRunner(exit_code=0, stdout="All checks passed!")
        v = TddCodeVerifier(_config(), runner)
        result = await v.verify_linters()
        assert result.status == VerificationStatus.PASS
        assert result.checks[0].name == "ruff"

    async def test_verify_linters_fail(self) -> None:
        runner = FakeRunner(exit_code=1, stderr="E501 line too long")
        v = TddCodeVerifier(_config(), runner)
        result = await v.verify_linters()
        assert result.status == VerificationStatus.FAIL


class TestVerifyCoverage:
    """verify_coverage: uses max(min_pct, config.min_coverage_pct)."""

    async def test_verify_coverage_pass(self) -> None:
        runner = FakeRunner(exit_code=0, stdout="90% coverage")
        v = TddCodeVerifier(_config(coverage=85), runner)
        result = await v.verify_coverage(min_pct=80)
        assert result.status == VerificationStatus.PASS
        # max(80, 85) = 85
        assert "85" in runner.commands[0]

    async def test_verify_coverage_fail(self) -> None:
        runner = FakeRunner(exit_code=1, stderr="Coverage 70% < 90%")
        v = TddCodeVerifier(_config(coverage=90), runner)
        result = await v.verify_coverage(min_pct=85)
        assert result.status == VerificationStatus.FAIL

    async def test_verify_coverage_skip_tdd_off(self) -> None:
        runner = FakeRunner()
        v = TddCodeVerifier(_config(tdd=False), runner)
        result = await v.verify_coverage()
        assert result.status == VerificationStatus.SKIP

    async def test_verify_coverage_min_pct_takes_max(self) -> None:
        runner = FakeRunner(exit_code=0)
        v = TddCodeVerifier(_config(coverage=70), runner)
        await v.verify_coverage(min_pct=95)
        # max(95, 70) = 95
        assert "95" in runner.commands[0]
