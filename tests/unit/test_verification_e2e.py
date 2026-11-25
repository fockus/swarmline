"""End-to-end: capture -> block -> fix -> done (REQ-002, REQ-004/005, I-027).

verify-before-done spec, Task 5 — the FINAL task of the epic.
TDD: RED phase — written BEFORE ``swarmline.verification.capture`` exists.

This is the key proof that ties every prior task together:

1. A contract (ledger) is captured up front from ``success_criteria``
   (REQ-002, Task 5's own capture primitive).
2. The SAME ``RuntimeConfig`` is driven through
   ``finalize_with_validation`` (Task 4's gate) TWICE against a mutable
   predicate: first the predicate reports failure -> the gate blocks with
   a ``guardrail_tripwire`` error naming the unmet criterion, no final
   event (REQ-004/005).
3. The predicate is "fixed" (flipped to report success) with NO other
   change to the config or the ledger.
4. The gate is re-run -> it now passes, emitting a single final event and
   no error.

Step 4 only works because the gate always re-verifies a FRESH,
criteria-only ledger on every attempt (I-027, ``gate.py``) rather than
trusting any ``results`` recorded on a previous pass -- this test is the
end-to-end proof of that mechanism, driven through the public capture ->
finalize surface rather than by inspecting ``gate.py`` internals directly.
"""

from __future__ import annotations

import time

import pytest

from swarmline.runtime.thin.finalization import finalize_with_validation
from swarmline.runtime.types import RuntimeConfig
from swarmline.verification import LedgerCodeVerifier
from swarmline.verification.capture import capture_ledger


async def _drain(agen) -> list:
    return [event async for event in agen]


async def _unused_llm_call(messages, prompt, **kwargs):
    raise AssertionError(
        "llm_call must not be invoked on the non-structured finalize path"
    )


class _MutablePredicate:
    """A predicate whose verdict can be flipped between finalize attempts.

    Stands in for "the fix landed": the SAME closure/object is re-used by
    the SAME ``LedgerCodeVerifier`` instance across both finalize attempts
    -- only its internal state changes, exactly like a real `pytest`-backed
    predicate would report differently before/after a code fix.
    """

    def __init__(self) -> None:
        self.passing = False

    async def __call__(self, ctx: object) -> tuple[bool, str]:
        if self.passing:
            return True, "all green"
        return False, "3 tests failing"


class TestEndToEndContractBlocksThenPassesAfterFix:
    @pytest.mark.asyncio
    async def test_end_to_end_contract_blocks_then_passes_after_fix(self) -> None:
        # 1. Capture the contract up front (REQ-002).
        ledger = capture_ledger(["all tests pass"], id_prefix="sc")
        (criterion,) = ledger.criteria
        assert criterion.id == "sc-0"
        assert criterion.check_ref == "sc-0"

        predicate = _MutablePredicate()
        config = RuntimeConfig(
            model="gpt-4o",
            verification_ledger=ledger,
            verifier=LedgerCodeVerifier({"sc-0": predicate}),
        )

        # 2. First finalize attempt -> BLOCKED (predicate still failing).
        blocked_events = await _drain(
            finalize_with_validation(
                text="done",
                config=config,
                lm_messages=[{"role": "user", "content": "go"}],
                prompt="SYS",
                llm_call=_unused_llm_call,
                start_time=time.monotonic(),
            )
        )

        assert not any(e.is_final for e in blocked_events), (
            "no final event may be emitted while the criterion is unmet"
        )
        last_blocked = blocked_events[-1]
        assert last_blocked.is_error
        assert last_blocked.data["kind"] == "guardrail_tripwire"
        unmet = last_blocked.data["details"]["unmet"]
        assert len(unmet) == 1
        assert unmet[0]["criterion_id"] == "sc-0"
        assert unmet[0]["reason"] == "failed"
        assert unmet[0]["evidence"] == "3 tests failing"

        # 3. "Fix": flip the predicate's verdict. Nothing else about the
        #    config or the ledger changes.
        predicate.passing = True

        # 4. Second finalize attempt with the SAME config -> now PASSES.
        #    This only works if the gate re-verifies from a fresh ledger
        #    each attempt (I-027) rather than trusting the stale FAIL.
        passed_events = await _drain(
            finalize_with_validation(
                text="done",
                config=config,
                lm_messages=[{"role": "user", "content": "go"}],
                prompt="SYS",
                llm_call=_unused_llm_call,
                start_time=time.monotonic(),
            )
        )

        assert len(passed_events) == 1
        assert passed_events[0].is_final
        assert not any(e.is_error for e in passed_events)


class TestEndToEndEmptyLedgerIsNoOp:
    @pytest.mark.asyncio
    async def test_end_to_end_no_success_criteria_is_gate_no_op(self) -> None:
        """REQ-009: a captured ledger with zero criteria never blocks finalize."""
        ledger = capture_ledger([])

        config = RuntimeConfig(
            model="gpt-4o",
            verification_ledger=ledger,
            verifier=LedgerCodeVerifier({}),
        )

        events = await _drain(
            finalize_with_validation(
                text="done",
                config=config,
                lm_messages=[{"role": "user", "content": "go"}],
                prompt="SYS",
                llm_call=_unused_llm_call,
                start_time=time.monotonic(),
            )
        )

        assert len(events) == 1
        assert events[0].is_final
