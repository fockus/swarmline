"""Tests for ``JudgeVerifier`` — optional, advisory-only verifier.

verify-before-done spec, Task 3 (REQ-007).
TDD: RED phase — tests written BEFORE implementation.

REQ-007 core proof: a judge verifier's output is a supplementary signal
and MUST NEVER be the sole gate. Every ``VerificationOutcome`` produced by
``JudgeVerifier`` has ``advisory=True`` — including exception paths — so
``VerificationLedger.gate_passed`` (which ignores advisory results) can
never be flipped to ``True`` by a judge alone.
"""

from __future__ import annotations

import pytest

from swarmline.protocols import Verifier
from swarmline.types import AcceptanceCriterion, VerificationLedger, VerificationOutcome
from swarmline.verification import JudgeVerifier, LedgerCodeVerifier


# ---------------------------------------------------------------------------
# Helpers — content-branched async judges (never tautological)
# ---------------------------------------------------------------------------


async def _judge_pass(criterion: AcceptanceCriterion, ctx: object) -> tuple[bool, str]:
    return True, f"judge: '{criterion.description}' looks satisfied"


async def _judge_fail(criterion: AcceptanceCriterion, ctx: object) -> tuple[bool, str]:
    return False, f"judge: '{criterion.description}' is not convincing"


async def _judge_raises(
    criterion: AcceptanceCriterion, ctx: object
) -> tuple[bool, str]:
    raise RuntimeError("judge blew up")


async def _predicate_pass(ctx: object) -> tuple[bool, str]:
    return True, "pytest: 42 passed"


# ---------------------------------------------------------------------------
# advisory=True invariant — the core REQ-007 proof
# ---------------------------------------------------------------------------


class TestJudgeVerifierAdvisoryInvariant:
    @pytest.mark.asyncio
    async def test_judge_results_are_advisory_true(self) -> None:
        criterion = AcceptanceCriterion(
            id="c1", description="code reads cleanly", kind="judge"
        )
        ledger = VerificationLedger(criteria=(criterion,))
        verifier = JudgeVerifier(_judge_pass)

        result = await verifier.verify(ledger, ctx=object())

        assert len(result.results) == 1
        outcome = result.results[0]
        assert outcome.criterion_id == "c1"
        assert outcome.passed is True
        assert outcome.advisory is True
        assert outcome.evidence == "judge: 'code reads cleanly' looks satisfied"

    @pytest.mark.asyncio
    async def test_judge_only_criterion_does_not_pass_gate_alone(self) -> None:
        """REQ-007 / scenario 2 — a judge can never be the sole gate.

        A ledger whose ONLY criterion is judge-kind, verified by a judge
        that returns ``passed=True``, must still leave ``gate_passed`` as
        ``True`` here (no non-advisory failure exists to report) BUT the
        recorded result is advisory, so a downstream gate that requires a
        deterministic per-criterion result (Task 4 wiring, per I-024) will
        correctly refuse to treat this ledger as fully verified. This test
        pins the airtight, verifier-local half of the invariant: the judge
        NEVER records a non-advisory outcome, so it can never itself flip
        a real failing criterion to "passed" at the gate level.
        """
        criterion = AcceptanceCriterion(
            id="c1", description="code reads cleanly", kind="judge"
        )
        ledger = VerificationLedger(criteria=(criterion,))
        verifier = JudgeVerifier(_judge_pass)

        result = await verifier.verify(ledger, ctx=object())

        assert len(result.results) == 1
        outcome = result.results[0]
        assert outcome.passed is True
        assert outcome.advisory is True
        # No NON-advisory result exists for this criterion at all — a
        # judge-only criterion can never produce the deterministic
        # evidence a real gate requires.
        assert result.failed == ()
        assert not any(r.advisory is False for r in result.results)


# ---------------------------------------------------------------------------
# Judge exception handling — never crashes, never non-advisory
# ---------------------------------------------------------------------------


class TestJudgeVerifierExceptionHandling:
    @pytest.mark.asyncio
    async def test_judge_exception_produces_advisory_failed_outcome(self) -> None:
        criterion = AcceptanceCriterion(
            id="c1", description="code reads cleanly", kind="judge"
        )
        ledger = VerificationLedger(criteria=(criterion,))
        verifier = JudgeVerifier(_judge_raises)

        result = await verifier.verify(ledger, ctx=object())

        outcome = result.results[0]
        assert outcome.passed is False
        assert outcome.advisory is True
        assert "judge raised" in outcome.evidence
        assert "judge blew up" in outcome.evidence
        # A judge failure must never affect the gate.
        assert result.gate_passed is True
        assert result.failed == ()


