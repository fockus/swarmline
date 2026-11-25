"""SupervisorState — mutable session state holding the frozen H6 artifacts.

H6 supervisor-orchestrator, Task 2/3. Mirrors `ThinSubagentOrchestrator`'s own
`dict[str, frozen]` pattern: the container is a plain mutable class, but every
value it holds (`Blackboard`, `AgentHandle`, `Report`, `OutboxMessage`,
`Mailbox`) is a frozen dataclass. `update_plan` never mutates the current
`Blackboard` in place — it reassigns `self._blackboard` to the new immutable
snapshot returned by `Blackboard.with_patch`. `send_message`/`drain_for`
follow the same rebuild pattern against `self._mailbox` (REQ-009).

`OutboxMessage` now lives in `mailbox.py` (Task 3 relocation — see that
module's docstring for why) and is re-exported here so existing
`from swarmline.orchestration.supervisor.state import OutboxMessage` call
sites keep working unchanged.

Task 4 adds `_write_lock` (an `asyncio.Lock`, mirrors
`multi_agent/agent_registry.py`'s `self._lock = asyncio.Lock()` idiom) plus
`replan_on_blocker`, the ADaPT-style decompose-on-failure write flow
(REQ-008). The existing sync mutators (`update_plan`/`assign_steps`/etc.) are
deliberately left untouched — they never `await`, so they are already atomic
within one event-loop tick; the lock exists for ASYNC write flows that span
an `await` (REQ-010: serialize writes, let read-only workers run in
parallel).

Kept import-light on purpose (I-020): only `orchestration.types`,
`orchestration.supervisor.blackboard/mailbox/replan/types`, and
`protocols.host_adapter` — no ThinRuntime, no runtime package.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Mapping

from swarmline.orchestration.supervisor.blackboard import Blackboard, PlanPatch
from swarmline.orchestration.supervisor.mailbox import Mailbox, OutboxMessage
from swarmline.orchestration.supervisor.replan import is_blocker
from swarmline.orchestration.supervisor.types import Report

if TYPE_CHECKING:
    from swarmline.orchestration.supervisor.replan import Decomposer
    from swarmline.protocols.host_adapter import AgentHandle

__all__ = ["OutboxMessage", "SupervisorState"]


class SupervisorState:
    """Mutable supervisor session state: blackboard + workers + reports + mailbox."""

    def __init__(self, blackboard: Blackboard) -> None:
        self._blackboard = blackboard
        self._workers: dict[str, AgentHandle] = {}
        self._reports: list[Report] = []
        self._mailbox: Mailbox = Mailbox()
        # REQ-010: serializes async write flows that span an `await` (e.g.
        # `replan_on_blocker`'s `await decompose(...)`). Sync mutators below
        # (`update_plan`/`assign_steps`) never `await`, so they stay outside
        # the lock — they are already atomic within one event-loop tick.
        self._write_lock: asyncio.Lock = asyncio.Lock()

    @property
    def blackboard(self) -> Blackboard:
        """Current immutable Blackboard snapshot."""
        return self._blackboard

    @property
    def workers(self) -> Mapping[str, AgentHandle]:
        """Read-only view of registered worker handles, keyed by `AgentHandle.id`."""
        return MappingProxyType(self._workers)

    @property
    def reports(self) -> tuple[Report, ...]:
        """Read-only snapshot of all reports collected so far."""
        return tuple(self._reports)

    @property
    def outbox(self) -> tuple[OutboxMessage, ...]:
        """Read-only snapshot of ALL queued, not-yet-drained outbound messages.

        Observability/back-compat view over the mailbox (Task-2 outbox
        intent): unlike `drain_for`, reading this does NOT clear anything —
        it is a pure passthrough of `self._mailbox.messages` across every
        recipient, addressed delivery is `drain_for`'s job.
        """
        return self._mailbox.messages

    def register_worker(self, handle: AgentHandle) -> None:
        """Record a spawned worker's handle."""
        self._workers[handle.id] = handle

    def add_report(self, report: Report) -> None:
        """Append a worker report."""
        self._reports.append(report)

    def send_message(self, to: str, content: str) -> None:
        """Deliver an outbound message for `to` into the mailbox (REQ-009).

        Replaces `self._mailbox` with the NEW snapshot returned by
        `Mailbox.deliver` — the current mailbox is never mutated in place.
        """
        self._mailbox = self._mailbox.deliver(to, content)

    def drain_for(self, worker_id: str) -> tuple[OutboxMessage, ...]:
        """Return and remove `worker_id`'s queued messages — once-only delivery.

        `Mailbox` is frozen and `drain` alone is a pure read, so once-only
        semantics live here: read `worker_id`'s queue, then replace
        `self._mailbox` with the `without(worker_id)` snapshot in the same
        call. A second `drain_for(worker_id)` call returns `()` — the
        messages were consumed, not re-delivered.
        """
        msgs = self._mailbox.drain(worker_id)
        self._mailbox = self._mailbox.without(worker_id)
        return msgs

    def update_plan(self, patch: PlanPatch) -> None:
        """Apply `patch` by replacing `self._blackboard` with a NEW snapshot.

        The current Blackboard is never mutated in place — `with_patch`
        already returns a fresh, immutable instance.
        """
        self._blackboard = self._blackboard.with_patch(patch)

    def assign_steps(self, worker_id: str, step_ids: Iterable[str]) -> None:
        """Record that `worker_id` owns `step_ids`, replacing `self._blackboard`.

        Mirrors `update_plan`: the current Blackboard is never mutated in
        place — `with_assignment` already returns a fresh, immutable
        instance. Keeps callers (e.g. `spawn_subagent`) from poking the
        private `_blackboard` attribute directly.
        """
        self._blackboard = self._blackboard.with_assignment(worker_id, step_ids)

    async def replan_on_blocker(self, report: Report, decompose: Decomposer) -> bool:
        """Replan-by-decompose on a worker blocker (REQ-008, ADaPT principle).

        No-op (returns `False`, plan unchanged) unless `is_blocker(report)` —
        only `status == "failed"` triggers a replan; `"cancelled"` is a
        stop-signal, not a blocker (YAGNI). Otherwise, under `_write_lock`
        (REQ-010: this spans an `await`, so it must be serialized against any
        other async write flow): resolve the `PlanStep` the report's worker
        owns via `blackboard.assignments.get(report.worker_id, ...)` —
        `worker_id` (the assignments-key identity), NOT `worker` (the display
        role; a different string space that never matches an assignment
        key) — then `await decompose.decompose(step)` for its ordered
        sub-steps, and apply them via `PlanPatch(replace(step,
        substeps=...))`.

        If the worker owns multiple steps, only the FIRST assigned step is
        decomposed — minimal, documented choice (a worker blocked on one of
        several owned steps rarely means all of them failed; Task 5 can
        extend this to per-step tracking if a real blocker needs it).

        Returns:
          `True` if a replan was applied, `False` if this was a no-op.
        """
        if not is_blocker(report):
            return False

        async with self._write_lock:
            step_ids = self._blackboard.assignments.get(report.worker_id, ())
            if not step_ids:
                return False
            target_id = step_ids[0]
            step = next(
                (s for s in self._blackboard.plan.steps if s.id == target_id), None
            )
            if step is None:
                return False

            subs = await decompose.decompose(step)
            patch = PlanPatch(step=replace(step, substeps=list(subs)))
            self._blackboard = self._blackboard.with_patch(patch)
            return True
