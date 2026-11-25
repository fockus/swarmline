"""Opt-in verify-before-done gate wired into ``finalize_with_validation``.

verify-before-done spec, Task 4 (REQ-004, REQ-005, REQ-008, REQ-009, REQ-010).
TDD: RED phase -- written BEFORE ``RuntimeConfig.verification_ledger``/``verifier``
and the gate helper exist.

Closes two HIGH carry-forwards from Task 1/Task 2:

- I-024 (coverage-aware gate): ``VerificationLedger.gate_passed`` alone is vacuously
  True for a criterion with only advisory (judge) results or no result at all. The
  gate wired here must treat such a criterion as UNCOVERED -> blocks, proving
  REQ-007 scenario 2 end-to-end (a judge can never be the sole gate).
- I-027 (fresh re-verify): a stale FAIL recorded on a prior finalize attempt in
  ``config.verification_ledger.results`` must never stick across a
  block -> fix -> done re-run; the gate always re-verifies from a FRESH
  criteria-only ledger.

No network: ``llm_call`` stands in for the provider (only exercised on the
structured-retry-success finalize path).
"""

from __future__ import annotations

import time

import pytest
from pydantic import BaseModel

from swarmline.types import AcceptanceCriterion, VerificationLedger, VerificationOutcome
from swarmline.verification import JudgeVerifier, LedgerCodeVerifier
from swarmline.runtime.thin.finalization import finalize_with_validation
from swarmline.runtime.types import RuntimeConfig


class _Answer(BaseModel):
    answer: str = ""


async def _drain(agen) -> list:
    return [event async for event in agen]


def _config(**kwargs) -> RuntimeConfig:
    return RuntimeConfig(model="gpt-4o", **kwargs)


async def _unused_llm_call(messages, prompt, **kwargs):
    raise AssertionError(
        "llm_call must not be invoked on the non-structured finalize path"
    )


# ---------------------------------------------------------------------------
# scenario 1 (REQ-004/005/006) — unmet criterion blocks done, names it + evidence
# ---------------------------------------------------------------------------


class TestGateBlocksOnUnmetCriterion:
    @pytest.mark.asyncio
    async def test_finalize_blocked_when_criterion_unmet_reports_failed(self) -> None:
        criterion = AcceptanceCriterion(
            id="c1", description="all tests pass", kind="code", check_ref="tests"
        )
        ledger = VerificationLedger(criteria=(criterion,))

        async def failing_predicate(ctx: object) -> tuple[bool, str]:
            return False, "tests failing: 3"

        config = _config(
            verification_ledger=ledger,
            verifier=LedgerCodeVerifier({"tests": failing_predicate}),
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

        assert not any(e.is_final for e in events), (
            "no final event may be emitted when the gate blocks"
        )
        last = events[-1]
        assert last.is_error
        assert last.data["kind"] == "guardrail_tripwire"
        unmet = last.data["details"]["unmet"]
        assert len(unmet) == 1
        assert unmet[0]["criterion_id"] == "c1"
        assert unmet[0]["description"] == "all tests pass"
        assert unmet[0]["reason"] == "failed"
        assert unmet[0]["evidence"] == "tests failing: 3"

    @pytest.mark.asyncio
    async def test_gate_blocks_after_structured_retry_success(self) -> None:
        """Same scenario-1 block, but on the OTHER finalize success site (~254):

        phase-1 text fails to parse -> the retry loop runs -> the retry succeeds
        (schema-valid) -> the gate must still intercept BEFORE the final event.
        """
        criterion = AcceptanceCriterion(
            id="c1", description="all tests pass", kind="code", check_ref="tests"
        )
        ledger = VerificationLedger(criteria=(criterion,))

        async def failing_predicate(ctx: object) -> tuple[bool, str]:
            return False, "still red"

        config = RuntimeConfig(
            model="gpt-4o",
            output_type=_Answer,
            output_format=_Answer.model_json_schema(),
            max_model_retries=2,
            verification_ledger=ledger,
            verifier=LedgerCodeVerifier({"tests": failing_predicate}),
        )

        async def llm_call(messages, prompt, **kwargs):
            return '{"answer": "done"}'

        events = await _drain(
            finalize_with_validation(
                text="not json",  # forces the retry loop -> success at site ~254
                config=config,
                lm_messages=[{"role": "user", "content": "go"}],
                prompt="SYS",
                llm_call=llm_call,
                start_time=time.monotonic(),
            )
        )

        assert not any(e.is_final for e in events), (
            "the retry-success finalize path must also honor the gate"
        )
        last = events[-1]
        assert last.is_error
        assert last.data["kind"] == "guardrail_tripwire"


# ---------------------------------------------------------------------------
# scenario 3 (REQ-008/009) — empty/disabled ledger = no-op, byte-identical
# ---------------------------------------------------------------------------


class TestGateNoOpWhenDisabledOrEmpty:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "extra_kwargs",
        [
            pytest.param({}, id="verification_ledger_none"),
            pytest.param(
                {
                    "verification_ledger": VerificationLedger(criteria=()),
                    "verifier": LedgerCodeVerifier({}),
                },
                id="empty_criteria",
            ),
            pytest.param(
                {
                    "verification_ledger": VerificationLedger(
                        criteria=(
                            AcceptanceCriterion(
                                id="c1",
                                description="x",
                                kind="code",
                                check_ref="tests",
                            ),
                        )
                    ),
                    "verifier": None,
                },
                id="verifier_none",
            ),
        ],
    )
    async def test_finalize_unchanged_when_ledger_empty_or_disabled(
        self, extra_kwargs: dict
    ) -> None:
        config = _config(**extra_kwargs)

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
        assert events[0].text == "done"


