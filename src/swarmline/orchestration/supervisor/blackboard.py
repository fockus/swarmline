"""Blackboard — shared plan artifact with scoped worker context slices.

Implements REQ-004 (shared plan as a blackboard artifact readable/writable by the
supervisor and authorized workers) and REQ-005 (each worker gets a scoped context
consisting of its assigned plan-step slice).

Layering: this module is Application. It imports only `orchestration.types` (Plan,
PlanStep) and `protocols.host_adapter` (AgentHandle) plus stdlib — no Infrastructure,
no runtime, no LLM. Kept import-light on purpose: `orchestration/__init__.py`
eager-imports ThinRuntime (I-020), so this sub-package is intentionally NOT
re-exported from there.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Mapping

from swarmline.orchestration.types import Plan, PlanStep
from swarmline.protocols.host_adapter import AgentHandle


@dataclass(frozen=True)
class ContextSlice:
    """Scoped context handed to one worker: its goal plus assigned plan steps.

    Deliberately minimal — the supervisor's prompt is injected at spawn time
    (Task 2), not carried here.
    """

    goal: str
    steps: tuple[PlanStep, ...]


@dataclass(frozen=True)
class PlanPatch:
    """A single-step upsert/replace mutation of a Plan.

    Applied via `Plan.update_step`, which replaces the step matching `step.id`.
    No diff DSL, no multi-op batch (YAGNI) — a decomposed step carries its own
    substeps, which covers ADaPT-style replan-by-decompose (Task 4).
    """

    step: PlanStep


@dataclass(frozen=True)
class Blackboard:
    """Shared plan artifact readable/writable by the supervisor and workers.

    `assignments` maps a worker's `AgentHandle.id` to the tuple of `PlanStep.id`
    it has been assigned. Unassigned/unknown workers resolve to an empty slice —
    the full plan is never leaked (context-isolation intent, REQ-006).
    """

    plan: Plan
    assignments: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Detach and freeze `assignments` so callers can't mutate the snapshot.

        Copies the caller's mapping (external mutation of the original dict no
        longer reaches this Blackboard), normalizes values to tuples, and wraps
        the result in a read-only `MappingProxyType` (direct item assignment on
        `bb.assignments` raises `TypeError`).
        """
        frozen = MappingProxyType(
            {worker_id: tuple(ids) for worker_id, ids in self.assignments.items()}
        )
        object.__setattr__(self, "assignments", frozen)

    def slice_for(self, worker: AgentHandle) -> ContextSlice:
        """Return the scoped context slice assigned to `worker`.

        Steps are returned in plan order regardless of the order they appear
        in the assignment tuple. Each returned step is deep-copied so that a
        worker mutating its slice (e.g. `slice.steps[0].substeps.append(...)`)
        cannot corrupt the shared plan snapshot.
        """
        assigned_ids = self.assignments.get(worker.id, ())
        steps = tuple(
            copy.deepcopy(step) for step in self.plan.steps if step.id in assigned_ids
        )
        return ContextSlice(goal=self.plan.goal, steps=steps)

    def with_patch(self, patch: PlanPatch) -> Blackboard:
        """Return a NEW Blackboard with `patch.step` applied to the plan.

        `patch.step` is deep-copied before being applied so that the caller
        mutating the original step object after this call cannot alter the
        new Blackboard's snapshot.

        Raises:
          ValueError: if `patch.step.id` is not found in the plan (propagated
            from `Plan.update_step` — not swallowed).
        """
        return Blackboard(
            plan=self.plan.update_step(copy.deepcopy(patch.step)),
            assignments=self.assignments,
        )

    def with_assignment(self, worker_id: str, step_ids: Iterable[str]) -> Blackboard:
        """Return a NEW Blackboard recording that `worker_id` owns `step_ids`.

        Mirrors `with_patch`: the original Blackboard is untouched, and the
        result's `assignments` are re-frozen into a read-only `MappingProxyType`
        by `__post_init__`. Does not validate `step_ids` against the plan —
        callers (e.g. `spawn_subagent`) are expected to validate against
        `plan.steps` before calling this, so unknown ids surface as a
        tool-level error rather than silently creating a scope that can never
        resolve to any steps.
        """
        new_assignments = dict(self.assignments)
        new_assignments[worker_id] = tuple(step_ids)
        return replace(self, assignments=new_assignments)
