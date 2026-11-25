"""Unit: finalize gated on the verify-before-done contract (REQ-011, scenario 3).

H6 supervisor-orchestrator, Task 5. Moved out of `tools.py` (SRP + the
400-line ceiling): `create_finalize_tool`/`FINALIZE_TOOL_SPEC` now live in
`finalize.py`. Reuses the EXISTING `verify-before-done` primitives —
`capture_ledger` + `LedgerCodeVerifier` — rather than inventing a parallel
contract-check mechanism.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from swarmline.orchestration.supervisor.blackboard import Blackboard
from swarmline.orchestration.supervisor.finalize import (
    FINALIZE_TOOL_SPEC,
    create_finalize_tool,
)
from swarmline.orchestration.supervisor.state import SupervisorState
from swarmline.orchestration.supervisor.types import Report
from swarmline.orchestration.types import Plan, PlanStep
from swarmline.types import VerificationLedger, VerificationOutcome
from swarmline.verification.capture import capture_ledger
from swarmline.verification.verifiers import JudgeVerifier, LedgerCodeVerifier


def _make_plan() -> Plan:
    return Plan(
        id="plan-1",
        goal="Ship feature X",
        steps=[
            PlanStep(id="step-1", description="Research", status="completed"),
            PlanStep(id="step-2", description="Implement", status="completed"),
        ],
        created_at=datetime(2026, 7, 3, tzinfo=UTC),
    )


def _make_state() -> SupervisorState:
    return SupervisorState(blackboard=Blackboard(plan=_make_plan()))


class TestFinalizeWithoutVerifierIsUnchanged:
    @pytest.mark.asyncio
    async def test_finalize_returns_plain_summary_without_verifier_or_ledger(
        self,
    ) -> None:
        """REQ-012 opt-in back-compat: no verifier/ledger -> the same plain
        summary as before Task 5, never BLOCKED."""
        state = _make_state()
        state.add_report(
            Report(worker="researcher", summary="found X", status="completed")
        )
        execute = create_finalize_tool(state)

        output = await execute({})

        assert "BLOCKED" not in output
        assert "plan-1" in output
        assert "researcher" in output


class TestFinalizeBlockedUntilContractPasses:
    @pytest.mark.asyncio
    async def test_finalize_blocked_until_contract_passes(self) -> None:
        """Scenario 3: a configured verifier+ledger whose code criterion
        FAILS blocks finalize (names the failed criterion, no done claim);
        flipping the predicate to pass makes the SAME finalize call return
        the done summary — idempotent block -> fix -> done, no mutation of
        the original ledger across calls."""
        state = _make_state()
        gate = {"passed": False}

        async def predicate(ctx: object) -> tuple[bool, str]:
            assert ctx is state  # ctx threaded through is the SupervisorState
            return (gate["passed"], "not yet" if not gate["passed"] else "now green")

        ledger = capture_ledger(["all tests pass"], id_prefix="sc")
        verifier = LedgerCodeVerifier({"sc-0": predicate})
        execute = create_finalize_tool(state, verifier=verifier, ledger=ledger)

        blocked = await execute({})
        assert "BLOCKED" in blocked
        assert "sc-0" in blocked

        gate["passed"] = True
        done = await execute({})
        assert "BLOCKED" not in done
        assert "plan-1" in done

        # Idempotent: the ORIGINAL captured ledger was never mutated across
        # either call — `capture_ledger` yields a fresh, criteria-only
        # ledger and `verify()` never replaces the closed-over `ledger`.
        assert ledger.results == ()

        # Re-call after the fix stays green (no accumulated stale failure).
        again = await execute({})
        assert "BLOCKED" not in again

    @pytest.mark.asyncio
    async def test_finalize_blocked_result_lists_failed_criterion_id(self) -> None:
        state = _make_state()

        async def always_fails(ctx: object) -> tuple[bool, str]:
            return (False, "predicate never passes")

        ledger = capture_ledger(["coverage above 90%"], id_prefix="sc")
        verifier = LedgerCodeVerifier({"sc-0": always_fails})
        execute = create_finalize_tool(state, verifier=verifier, ledger=ledger)

        output = await execute({})

        assert output.startswith("BLOCKED")
        assert "sc-0" in output


class _ZeroResultVerifier:
    """A misbehaving/incomplete verifier that reports NO results at all.

    Used to prove finalize does not trust a bare `gate_passed=True` (which is
    vacuously true for `results=()` — see `VerificationLedger.gate_passed`
    docstring) as evidence that anything was actually checked (I-024).
    """

    async def verify(
        self, ledger: VerificationLedger, ctx: object
    ) -> VerificationLedger:
        return VerificationLedger(criteria=ledger.criteria, results=())


class _PartialCoverageVerifier:
    """Verifies only the FIRST criterion of the ledger; the rest get no
    result at all — proving finalize names every uncovered criterion, not
    just the ones with an explicit failing result."""

    async def verify(
        self, ledger: VerificationLedger, ctx: object
    ) -> VerificationLedger:
        covered = ledger.criteria[0]
        results = (
            VerificationOutcome(
                criterion_id=covered.id, passed=True, advisory=False, evidence="ok"
            ),
        )
        return VerificationLedger(criteria=ledger.criteria, results=results)


class TestFinalizeBlockedOnCoverageGap:
    """I-024: `gate_passed` alone is vacuous — a configured verifier/ledger
    that never produced a non-advisory result per criterion must still
    BLOCK, not silently declare done (GPT-5.5 external review r1, REQ-011
    gate incomplete)."""

    @pytest.mark.asyncio
    async def test_finalize_blocked_when_verifier_returns_zero_results(self) -> None:
        state = _make_state()
        ledger = capture_ledger(["all tests pass"], id_prefix="sc")
        execute = create_finalize_tool(
            state, verifier=_ZeroResultVerifier(), ledger=ledger
        )

        output = await execute({})

        assert "BLOCKED" in output
        assert "sc-0" in output
        assert "not_verified" in output

    @pytest.mark.asyncio
    async def test_finalize_blocked_when_only_advisory_results(self) -> None:
        state = _make_state()
        ledger = capture_ledger(["code reads cleanly"], id_prefix="sc", kind="judge")

        async def judge_pass(criterion: object, ctx: object) -> tuple[bool, str]:
            return True, "judge: looks great"

        execute = create_finalize_tool(
            state, verifier=JudgeVerifier(judge_pass), ledger=ledger
        )

        output = await execute({})

        assert "BLOCKED" in output
        assert "sc-0" in output
        assert "not_verified" in output

    @pytest.mark.asyncio
    async def test_finalize_blocked_when_a_criterion_has_no_nonadvisory_result(
        self,
    ) -> None:
        state = _make_state()
        ledger = capture_ledger(["all tests pass", "no lint errors"], id_prefix="sc")
        execute = create_finalize_tool(
            state, verifier=_PartialCoverageVerifier(), ledger=ledger
        )

        output = await execute({})

        assert "BLOCKED" in output
        assert "sc-1" in output
        assert "not_verified" in output
        # sc-0 is covered and passing — must not be named as unmet.
        assert "sc-0 (" not in output


class TestFinalizeToolSpec:
    def test_finalize_tool_spec_unchanged_shape(self) -> None:
        assert FINALIZE_TOOL_SPEC.name == "finalize"
        assert FINALIZE_TOOL_SPEC.is_local is True
