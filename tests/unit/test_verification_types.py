"""Tests for VerificationResult, VerificationStatus, CheckDetail types."""

from __future__ import annotations

from swarmline.orchestration.verification_types import (
    CheckDetail,
    VerificationResult,
    VerificationStatus,
)


class TestVerificationStatus:
    def test_status_values(self) -> None:
        assert VerificationStatus.PASS == "pass"
        assert VerificationStatus.FAIL == "fail"
        assert VerificationStatus.SKIP == "skip"

    def test_status_is_str(self) -> None:
        assert isinstance(VerificationStatus.PASS, str)


class TestCheckDetail:
    def test_check_detail_defaults(self) -> None:
        check = CheckDetail(name="lint", status=VerificationStatus.PASS)
        assert check.name == "lint"
        assert check.status == VerificationStatus.PASS
        assert check.message == ""

    def test_check_detail_with_message(self) -> None:
        check = CheckDetail(
            name="ty",
            status=VerificationStatus.FAIL,
            message="Found 3 type errors",
        )
        assert check.message == "Found 3 type errors"

    def test_check_detail_is_frozen(self) -> None:
        check = CheckDetail(name="test", status=VerificationStatus.PASS)
        try:
            check.name = "other"  # type: ignore[misc]
            raise AssertionError("Expected FrozenInstanceError")
        except AttributeError:
            pass


class TestVerificationResult:
    def test_verification_result_pass(self) -> None:
        result = VerificationResult(
            status=VerificationStatus.PASS,
            checks=(
                CheckDetail(name="lint", status=VerificationStatus.PASS),
                CheckDetail(name="test", status=VerificationStatus.PASS),
            ),
            summary="All checks passed",
        )
        assert result.passed is True
        assert result.status == VerificationStatus.PASS
        assert len(result.checks) == 2
        assert result.summary == "All checks passed"

    def test_verification_result_fail_with_checks(self) -> None:
        result = VerificationResult(
            status=VerificationStatus.FAIL,
            checks=(
                CheckDetail(name="lint", status=VerificationStatus.PASS),
                CheckDetail(
                    name="ty",
                    status=VerificationStatus.FAIL,
                    message="2 errors",
                ),
            ),
            summary="ty failed",
        )
        assert result.passed is False
        assert result.status == VerificationStatus.FAIL
        failed = [c for c in result.checks if c.status == VerificationStatus.FAIL]
        assert len(failed) == 1
        assert failed[0].name == "ty"

    def test_verification_result_skip(self) -> None:
        result = VerificationResult(status=VerificationStatus.SKIP)
        assert result.passed is False
        assert result.checks == ()
        assert result.summary == ""

    def test_verification_result_defaults(self) -> None:
        result = VerificationResult(status=VerificationStatus.PASS)
        assert result.checks == ()
        assert result.summary == ""
        assert result.passed is True
