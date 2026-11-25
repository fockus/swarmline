"""Hibernate/rehydrate snapshot primitives (Phase 71, observability-events Task 3).

Composes ``CostTracker.snapshot()`` + ``DefaultContextBuilder.export_saturation()``
into one serializable ``HibernateRecord`` keyed by session id, plus the id of
the currently active plan (``plan_ref``) and its step (``plan_step``).

Scope boundary: the plan itself is never serialized here - ``plan_ref`` is an
opaque id string; the caller persists/loads the actual plan via the existing
``PlanStore`` (out of scope for this module - no ``PlanStore`` import).
Wiring into ``hosting/session_registry`` and any product-level hibernate
lifecycle is the taskloom Phase 71 product-side responsibility.

Kept import-light on purpose: ``CostTracker``/``DefaultContextBuilder`` are
only imported under ``TYPE_CHECKING`` for annotations; at runtime this module
duck-types against their ``snapshot``/``restore``/``export_saturation``/
``import_saturation`` methods.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from swarmline.context.builder import DefaultContextBuilder
    from swarmline.runtime.cost import CostTracker


@dataclass(frozen=True)
class HibernateRecord:
    """Serializable snapshot of one session's cost + context-budget state.

    ``plan_ref``/``plan_step`` carry the plan's identity only - the plan
    content itself is never serialized into this record.
    """

    session_id: str
    plan_ref: str | None
    plan_step: str | None
    cost: dict[str, object]
    context_budget: dict[str, float] | None


def capture_hibernate(
    session_id: str,
    *,
    cost_tracker: CostTracker,
    context_builder: DefaultContextBuilder,
    plan_ref: str | None = None,
    plan_step: str | None = None,
) -> HibernateRecord:
    """Compose a ``HibernateRecord`` from live cost/context-builder state.

    REQ-011: composes plan reference + cost snapshot + context-budget
    snapshot + current plan step into one serializable record. The plan
    itself is not touched - the caller supplies/persists ``plan_ref`` via the
    existing ``PlanStore``.
    """
    return HibernateRecord(
        session_id=session_id,
        plan_ref=plan_ref,
        plan_step=plan_step,
        cost=cost_tracker.snapshot(),
        context_budget=context_builder.export_saturation(),
    )


def restore_hibernate(
    record: HibernateRecord,
    *,
    cost_tracker: CostTracker,
    context_builder: DefaultContextBuilder,
) -> None:
    """Mutate fresh ``cost_tracker``/``context_builder`` instances from ``record``.

    ``plan_ref``/``plan_step`` are handed back to the caller via ``record``
    itself - loading the actual plan from ``PlanStore`` is the caller's
    responsibility, not performed here.
    """
    cost_tracker.restore(record.cost)
    context_builder.import_saturation(record.context_budget)