# ---------------------------------------------------------------------------
# kind != "judge" criteria are ignored by JudgeVerifier
# ---------------------------------------------------------------------------


class TestJudgeVerifierIgnoresNonJudgeCriteria:
    @pytest.mark.asyncio
    async def test_code_kind_criterion_produces_no_outcome(self) -> None:
        criterion = AcceptanceCriterion(
            id="c1", description="all tests pass", kind="code", check_ref="tests"
        )
        ledger = VerificationLedger(criteria=(criterion,))
        verifier = JudgeVerifier(_judge_pass)

        result = await verifier.verify(ledger, ctx=object())

        assert result.results == ()

    @pytest.mark.asyncio
    async def test_mixed_criteria_only_judge_kind_gets_outcome(self) -> None:
        criterion_code = AcceptanceCriterion(
            id="c1", description="all tests pass", kind="code", check_ref="tests"
        )
        criterion_judge = AcceptanceCriterion(
            id="c2", description="looks clean", kind="judge"
        )
        ledger = VerificationLedger(criteria=(criterion_code, criterion_judge))
        verifier = JudgeVerifier(_judge_pass)

        result = await verifier.verify(ledger, ctx=object())

        assert len(result.results) == 1
        assert result.results[0].criterion_id == "c2"
        assert result.results[0].advisory is True


# ---------------------------------------------------------------------------
# Immutability / append semantics
# ---------------------------------------------------------------------------


class TestJudgeVerifierImmutability:
    @pytest.mark.asyncio
    async def test_judge_verifier_returns_new_ledger_not_mutates_input(self) -> None:
        criterion = AcceptanceCriterion(
            id="c1", description="looks clean", kind="judge"
        )
        ledger = VerificationLedger(criteria=(criterion,))
        original_results = ledger.results
        verifier = JudgeVerifier(_judge_pass)

        result = await verifier.verify(ledger, ctx=object())

        # Input untouched.
        assert ledger.results is original_results
        assert ledger.results == ()
        # Output is a different object with the appended outcome.
        assert result is not ledger
        assert len(result.results) == 1

    @pytest.mark.asyncio
    async def test_judge_verifier_appends_to_existing_results(self) -> None:
        criterion_code = AcceptanceCriterion(
            id="c1", description="all tests pass", kind="code", check_ref="tests"
        )
        criterion_judge = AcceptanceCriterion(
            id="c2", description="looks clean", kind="judge"
        )
        preexisting = VerificationOutcome(
            criterion_id="c1", passed=True, advisory=False, evidence="pytest: 42 passed"
        )
        ledger = VerificationLedger(
            criteria=(criterion_code, criterion_judge), results=(preexisting,)
        )
        verifier = JudgeVerifier(_judge_pass)

        result = await verifier.verify(ledger, ctx=object())

        assert preexisting in result.results
        assert len(result.results) == 2
        new_outcome = next(r for r in result.results if r.criterion_id == "c2")
        assert new_outcome.passed is True
        assert new_outcome.advisory is True


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestJudgeVerifierProtocolConformance:
    def test_judge_verifier_satisfies_verifier_protocol(self) -> None:
        verifier = JudgeVerifier(_judge_pass)
        assert isinstance(verifier, Verifier)


# ---------------------------------------------------------------------------
# Composition — LedgerCodeVerifier then JudgeVerifier on the same ledger
# ---------------------------------------------------------------------------


class TestJudgeVerifierComposesWithCodeVerifier:
    @pytest.mark.asyncio
    async def test_code_then_judge_yields_both_outcomes_gate_reflects_code_only(
        self,
    ) -> None:
        criterion_code = AcceptanceCriterion(
            id="c1", description="all tests pass", kind="code", check_ref="tests"
        )
        criterion_judge = AcceptanceCriterion(
            id="c2", description="looks clean", kind="judge"
        )
        ledger = VerificationLedger(criteria=(criterion_code, criterion_judge))
        code_verifier = LedgerCodeVerifier({"tests": _predicate_pass})
        judge_verifier = JudgeVerifier(_judge_fail)

        after_code = await code_verifier.verify(ledger, ctx=object())
        after_judge = await judge_verifier.verify(after_code, ctx=object())

        assert len(after_judge.results) == 2
        code_outcome = next(r for r in after_judge.results if r.criterion_id == "c1")
        judge_outcome = next(r for r in after_judge.results if r.criterion_id == "c2")
        assert code_outcome.advisory is False
        assert code_outcome.passed is True
        assert judge_outcome.advisory is True
        assert judge_outcome.passed is False
        # Gate reflects only the non-advisory (code) outcome, ignoring the
        # failing judge outcome entirely.
        assert after_judge.gate_passed is True
        assert after_judge.failed == ()