# ---------------------------------------------------------------------------
# I-024 — coverage-aware gate closes the Task-1 vacuous-True gap
# ---------------------------------------------------------------------------


class TestGateCoverageAwareness:
    @pytest.mark.asyncio
    async def test_gate_blocks_judge_only_criterion_as_uncovered(self) -> None:
        """REQ-006/007 / scenario 2 end-to-end: a judge alone can never satisfy the gate."""
        criterion = AcceptanceCriterion(
            id="c1", description="code reads cleanly", kind="judge"
        )
        ledger = VerificationLedger(criteria=(criterion,))

        async def judge_pass(criterion: AcceptanceCriterion, ctx: object):
            return True, "judge: looks great"

        config = _config(
            verification_ledger=ledger,
            verifier=JudgeVerifier(judge_pass),
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

        last = events[-1]
        assert last.is_error
        assert last.data["kind"] == "guardrail_tripwire"
        unmet = last.data["details"]["unmet"]
        assert len(unmet) == 1
        assert unmet[0]["criterion_id"] == "c1"
        assert unmet[0]["reason"] == "not_verified"
        assert unmet[0]["evidence"] == ""

    @pytest.mark.asyncio
    async def test_gate_allows_finalize_when_code_criterion_passes(self) -> None:
        criterion = AcceptanceCriterion(
            id="c1", description="all tests pass", kind="code", check_ref="tests"
        )
        ledger = VerificationLedger(criteria=(criterion,))

        async def passing_predicate(ctx: object) -> tuple[bool, str]:
            return True, "pytest: 10 passed"

        config = _config(
            verification_ledger=ledger,
            verifier=LedgerCodeVerifier({"tests": passing_predicate}),
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


# ---------------------------------------------------------------------------
# I-027 — fresh re-verify: stale FAIL from a prior attempt must never stick
# ---------------------------------------------------------------------------


class TestGateFreshReVerify:
    @pytest.mark.asyncio
    async def test_gate_ignores_stale_failing_result_and_reverifies_fresh(
        self,
    ) -> None:
        criterion = AcceptanceCriterion(
            id="c1", description="all tests pass", kind="code", check_ref="tests"
        )
        stale_fail = VerificationOutcome(
            criterion_id="c1",
            passed=False,
            advisory=False,
            evidence="OLD RUN: tests failing",
        )
        ledger = VerificationLedger(criteria=(criterion,), results=(stale_fail,))

        async def now_passing_predicate(ctx: object) -> tuple[bool, str]:
            return True, "pytest: now green"

        config = _config(
            verification_ledger=ledger,
            verifier=LedgerCodeVerifier({"tests": now_passing_predicate}),
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

        assert events[-1].is_final, (
            "a stale FAIL on config.verification_ledger.results must not block a "
            "now-passing predicate: the gate must re-verify from a fresh, "
            "criteria-only ledger (I-027)"
        )
