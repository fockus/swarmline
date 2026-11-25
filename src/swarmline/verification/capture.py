"""Capture a :class:`~swarmline.types.VerificationLedger` from a contract's
success criteria (REQ-002).

verify-before-done spec, Task 5 (REQ-002 — "WHEN a task or plan begins THE
SYSTEM SHALL record its acceptance criteria into the ledger"). This module
is the generic, source-agnostic capture primitive: it turns a bare
iterable of criterion strings (from a plan, a spec, a task description —
whatever contract the caller has at "start") into a fresh
:class:`~swarmline.types.VerificationLedger` with ``results=()``, ready to
be handed to :func:`~swarmline.verification.gate._apply_verification_gate`
(via ``config.verification_ledger``) later at finalize time.

Application layer: imports ONLY domain (``swarmline.types``) and stdlib —
same constraint as ``verifiers.py`` in this package. In particular this
module does NOT import ``swarmline.runtime.thin.schemas.PlanSchema``: that
type belongs to the infrastructure layer (a concrete ThinRuntime plan
format), and Clean Architecture forbids Application depending on
Infrastructure. The PlanSchema-coupled adapter that flattens a plan's
per-step ``success_criteria`` into a ledger lives at
``swarmline.runtime.thin.verification_capture.ledger_from_plan`` instead,
one layer down, where it is free to import both this primitive's domain
types AND ``PlanSchema`` (infra -> domain is allowed; infra -> app is also
allowed, just never the reverse).
"""

from __future__ import annotations

from collections.abc import Iterable

from swarmline.types import AcceptanceCriterion, VerificationLedger


def capture_ledger(
    success_criteria: Iterable[str],
    *,
    id_prefix: str = "sc",
    kind: str = "code",
) -> VerificationLedger:
    """Build a fresh, results-empty ledger from *success_criteria* strings.

    Each criterion string becomes one :class:`AcceptanceCriterion` whose
    ``id`` and ``check_ref`` are BOTH ``f"{id_prefix}-{i}"`` (``i`` = the
    0-based index in *success_criteria*) — the same value on purpose, so a
    caller-supplied predicate map for a :class:`~swarmline.verification.LedgerCodeVerifier`
    can key its predicates by that one id and resolve every captured
    criterion without a separate lookup table.

    ``kind`` defaults to ``"code"``: a captured success-criterion is only
    useful at the verify-before-done gate if it is deterministically
    checkable (REQ-006 — code checks are the PRIMARY, gate-deciding
    verifier family; ``"judge"`` criteria are advisory-only and, per the
    Task-4 coverage-aware gate, can never satisfy completion alone). A
    caller that captures genuinely judge-only criteria must opt in
    explicitly via ``kind="judge"``.

    Does not mutate anything — *success_criteria* is only iterated once,
    and the returned :class:`VerificationLedger` is a fresh frozen
    dataclass with ``results=()``.
    """
    criteria = tuple(
        AcceptanceCriterion(
            id=f"{id_prefix}-{index}",
            description=criterion,
            kind=kind,
            check_ref=f"{id_prefix}-{index}",
        )
        for index, criterion in enumerate(success_criteria)
    )
    return VerificationLedger(criteria=criteria)
