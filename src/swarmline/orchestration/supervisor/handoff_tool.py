"""handoff — REQ-009/010/011 opt-in `handoff` tool on `build_supervisor`.

Kernel-wiring spec, Task 3 (I-046). Mirrors `finalize.py`'s shape exactly: a
`ToolSpec` constant + `create_<name>_tool(...) -> executor` factory pattern.
`create_handoff_tool` binds the EXISTING `handoff()` primitive (H6,
`handoff.py:52`) — built and tested there, never previously exposed as a
supervisor tool — as a SIXTH, strictly opt-in supervisor tool. No new
delegation mechanism is introduced: the executor is a thin arg-mapping layer
over `handoff(runner, agent_id=..., goal=..., stage=..., parent_task_id=...,
task_id=..., timeout=...)`.

I-041 forward-guard (REQ-012, documentation only — no code here): `handoff()`
composes only `GraphHandoffRunner.delegate` + `.wait_for_task`; it never
touches a `Mailbox`, so the I-041 "bare `Mailbox.drain` re-delivers messages"
hazard (`mailbox.py:67-75`) is NOT triggered by this module. IF a future
change broadens this scope to draining delivered messages into a live worker
loop, it MUST clear queues via `SupervisorState.drain_for` (drain + `without`
applied together, once-only), NEVER via the bare, intentionally non-clearing
`Mailbox.drain` read.

Kept import-light on purpose (I-020): `handoff.py` already lazy-imports
`DelegationRequest` inside `handoff()`, not at module level — this module
adds no module-level import on top of that, so importing `handoff_tool`
alone never eagerly pulls `swarmline.multi_agent.graph_orchestrator`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from swarmline.orchestration.supervisor.handoff import GraphHandoffRunner, handoff
from swarmline.runtime.types import ToolSpec

ToolExecutorFn = Callable[[dict[str, Any]], Awaitable[str]]

__all__ = ["HANDOFF_TOOL_SPEC", "create_handoff_tool"]

HANDOFF_TOOL_SPEC = ToolSpec(
    name="handoff",
    description=(
        "Delegate a sub-goal to another agent through the existing graph "
        "runtime (delegate + wait_for_task) — a synchronous hand-off, not a "
        "fire-and-forget spawn. Use this to route work to a SPECIFIC known "
        "agent_id in the agent graph, rather than spawning a fresh worker. "
        "Blocks until the delegated task completes (or times out)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": "ID of the agent (graph node) to hand the goal off to.",
            },
            "goal": {
                "type": "string",
                "description": "The sub-goal to delegate to that agent.",
            },
            "stage": {
                "type": "string",
                "description": "Optional stage/label recorded on the delegated task.",
            },
            "parent_task_id": {
                "type": "string",
                "description": (
                    "Optional id of the parent task this hand-off is a "
                    "subtask of, for graph task-board bookkeeping."
                ),
            },
            "task_id": {
                "type": "string",
                "description": (
                    "Optional explicit id for the delegated task. When "
                    "omitted, a fresh id is generated."
                ),
            },
            "timeout": {
                "type": "number",
                "description": (
                    "Optional max seconds to wait for the delegated task to "
                    "complete before giving up (no timeout by default)."
                ),
            },
        },
        "required": ["agent_id", "goal"],
    },
    is_local=True,
)


def create_handoff_tool(runner: GraphHandoffRunner) -> ToolExecutorFn:
    """Create the handoff executor bound to `runner`.

    Maps the tool's `args` dict onto the existing `handoff()` primitive's
    keyword arguments and awaits it. `agent_id`/`goal` are required (present
    in `HANDOFF_TOOL_SPEC.parameters["required"]`); `stage`/`parent_task_id`/
    `task_id`/`timeout` are optional and fall back to `handoff()`'s own
    defaults (`stage=""`, the rest `None`) when absent from `args`.

    `handoff()` returns the delegated task's result string, or `None` if it
    never completed (timeout, or the task never registered) — this executor
    always returns a `str`, substituting a clear "no result" message for
    `None` so callers never have to special-case a missing return value.
    """

    async def _execute(args: dict[str, Any]) -> str:
        agent_id: str = args["agent_id"]
        goal: str = args["goal"]
        stage: str = args.get("stage") or ""
        parent_task_id: str | None = args.get("parent_task_id")
        task_id: str | None = args.get("task_id")
        timeout: float | None = args.get("timeout")

        result = await handoff(
            runner,
            agent_id=agent_id,
            goal=goal,
            stage=stage,
            parent_task_id=parent_task_id,
            task_id=task_id,
            timeout=timeout,
        )
        if result is None:
            return (
                f"Handoff to '{agent_id}' produced no result (timed out or "
                "the delegated task never completed)."
            )
        return result

    return _execute
