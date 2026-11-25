"""Supervisor tools: spawn_subagent / update_plan / send_message / read_reports / finalize.

H6 supervisor-orchestrator, Task 2 (REQ-001, REQ-002, REQ-006). Mirrors the
`ToolSpec` constant + `create_<name>_tool(state, ...) -> executor` factory
pattern from `orchestration/message_tools.py` — NOT the `@tool` decorator.
Every executor is `async def (args: dict[str, Any]) -> str`.

Kept import-light on purpose (I-020): no ThinRuntime / runtime.thin import.
`SubagentSpawner` is a narrow local Protocol (2 methods) so tests can inject
a fake orchestrator without the real one's ThinRuntime import chain.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any, Protocol
from uuid import uuid4

from swarmline.orchestration.context_bridge import ContextBridgeBuilder
from swarmline.orchestration.subagent_types import SubagentResult, SubagentSpec
from swarmline.orchestration.supervisor.blackboard import PlanPatch
from swarmline.orchestration.supervisor.state import SupervisorState
from swarmline.orchestration.supervisor.types import Report
from swarmline.orchestration.types import PlanStep
from swarmline.protocols.host_adapter import AgentHandle
from swarmline.runtime.types import ToolSpec

ToolExecutorFn = Callable[[dict[str, Any]], Awaitable[str]]


class SubagentSpawner(Protocol):
    """Minimal duck-typed contract `spawn_subagent` needs from an orchestrator.

    Deliberately narrower than `ThinSubagentOrchestrator` (ISP: 2 methods) so
    tests can inject a fake without pulling in the real orchestrator's
    ThinRuntime import chain.
    """

    async def spawn(self, spec: SubagentSpec, task: str) -> str:
        """Fire-and-forget spawn; returns an agent_id."""
        ...  # pragma: no cover

    async def wait(self, agent_id: str) -> SubagentResult:
        """Block until the spawned agent finishes and return its result."""
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# spawn_subagent
# ---------------------------------------------------------------------------

SPAWN_SUBAGENT_TOOL_SPEC = ToolSpec(
    name="spawn_subagent",
    description=(
        "Spawn a worker for the given role with a task. The worker only sees "
        "its own scoped slice of the shared plan (goal + assigned steps), "
        "never the whole plan or other workers' steps."
    ),
    parameters={
        "type": "object",
        "properties": {
            "role": {"type": "string", "description": "Role/name for the new worker."},
            "task": {
                "type": "string",
                "description": "Task instruction for the worker.",
            },
            "step_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "IDs of the plan steps (from the current shared plan) this "
                    "worker owns. The worker's scoped slice is built from "
                    "exactly these steps — never the whole plan or another "
                    "worker's steps. Every id must exist in the current plan; "
                    "unknown ids are rejected."
                ),
            },
            "read_only": {
                "type": "boolean",
                "description": (
                    "REQ-010: if true, this worker performs no plan writes and "
                    "may run concurrently with other read_only workers. If "
                    "false (default), the worker's state-writing lifecycle is "
                    "serialized against every other write worker."
                ),
            },
        },
        "required": ["role", "task"],
    },
    is_local=True,
)


def _build_worker_spec(
    state: SupervisorState, handle: AgentHandle, role: str
) -> SubagentSpec:
    """Build the worker's scoped `SubagentSpec` from its (already-recorded)
    assignment. Pure read — safe inside or outside `state._write_lock` once
    `assign_steps` for `handle.id` has completed (assignments only grow).
    """
    slice_ = state.blackboard.slice_for(handle)
    bridge = ContextBridgeBuilder.from_agent_state(
        goal=slice_.goal,
        progress="",
        findings=[f"{step.id}: {step.description}" for step in slice_.steps],
        tools=[],
    )
    system_prompt = (
        f"You are the '{role}' worker spawned by the supervisor.\n\n"
        f"{ContextBridgeBuilder.format_for_prompt(bridge)}"
    )
    return SubagentSpec(name=role, system_prompt=system_prompt)


def _build_report(handle: AgentHandle, role: str, result: SubagentResult) -> Report:
    """Build the result-only `Report` for a finished worker (REQ-006)."""
    return Report(
        worker=role,
        worker_id=handle.id,
        summary=result.output,
        status=result.status.state,
    )


async def _spawn_and_wait(
    orchestrator: SubagentSpawner, spec: SubagentSpec, task: str
) -> tuple[str, SubagentResult]:
    """Fire-and-await one worker; returns `(agent_id, result)`."""
    agent_id = await orchestrator.spawn(spec, task)
    result = await orchestrator.wait(agent_id)
    return agent_id, result


def create_spawn_subagent_tool(
    state: SupervisorState, orchestrator: SubagentSpawner
) -> ToolExecutorFn:
    """Create the spawn_subagent executor bound to `state` and `orchestrator`.

    Only `.output`/`.status.state` are read into the `Report` (REQ-006).
    `step_ids` are validated against the current plan BEFORE the assignment
    is recorded (unknown ids raise `ValueError`, never a silent drop).

    REQ-010 (fix-loop cycle 2): `state._write_lock` is NEVER skipped — ALL
    mutations (`assign_steps`/`register_worker`/`add_report`) always run
    under the lock; `read_only` only controls whether the spawn/wait
    EXECUTION span is ALSO inside it (`True`: two short locked sections
    around an unlocked execution span — workers overlap, mutations still
    serialize; `False`: one lock end-to-end). Mutators are deliberately NOT
    self-locking — `asyncio.Lock` is not reentrant.
    """

    async def _execute(args: dict[str, Any]) -> str:
        role: str = args["role"]
        task: str = args["task"]
        step_ids: list[str] = list(args.get("step_ids") or [])
        read_only: bool = bool(args.get("read_only", False))

        handle = AgentHandle(id=str(uuid4()), role=role)

        known_step_ids = {step.id for step in state.blackboard.plan.steps}
        unknown_step_ids = [sid for sid in step_ids if sid not in known_step_ids]
        if unknown_step_ids:
            raise ValueError(
                f"unknown step id(s) {unknown_step_ids!r} — not present in "
                f"plan '{state.blackboard.plan.id}'"
            )

        if read_only:
            async with state._write_lock:
                state.assign_steps(handle.id, step_ids)
            spec = _build_worker_spec(state, handle, role)
            agent_id, result = await _spawn_and_wait(orchestrator, spec, task)
            async with state._write_lock:
                state.register_worker(handle)
                state.add_report(_build_report(handle, role, result))
            return f"Worker '{role}' ({agent_id}) finished with status={result.status.state}."

        async with state._write_lock:
            state.assign_steps(handle.id, step_ids)
            spec = _build_worker_spec(state, handle, role)
            agent_id, result = await _spawn_and_wait(orchestrator, spec, task)
            state.register_worker(handle)
            state.add_report(_build_report(handle, role, result))
        return (
            f"Worker '{role}' ({agent_id}) finished with status={result.status.state}."
        )

    return _execute


# ---------------------------------------------------------------------------
# update_plan
# ---------------------------------------------------------------------------

UPDATE_PLAN_TOOL_SPEC = ToolSpec(
    name="update_plan",
    description=(
        "Patch a single step of the shared plan (blackboard). Only the step "
        "matching step_id is replaced; only description/status/result are "
        "ever changed by this tool — those you omit keep their current "
        "values, and internal step fields you cannot set here (substeps, "
        "dod_criteria, dod_verified, verification_log) are always preserved "
        "untouched; other steps are untouched."
    ),
    parameters={
        "type": "object",
        "properties": {
            "step_id": {
                "type": "string",
                "description": "ID of the plan step to patch.",
            },
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed", "failed", "skipped"],
                "description": "New status for the step.",
            },
            "result": {
                "type": "string",
                "description": "Result or reason text recorded on the step.",
            },
            "description": {
                "type": "string",
                "description": "Override the step description (defaults to the current one).",
            },
        },
        "required": ["step_id"],
    },
    is_local=True,
)


def create_update_plan_tool(state: SupervisorState) -> ToolExecutorFn:
    """Create the update_plan executor bound to `state`.

    Builds a `PlanPatch` via `dataclasses.replace(current, ...)`: only
    caller-supplied fields (`description`/`status`/`result`) are overwritten,
    everything else is carried forward from `current`.

    REQ-010 (fix-loop cycle 3): the ENTIRE read-modify-write (current-step
    lookup, patch construction, `state.update_plan`) runs under
    `state._write_lock` — the read too, else a snapshot read before acquiring
    the lock would reintroduce the stale-snapshot race vs. `replan_on_blocker`.
    """

    async def _execute(args: dict[str, Any]) -> str:
        step_id: str = args["step_id"]
        async with state._write_lock:
            current = next(
                (s for s in state.blackboard.plan.steps if s.id == step_id), None
            )
            status = args.get("status") or (
                current.status if current is not None else "pending"
            )

            if current is None:
                # Unknown id: build a fresh PlanStep so update_plan raises
                # ValueError below instead of silently no-op-ing.
                description = args.get("description") or ""
                result = args.get("result")
                updated_step = PlanStep(
                    id=step_id, description=description, status=status, result=result
                )
            else:
                # Only caller-supplied fields are overwritten; the rest of
                # `current` is carried forward untouched.
                overrides: dict[str, Any] = {"status": status}
                if args.get("description"):
                    overrides["description"] = args["description"]
                if "result" in args:
                    overrides["result"] = args["result"]
                updated_step = replace(current, **overrides)

            state.update_plan(PlanPatch(step=updated_step))
            return f"Plan step '{step_id}' updated to status={status!r}."

    return _execute


# ---------------------------------------------------------------------------
# send_message
# ---------------------------------------------------------------------------

SEND_MESSAGE_TOOL_SPEC = ToolSpec(
    name="send_message",
    description=(
        "Deliver a corrective/informational message to a worker through the "
        "Mailbox (deliver/drain, REQ-009). Lets the supervisor correct a "
        "worker mid-run. `to` MUST be the worker's id, as surfaced by "
        "read_reports' 'id=' field — a role string is display-only and is "
        "never drained by the worker."
    ),
    parameters={
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "description": (
                    "Target worker id (from read_reports' 'id=' field) — not a role."
                ),
            },
            "content": {"type": "string", "description": "Message content."},
        },
        "required": ["to", "content"],
    },
    is_local=True,
)


def create_send_message_tool(state: SupervisorState) -> ToolExecutorFn:
    """Create the send_message executor bound to `state`.

    REQ-010 (fix-loop cycle 3): `state.send_message` runs under
    `state._write_lock` — it was previously unlocked and could interleave
    with `replan_on_blocker`'s locked write flow.
    """

    async def _execute(args: dict[str, Any]) -> str:
        to: str = args["to"]
        content: str = args["content"]
        async with state._write_lock:
            state.send_message(to=to, content=content)
        return f"Message queued for '{to}'."

    return _execute


# ---------------------------------------------------------------------------
# read_reports
# ---------------------------------------------------------------------------

READ_REPORTS_TOOL_SPEC = ToolSpec(
    name="read_reports",
    description=(
        "Return the worker reports collected so far — id + summary + status "
        "only (REQ-006: never a full transcript). 'id=' is the worker_id to "
        "pass as send_message's `to` — role strings are display-only and "
        "are never delivered by drain_for."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
    is_local=True,
)


def create_read_reports_tool(state: SupervisorState) -> ToolExecutorFn:
    """Create the read_reports executor bound to `state`.

    Result-only (REQ-006): reads ONLY `Report.worker`/`.worker_id`/`.summary`/
    `.status` — nothing else could leak by construction.

    Mailbox addressing fix (MAJOR-3, fix-loop cycle 2): `worker_id` is now
    surfaced per line — `send_message`'s `to`/`drain_for` are keyed by worker
    id, never the display role, so the supervisor needs the id to reach one.
    """

    async def _execute(_args: dict[str, Any]) -> str:
        reports = state.reports
        if not reports:
            return "No worker reports yet."
        lines = [
            f"- {r.worker} (id={r.worker_id}): status={r.status}, summary={r.summary}"
            for r in reports
        ]
        return "\n".join(lines)

    return _execute


# NOTE: `finalize` (FINALIZE_TOOL_SPEC / create_finalize_tool) moved to
# `finalize.py` in Task 5 (REQ-011 verify-before-done contract gate) — SRP +
# this file's 400-line ceiling. Re-imported by `kernel.py`/`__init__.py` from
# there now.
