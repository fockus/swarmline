"""Tests for VerifierRegistry (M4 fix) + DoDStateMachine integration.

The default registry MUST reproduce the existing 5-criterion behaviour
byte-for-byte: `DoDStateMachine(registry=None)` invokes the SAME verify_*
methods with the SAME results as the legacy hardcoded method_map.
"""

from __future__ import annotations

import pytest
from swarmline.orchestration.dod_state_machine import DoDStateMachine, DoDStatus
from swarmline.orchestration.verification_types import (
    VerificationResult,
    VerificationStatus,
)
from swarmline.orchestration.verifier_registry import VerifierRegistry


class RecordingVerifier:
    """Records which verify_* methods were called, in order."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def verify_contracts(self) -> VerificationResult:
        self.calls.append("verify_contracts")
        return VerificationResult(status=VerificationStatus.PASS)

    async def verify_tests_substantive(self) -> VerificationResult:
        self.calls.append("verify_tests_substantive")
        return VerificationResult(status=VerificationStatus.PASS)

    async def verify_tests_before_code(self) -> VerificationResult:
        self.calls.append("verify_tests_before_code")
        return VerificationResult(status=VerificationStatus.PASS)

    async def verify_linters(self) -> VerificationResult:
        self.calls.append("verify_linters")
        return VerificationResult(status=VerificationStatus.PASS)

    async def verify_coverage(self, min_pct: int = 85) -> VerificationResult:
        self.calls.append("verify_coverage")
        return VerificationResult(status=VerificationStatus.PASS)


class TestVerifierRegistryDefault:
    @pytest.mark.asyncio
    async def test_default_registry_keys_match_legacy_criteria(self) -> None:
        registry = VerifierRegistry.default(RecordingVerifier())
        assert set(registry.fns.keys()) == {
            "contracts",
            "tests",
            "tdd",
            "linters",
            "coverage",
        }

    @pytest.mark.asyncio
    async def test_default_registry_closures_bind_correct_methods(self) -> None:
        verifier = RecordingVerifier()
        registry = VerifierRegistry.default(verifier)

        await registry.fns["contracts"]()
        await registry.fns["tests"]()
        await registry.fns["tdd"]()
        await registry.fns["linters"]()
        await registry.fns["coverage"]()

        assert verifier.calls == [
            "verify_contracts",
            "verify_tests_substantive",
            "verify_tests_before_code",
            "verify_linters",
            "verify_coverage",
        ]

    def test_with_check_returns_new_registry_with_extra_key(self) -> None:
        base = VerifierRegistry.default(RecordingVerifier())

        async def extra() -> VerificationResult:
            return VerificationResult(status=VerificationStatus.PASS)

        extended = base.with_check("lint_delta", extra)

        assert "lint_delta" in extended.fns
        assert "lint_delta" not in base.fns  # base untouched (immutable)
        assert extended is not base

    def test_registry_is_frozen(self) -> None:
        registry = VerifierRegistry.default(RecordingVerifier())
        with pytest.raises(Exception):
            registry.fns = {}  # type: ignore[misc]


class TestDoDStateMachineRegistryIntegration:
    @pytest.mark.asyncio
    async def test_verify_dod_default_registry_unchanged(self) -> None:
        """`registry=None` produces the SAME verify_* calls/results as before."""
        verifier_none = RecordingVerifier()
        dod_none = DoDStateMachine(max_loops=3)
        criteria = ("contracts", "tests", "tdd", "linters", "coverage")

        result_none = await dod_none.verify_dod(criteria, verifier_none)

        assert result_none.status == DoDStatus.PASSED
        assert result_none.loop_count == 1
        # All 5 verify_* invoked exactly once, in criteria order.
        assert verifier_none.calls == [
            "verify_contracts",
            "verify_tests_substantive",
            "verify_tests_before_code",
            "verify_linters",
            "verify_coverage",
        ]

    @pytest.mark.asyncio
    async def test_explicit_default_registry_matches_none(self) -> None:
        """Passing VerifierRegistry.default(verifier) == registry=None behaviour."""
        verifier_a = RecordingVerifier()
        verifier_b = RecordingVerifier()
        criteria = ("contracts", "tests", "tdd", "linters", "coverage")

        result_none = await DoDStateMachine(max_loops=3).verify_dod(
            criteria, verifier_a
        )
        result_explicit = await DoDStateMachine(
            max_loops=3, registry=VerifierRegistry.default(verifier_b)
        ).verify_dod(criteria, verifier_b)

        assert result_none.status == result_explicit.status
        assert result_none.loop_count == result_explicit.loop_count
        assert result_none.verification_log == result_explicit.verification_log
        assert verifier_a.calls == verifier_b.calls

    @pytest.mark.asyncio
    async def test_unknown_criterion_still_skips_with_default_registry(self) -> None:
        dod = DoDStateMachine(max_loops=1)
        result = await dod.verify_dod(("coverage 95%",), RecordingVerifier())
        assert result.status == DoDStatus.MAX_LOOPS_EXCEEDED
        assert "coverage 95%: skip" in result.verification_log

    @pytest.mark.asyncio
    async def test_custom_registry_extra_criterion_invoked(self) -> None:
        verifier = RecordingVerifier()
        called: list[str] = []

        async def lint_delta_fn() -> VerificationResult:
            called.append("lint_delta")
            return VerificationResult(status=VerificationStatus.PASS)

        registry = VerifierRegistry.default(verifier).with_check(
            "lint_delta", lint_delta_fn
        )
        dod = DoDStateMachine(max_loops=1, registry=registry)

        result = await dod.verify_dod(("linters", "lint_delta"), verifier)

        assert result.status == DoDStatus.PASSED
        assert called == ["lint_delta"]
        assert verifier.calls == ["verify_linters"]
