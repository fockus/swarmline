"""Plan -> :class:`~swarmline.types.VerificationLedger` capture adapter.

verify-before-done spec, Task 5 (REQ-002 — "WHEN a task or plan begins THE
SYSTEM SHALL record its acceptance criteria into the ledger"). This module
is the ThinRuntime plan-side capture: it flattens EVERY step's
``success_criteria`` (``runtime/thin/schemas.py::PlanStep``) into one
ledger, ready to be assigned to ``RuntimeConfig.verification_ledger``
before execution so the Task-4 finalize-time gate
(``swarmline.verification.gate``) has a contract to check against.

Layering: infrastructure. ``PlanSchema``/``PlanStep`` are concrete
ThinRuntime plan types (infra), so this adapter cannot live in the
app-layer ``swarmline.verification`` package (which imports domain +
stdlib only — see that package's docstring). Clean Architecture allows
Infrastructure to depend on both Application and Domain, never the
reverse, so this module is free to import ``swarmline.types``
(domain) directly; it does not need to route through
``swarmline.verification.capture.capture_ledger`` because that
primitive's id scheme (``f"{id_prefix}-{i}"``, one flat sequence) does not
match the per-step, collision-resistant id scheme required here
(``f"{step.id}:sc{j}"`` — see :func:`ledger_from_plan` docstring for why).
"""

from __future__ import annotations

from swarmline.runtime.thin.schemas import PlanSchema
from swarmline.types import AcceptanceCriterion, VerificationLedger


def ledger_from_plan(plan: PlanSchema, *, kind: str = "code") -> VerificationLedger:
    """Flatten every step's ``success_criteria`` into one fresh ledger.

    Each criterion becomes one :class:`AcceptanceCriterion` with a STABLE
    id ``f"{step.id}:sc{j}"`` (``j`` = the 0-based index of the criterion
    within its OWN step, not a global counter) — using the step id as a
    namespace keeps ids stable across edits to earlier/other steps (adding
    a criterion to step 1 never renumbers step 2's criteria) and gives a
    predicate map an obvious, self-documenting key
    (``predicates["deploy-step:sc0"]``). ``id`` and ``check_ref`` are the
    SAME value, mirroring ``capture_ledger``'s convention, so a
    :class:`~swarmline.verification.LedgerCodeVerifier` predicate map can
    key directly off the criterion id.

    Collision note: id uniqueness depends on ``PlanStep.id`` being unique
    within the plan — ``PlanSchema``/``PlanStep`` (``runtime/thin/schemas.py``)
    do not currently enforce that at the schema level. A plan with two
    steps sharing the same ``id`` AND overlapping success-criteria indices
    would collide (the later step's criterion silently reuses an earlier
    id). This mirrors the pre-existing lack of a step-id-uniqueness
    validator elsewhere in the planner pipeline; flagged here rather than
    silently "fixed" by inventing an out-of-scope uniqueness contract.

    ``kind`` defaults to ``"code"`` for the same REQ-006 reason as
    :func:`~swarmline.verification.capture.capture_ledger`: a plan
    success-criterion must be deterministically checkable to satisfy the
    gate; genuinely judge-only criteria are opt-in via ``kind="judge"``.

    A plan whose steps carry no ``success_criteria`` at all captures an
    empty ledger (``criteria=()``) — the Task-4 gate treats that as a
    no-op (REQ-009), so plans that were written before this feature
    existed are unaffected.
    """
    criteria = tuple(
        AcceptanceCriterion(
            id=f"{step.id}:sc{index}",
            description=criterion,
            kind=kind,
            check_ref=f"{step.id}:sc{index}",
        )
        for step in plan.steps
        for index, criterion in enumerate(step.success_criteria)
    )
    return VerificationLedger(criteria=criteria)
