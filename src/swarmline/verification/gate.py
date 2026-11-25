"""Opt-in verify-before-done gate -- the finalize-time enforcement of a ledger.

verify-before-done spec, Task 4 (REQ-004, REQ-005, REQ-008, REQ-009, REQ-010). This is
the gate WIRING promised by Task 1/2/3's docstrings and CARRY-FORWARD notes: the ONLY
place that decides whether a finalize attempt may proceed to "done". Consumed exclusively
by ``runtime/thin/finalization.py`` (infrastructure) -- this module never imports it back.

Application layer: depends only on domain (``swarmline.types``, ``swarmline.domain_types``)
and stdlib. ``swarmline.runtime.types.RuntimeConfig`` is imported TYPE_CHECKING-only
(mirrors ``swarmline.types.KernelContext.config`` and this package's own
``verifiers.py``/``AcceptanceCriterion`` pattern) so this module never pulls in
runtime/infra at import time.

Two HIGH carry-forwards this module closes:

I-024 (coverage-aware gate): ``VerificationLedger.gate_passed`` alone is VACUOUSLY True
for a criterion that received only advisory (judge) results, or no result at all -- by
design, see that property's docstring. A criterion is only SATISFIED here if it has >=1
NON-advisory result and none of its non-advisory results failed. This is what makes
REQ-007 scenario 2 airtight end-to-end: a judge-only criterion is UNCOVERED, not
"passed" -- it blocks completion with ``reason="not_verified"``. The rule itself
(fix-cycle 2, GPT-5.5 external review r1, I-024 coverage hole) now lives in
``swarmline.verification.coverage`` -- the SINGLE source of truth shared with
``orchestration.supervisor.finalize`` (REQ-011) -- and is merely consumed here.
This module no longer keeps a private copy.

I-027 (fresh re-verify): every gate run rebuilds a ledger from
``config.verification_ledger.criteria`` ALONE (``results=()``) before calling
``verifier.verify``. A stale FAIL recorded on a previous finalize attempt must never
stick across a block -> fix -> done re-run (Task 5's e2e scenario depends on this).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from swarmline.domain_types import RuntimeErrorData, RuntimeEvent
from swarmline.types import CheckpointFn, VerificationLedger
from swarmline.verification.coverage import unmet_criteria, unmet_report

if TYPE_CHECKING:
    from swarmline.runtime.types import RuntimeConfig


@dataclass(frozen=True)
class _GateContext:
    """The ``ctx`` a :class:`~swarmline.protocols.verification.Verifier` receives here.

    This is the verify-before-done ``ctx`` contract: ``Verifier.verify(ledger, ctx)``
    deliberately leaves ``ctx`` un-annotated as ``object`` (see ``protocols/verification.py``,
    Task 1 note) so any caller can shape it to its needs. At finalize time, predicates/judges
    that need the model's candidate output read it from ``.output``; anything else about the
    turn (model name, structured_mode, thresholds in ``.extra``, ...) is reachable via
    ``.config``.
    """

    output: str
    config: RuntimeConfig


async def _apply_verification_gate(
    config: RuntimeConfig,
    output_text: str,
    checkpoint: CheckpointFn | None,
) -> RuntimeEvent | None:
    """Run the opt-in verify-before-done gate; ``None`` means "proceed to finalize".

    REQ-008/009 (opt-in, empty=no-op): disabled unless BOTH ``config.verification_ledger``
    and ``config.verifier`` are set AND the ledger has >=1 criterion -- in every other case
    this returns ``None`` immediately and the caller's finalize path is unchanged.

    REQ-004/005: when active, every criterion is (re-)evaluated before completion may be
    reported; if any is unmet, a terminal ``guardrail_tripwire`` error event is returned
    naming every unmet criterion with its evidence, and the caller must NOT emit a final
    event.
    """
    ledger = config.verification_ledger
    verifier = config.verifier
    if ledger is None or not ledger.criteria or verifier is None:
        return None

    # I-027: NEVER reuse ledger.results from a prior finalize attempt -- always
    # re-verify a fresh, criteria-only ledger so a stale FAIL cannot stick.
    fresh_ledger = VerificationLedger(criteria=ledger.criteria)
    gate_ctx = _GateContext(output=output_text, config=config)
    verified = await verifier.verify(fresh_ledger, gate_ctx)

    # The verify call may take real time (e.g. it shells out to run tests) -- honor a
    # checkpoint/cancellation hit exactly as the rest of finalize does.
    if checkpoint is not None:
        checkpoint_event = await checkpoint()
        if checkpoint_event is not None:
            return checkpoint_event

    unmet = unmet_criteria(verified)
    if not unmet:
        return None

    return RuntimeEvent.error(
        RuntimeErrorData(
            kind="guardrail_tripwire",
            message=f"verification gate blocked completion: {len(unmet)} criteria unmet",
            details={"unmet": [unmet_report(c, verified.results) for c in unmet]},
            recoverable=False,
        )
    )
