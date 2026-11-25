"""Tests for ``LedgerCodeVerifier`` — primary deterministic verifier.

verify-before-done spec, Task 2 (REQ-004, REQ-006).
TDD: RED phase — tests written BEFORE implementation.

NOTE: named ``LedgerCodeVerifier`` (not ``CodeVerifier``) precisely to
avoid colliding with the pre-existing, unrelated
``swarmline.orchestration.code_verifier.CodeVerifier`` Protocol (5-method
code-QUALITY pipeline — verify_contracts/verify_tests_substantive/...).
This mirrors the Task-1 precedent of renaming ``VerificationResult`` ->
``VerificationOutcome`` to dodge the same kind of vocabulary collision.
"""

from __future__ import annotations

import pytest

from swarmline.protocols import Verifier
from swarmline.types import AcceptanceCriterion, VerificationLedger, VerificationOutcome
from swarmline.verification import LedgerCodeVerifier


# ---------------------------------------------------------------------------
# Helpers — content-branched async predicates (never tautological)
# ---------------------------------------------------------------------------


async def _predicate_pass(ctx: object) -> tuple[bool, str]:
    return True, "pytest: 42 passed"


async def _predicate_fail(ctx: object) -> tuple[bool, str]:
    return False, "boom"


async def _predicate_raises(ctx: object) -> tuple[bool, str]:
    raise RuntimeError("predicate blew up")


# ---------------------------------------------------------------------------
# Core pass/fail behaviour
# ---------------------------------------------------------------------------


class TestLedgerCodeVerifierPassFail:
    @pytest.mark.asyncio
    async def test_code_verifier_marks_passed_when_predicate_true(self) -> None:
        criterion = AcceptanceCriterion(
            id="c1", description="all tests pass", kind="code", check_ref="tests"
        )
        ledger = VerificationLedger(criteria=(criterion,))
        verifier = LedgerCodeVerifier({"tests": _predicate_pass})

        result = await verifier.verify(ledger, ctx=object())

        assert len(result.results) == 1
        outcome = result.results[0]
        assert outcome.criterion_id == "c1"
        assert outcome.passed is True
        assert outcome.advisory is False
        assert outcome.evidence == "pytest: 42 passed"
        assert result.gate_passed is True

    @pytest.mark.asyncio
    async def test_code_verifier_marks_failed_with_evidence_when_predicate_false(
        self,
    ) -> None:
        criterion = AcceptanceCriterion(
            id="c1", description="all tests pass", kind="code", check_ref="tests"
        )
        ledger = VerificationLedger(criteria=(criterion,))
        verifier = LedgerCodeVerifier({"tests": _predicate_fail})

        result = await verifier.verify(ledger, ctx=object())

        assert len(result.results) == 1
        outcome = result.results[0]
        assert outcome.passed is False
        assert outcome.advisory is False
        assert outcome.evidence == "boom"
        assert result.gate_passed is False
        assert result.failed == (outcome,)


# ---------------------------------------------------------------------------
# Immutability / append semantics
# ---------------------------------------------------------------------------


class TestLedgerCodeVerifierImmutability:
    @pytest.mark.asyncio
    async def test_code_verifier_returns_new_ledger_not_mutates_input(self) -> None:
        criterion = AcceptanceCriterion(
            id="c1", description="all tests pass", kind="code", check_ref="tests"
        )
        ledger = VerificationLedger(criteria=(criterion,))
        original_results = ledger.results
        verifier = LedgerCodeVerifier({"tests": _predicate_pass})

        result = await verifier.verify(ledger, ctx=object())

        # Input untouched.
        assert ledger.results is original_results
        assert ledger.results == ()
        # Output is a different object with the appended outcome.
        assert result is not ledger
        assert len(result.results) == 1

    @pytest.mark.asyncio
    async def test_code_verifier_appends_to_existing_results(self) -> None:
        criterion_code = AcceptanceCriterion(
            id="c1", description="all tests pass", kind="code", check_ref="tests"
        )
        criterion_judge = AcceptanceCriterion(
            id="c2", description="looks clean", kind="judge"
        )
        preexisting = VerificationOutcome(
            criterion_id="c2", passed=True, advisory=True, evidence="judge: looks fine"
        )
        ledger = VerificationLedger(
            criteria=(criterion_code, criterion_judge), results=(preexisting,)
        )
        verifier = LedgerCodeVerifier({"tests": _predicate_pass})

        result = await verifier.verify(ledger, ctx=object())

        assert preexisting in result.results
        assert len(result.results) == 2
        new_outcome = next(r for r in result.results if r.criterion_id == "c1")
        assert new_outcome.passed is True


