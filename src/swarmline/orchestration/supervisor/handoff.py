"""Handoff helper — drives the EXISTING graph runtime (REQ-003).

H6 supervisor-orchestrator, Task 5. ADR (design.md — "handoffs =
существующие графы, не переизобретать"): handoff between agents is NOT a
new primitive. `handoff()` is a THIN wrapper that constructs a
`DelegationRequest` and drives the EXISTING
`multi_agent.graph_orchestrator.DefaultGraphOrchestrator.delegate` +
`.wait_for_task` — mirrors `tools.py`'s `_spawn_and_wait` spawn/wait shape
for the analogous worker-lifecycle helper.

Kept import-light on purpose (I-020): `swarmline.multi_agent.*` — even the
bare `graph_orchestrator_types` module — eagerly pulls `runtime.thin` the
moment `swarmline/multi_agent/__init__.py` runs (that package re-exports
`agent_tool`, which chains into ThinRuntime), so `DelegationRequest` is
imported LAZILY, inside `handoff()`, never at module level.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import uuid4

if TYPE_CHECKING:
    from swarmline.multi_agent.graph_orchestrator_types import DelegationRequest

__all__ = ["GraphHandoffRunner", "handoff"]


@runtime_checkable
class GraphHandoffRunner(Protocol):
    """Minimal contract `handoff()` needs from a graph orchestrator.

    Deliberately narrower (ISP: 2 methods) than the full 5-method
    `protocols.graph_orchestrator.GraphOrchestrator` — mirrors
    `tools.py::SubagentSpawner`'s local-narrow-Protocol pattern so tests (or
    future callers) can inject the real `DefaultGraphOrchestrator`, or any
    fake satisfying just these two methods, without depending on the whole
    orchestrator surface.
    """

    async def delegate(self, request: DelegationRequest) -> None:
        """Delegate a task to an agent (creates + launches the subtask)."""
        ...  # pragma: no cover

    async def wait_for_task(
        self, task_id: str, timeout: float | None = None
    ) -> str | None:
        """Block until `task_id` completes; return its result or `None`."""
        ...  # pragma: no cover


async def handoff(
    orchestrator: GraphHandoffRunner,
    *,
    agent_id: str,
    goal: str,
    parent_task_id: str | None = None,
    task_id: str | None = None,
    stage: str = "",
    max_retries: int | None = None,
    timeout: float | None = None,
) -> str | None:
    """Hand off `goal` to `agent_id` through the EXISTING graph runtime.

    Composes exactly two calls on the EXISTING `DefaultGraphOrchestrator`
    surface: `delegate` (creates the subtask on the task board and launches
    the agent's execution) then `wait_for_task` (blocks until it finishes).
    No new handoff primitive/type is introduced — `DelegationRequest` is the
    same request type `graph_orchestrator` has always taken.

    `task_id` defaults to a fresh `uuid4()` when the caller does not need to
    address a specific id (e.g. to `wait_for_task` it separately later).

    Returns:
      The delegated task's result string, or `None` if it never completed
      (timeout, or the task never registered — see `wait_for_task`).
    """
    from swarmline.multi_agent.graph_orchestrator_types import DelegationRequest

    resolved_task_id = task_id or str(uuid4())
    request = DelegationRequest(
        task_id=resolved_task_id,
        agent_id=agent_id,
        goal=goal,
        parent_task_id=parent_task_id,
        stage=stage,
        max_retries=max_retries,
    )
    await orchestrator.delegate(request)
    return await orchestrator.wait_for_task(resolved_task_id, timeout=timeout)
