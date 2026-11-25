"""Coverage-aware verification-gate rule (I-024) — single source of truth.

H6 supervisor-orchestrator, Task 5, fix-cycle 2 (GPT-5.5 external review r1,
REQ-011 gate incomplete). :attr:`swarmline.types.VerificationLedger.gate_passed`
is INTENTIONALLY vacuous — see that property's docstring — it only checks that
recorded non-advisory results did not fail, so it reports ``True`` for a
criterion with zero results, only advisory (judge) results, or no result at
all. Closing that gap is coverage WIRING, not the ledger's job (Task 4's
CARRY-FORWARD note, and this module's I-024).

This module was extracted from ``swarmline.verification.gate`` (the
``runtime/thin/finalization.py`` gate) so the SAME rule can be consumed by a
second caller — ``orchestration.supervisor.finalize`` — without either
duplicating it or one importing the other's private helpers. There is now
exactly ONE implementation of the coverage rule; ``gate.py`` imports it
instead of keeping a private copy.

Pure domain: imports ONLY ``swarmline.types`` (frozen dataclasses) + stdlib.
No ``RuntimeEvent``/``RuntimeConfig``/runtime pull — safe to import at module
level from anywhere, including the import-light supervisor package (I-020).
"""

from __future__ import annotations

from swarmline.types import AcceptanceCriterion, VerificationLedger, VerificationOutcome

__all__ = [
    "criterion_satisfied",
    "non_advisory_results",
    "unmet_criteria",
    "unmet_report",
]


def non_advisory_results(
    criterion_id: str, results: tuple[VerificationOutcome, ...]
) -> list[VerificationOutcome]:
    """The subset of *results* covering *criterion_id* that are NOT advisory."""
    return [r for r in results if r.criterion_id == criterion_id and not r.advisory]


def criterion_satisfied(
    criterion: AcceptanceCriterion, results: tuple[VerificationOutcome, ...]
) -> bool:
    """I-024: satisfied iff >=1 non-advisory result exists and none of them failed.

    A criterion with zero non-advisory results (no result at all, or only
    advisory/judge results) is UNCOVERED, never "satisfied" — this is the
    coverage check that :attr:`~swarmline.types.VerificationLedger.gate_passed`
    deliberately does not perform on its own.
    """
    covering = non_advisory_results(criterion.id, results)
    return bool(covering) and all(result.passed for result in covering)


def unmet_report(
    criterion: AcceptanceCriterion, results: tuple[VerificationOutcome, ...]
) -> dict[str, str]:
    """Build one unmet-criterion report entry for *criterion*.

    ``reason`` is ``"failed"`` when a non-advisory result exists but failed,
    or ``"not_verified"`` when there is no non-advisory result to cover it at
    all (zero results, or advisory-only).
    """
    covering = non_advisory_results(criterion.id, results)
    failed = [result for result in covering if not result.passed]
    if failed:
        return {
            "criterion_id": criterion.id,
            "description": criterion.description,
            "reason": "failed",
            "evidence": failed[0].evidence,
        }
    return {
        "criterion_id": criterion.id,
        "description": criterion.description,
        "reason": "not_verified",
        "evidence": "",
    }


def unmet_criteria(ledger: VerificationLedger) -> tuple[AcceptanceCriterion, ...]:
    """The subset of *ledger*'s criteria that fail :func:`criterion_satisfied`."""
    return tuple(
        criterion
        for criterion in ledger.criteria
        if not criterion_satisfied(criterion, ledger.results)
    )