# ---------------------------------------------------------------------------
# Fail-safe behaviours — an unverifiable code criterion never passes
# ---------------------------------------------------------------------------


class TestLedgerCodeVerifierFailSafe:
    @pytest.mark.asyncio
    async def test_missing_check_ref_produces_fail_safe_outcome(self) -> None:
        criterion = AcceptanceCriterion(
            id="c1", description="all tests pass", kind="code", check_ref=None
        )
        ledger = VerificationLedger(criteria=(criterion,))
        verifier = LedgerCodeVerifier({})

        result = await verifier.verify(ledger, ctx=object())

        outcome = result.results[0]
        assert outcome.passed is False
        assert outcome.advisory is False
        assert "no predicate registered" in outcome.evidence
        assert "None" in outcome.evidence

    @pytest.mark.asyncio
    async def test_unregistered_check_ref_produces_fail_safe_outcome(self) -> None:
        criterion = AcceptanceCriterion(
            id="c1",
            description="all tests pass",
            kind="code",
            check_ref="nonexistent",
        )
        ledger = VerificationLedger(criteria=(criterion,))
        verifier = LedgerCodeVerifier({"tests": _predicate_pass})

        result = await verifier.verify(ledger, ctx=object())

        outcome = result.results[0]
        assert outcome.passed is False
        assert outcome.advisory is False
        assert "no predicate registered for check_ref=nonexistent" in outcome.evidence

    @pytest.mark.asyncio
    async def test_predicate_exception_produces_fail_safe_outcome(self) -> None:
        criterion = AcceptanceCriterion(
            id="c1", description="all tests pass", kind="code", check_ref="tests"
        )
        ledger = VerificationLedger(criteria=(criterion,))
        verifier = LedgerCodeVerifier({"tests": _predicate_raises})

        result = await verifier.verify(ledger, ctx=object())

        outcome = result.results[0]
        assert outcome.passed is False
        assert outcome.advisory is False
        assert "predicate raised" in outcome.evidence
        assert "predicate blew up" in outcome.evidence
        assert result.gate_passed is False


# ---------------------------------------------------------------------------
# kind="judge" criteria are ignored by LedgerCodeVerifier
# ---------------------------------------------------------------------------


class TestLedgerCodeVerifierIgnoresJudgeCriteria:
    @pytest.mark.asyncio
    async def test_judge_kind_criterion_produces_no_outcome(self) -> None:
        criterion = AcceptanceCriterion(
            id="c1", description="looks clean", kind="judge"
        )
        ledger = VerificationLedger(criteria=(criterion,))
        verifier = LedgerCodeVerifier({})

        result = await verifier.verify(ledger, ctx=object())

        assert result.results == ()

    @pytest.mark.asyncio
    async def test_mixed_criteria_only_code_kind_gets_outcome(self) -> None:
        criterion_code = AcceptanceCriterion(
            id="c1", description="all tests pass", kind="code", check_ref="tests"
        )
        criterion_judge = AcceptanceCriterion(
            id="c2", description="looks clean", kind="judge"
        )
        ledger = VerificationLedger(criteria=(criterion_code, criterion_judge))
        verifier = LedgerCodeVerifier({"tests": _predicate_pass})

        result = await verifier.verify(ledger, ctx=object())

        assert len(result.results) == 1
        assert result.results[0].criterion_id == "c1"


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestLedgerCodeVerifierProtocolConformance:
    def test_ledger_code_verifier_satisfies_verifier_protocol(self) -> None:
        verifier = LedgerCodeVerifier({})
        assert isinstance(verifier, Verifier)
