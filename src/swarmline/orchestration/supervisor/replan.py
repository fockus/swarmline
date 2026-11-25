"""Dynamic replan (ADaPT) + planner-as-subagent (H6 supervisor-orchestrator, Task 4).

Covers REQ-008 (WHEN execution deviates, the supervisor updates the plan via
the ADaPT decompose-on-failure principle) and REQ-007 (WHERE a planner-as-
subagent is configured, planning runs in a separate subagent so the
supervisor's context isn't filled by planning).

`ADaPTKernel._decompose` (runtime.thin.kernels.adapt) is NOT reused here — it
is `KernelContext`-bound, needs a live LLM, and returns
`runtime.thin.schemas.PlanStep` (`.title`), not `orchestration.types.PlanStep`
(`.id`/`.description`/`.substeps`). The ADaPT decompose-on-failure principle
is replicated at the plan level instead: `Decomposer` is injected (DIP), and
`SupervisorState.replan_on_blocker` (state.py) applies the returned sub-steps
to the blocked step via `Blackboard.with_patch`.

`plan_via_subagent` mirrors `tools.py::create_spawn_subagent_tool`'s
spawn/wait shape exactly, and reads ONLY `SubagentResult.output` — never
`.messages` — to build the `Plan`. That is what makes REQ-007's context
isolation true by construction, the same idiom as REQ-006 (Task 2).

Kept import-light on purpose (I-020): `swarmline.runtime.thin.parsers` /
`schemas` are imported LAZILY inside `plan_via_subagent`, so importing
`orchestration.supervisor` (or this module) does not eagerly pull in
ThinRuntime.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from swarmline.orchestration.types import Plan, PlanStep

if TYPE_CHECKING:
    from swarmline.orchestration.subagent_types import SubagentSpec
    from swarmline.orchestration.supervisor.tools import SubagentSpawner
    from swarmline.orchestration.supervisor.types import Report

__all__ = ["Decomposer", "is_blocker", "plan_via_subagent"]


@runtime_checkable
class Decomposer(Protocol):
    """Decomposes one blocked `PlanStep` into ordered sub-steps (ADaPT-style).

    Injected (DIP) so `replan_on_blocker` never depends on a concrete LLM —
    tests supply a fake; a live implementation (e.g. LLM-backed) is Task 5's
    concern to wire in.
    """

    async def decompose(self, step: PlanStep) -> tuple[PlanStep, ...]:
        """Return the ordered sub-steps that replace `step`."""
        ...  # pragma: no cover


# Allow-list of `Report.status` values that count as a replan trigger.
# `"cancelled"` is deliberately excluded — it is a stop-signal, not a
# blocker (YAGNI: no replan-on-cancel path exists yet).
_BLOCKER_STATUSES = frozenset({"failed"})


def is_blocker(report: Report) -> bool:
    """True iff `report.status` is one of `_BLOCKER_STATUSES`."""
    return report.status in _BLOCKER_STATUSES


async def plan_via_subagent(
    orchestrator: SubagentSpawner, spec: SubagentSpec, task: str
) -> Plan:
    """Run planning in a subagent (REQ-007) and return the resulting `Plan`.

    Spawns+waits exactly like `create_spawn_subagent_tool`, then builds the
    `Plan` from `result.output` ONLY — `.messages` (the planner's reasoning
    transcript) is never read, so it cannot leak into the supervisor's
    context by construction.

    Raises:
      ValueError: if `result.output` does not parse as a valid plan JSON.
    """
    from swarmline.runtime.thin.parsers import parse_plan

    agent_id = await orchestrator.spawn(spec, task)
    result = await orchestrator.wait(agent_id)

    schema = parse_plan(result.output)
    if schema is None:
        msg = f"plan_via_subagent: could not parse a plan from subagent output: {result.output!r}"
        raise ValueError(msg)

    steps = [
        PlanStep(id=s.id, description=s.title, dod_criteria=tuple(s.success_criteria))
        for s in schema.steps
    ]
    return Plan(
        id=str(uuid.uuid4()),
        goal=schema.goal,
        steps=steps,
        created_at=datetime.now(tz=UTC),
    )
