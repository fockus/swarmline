"""Domain types for the kanban module (hermes semantics, minimum surface).

Recursive multi-parent board: tasks link to zero or more parents through
`TaskLink`, and every task carries one of the nine hermes statuses. A
blocked task also carries a typed `block_kind` and a `block_recurrences`
counter for escalation back to `triage` (see `KanbanStore`/tools, next
tasks in this increment).

All types are frozen dataclasses or str enums. Zero external dependencies
— stdlib only (dataclasses, enum, typing). This is the pure domain layer
of the opt-in `swarmline.kanban` module: the swarmline core does not
import it.

Deliberately excluded from this minimum (next increment, per spec):
comments and `task_runs` attempt history. `assignee` + claim/heartbeat
liveness (`claimed_at`/`last_heartbeat_at`) were added by the kanban-
unification increment (Sprint J, AGR-007) — see `KanbanAssignment` in
`store.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class KanbanStatus(str, Enum):
    """Lifecycle status of a kanban task — the nine hermes statuses."""

    TRIAGE = "triage"
    TODO = "todo"
    SCHEDULED = "scheduled"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    REVIEW = "review"
    DONE = "done"
    ARCHIVED = "archived"


class BlockKind(str, Enum):
    """Typed reason a kanban task is blocked."""

    DEPENDENCY = "dependency"
    NEEDS_INPUT = "needs_input"
    CAPABILITY = "capability"
    TRANSIENT = "transient"


@dataclass(frozen=True)
class KanbanTask:
    """Immutable kanban task — one card on the recursive board.

    Attributes:
        id: Unique task identifier.
        title: Short human-readable title.
        status: Current lifecycle status (one of the nine hermes statuses).
        parent_ids: IDs of this task's parents via the multi-parent
            `task_links` relation (empty tuple for a top-level task).
        block_kind: Typed reason this task is currently blocked, or None.
        block_recurrences: Number of times this task has re-entered
            `blocked` (used to escalate back to `triage` on repeat).
        metadata: Arbitrary key-value metadata.
        assignee: Opaque identifier (model/agent id) of whoever last claimed
            this card via `KanbanAssignment.claim_task`, or None if never
            claimed. Independent of `status` — claiming never moves it.
        claimed_at: ISO-8601 UTC timestamp of the most recent claim, or None.
        last_heartbeat_at: ISO-8601 UTC timestamp of the most recent
            liveness signal (set at claim time, bumped by
            `KanbanAssignment.heartbeat`), or None.
    """

    id: str
    title: str
    status: KanbanStatus = KanbanStatus.TODO
    parent_ids: tuple[str, ...] = ()
    block_kind: BlockKind | None = None
    block_recurrences: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    assignee: str | None = None
    claimed_at: str | None = None
    last_heartbeat_at: str | None = None


@dataclass(frozen=True)
class TaskLink:
    """One edge of the multi-parent `task_links` relation.

    Attributes:
        parent_id: ID of the parent task.
        child_id: ID of the child task.
    """

    parent_id: str
    child_id: str


@dataclass(frozen=True)
class KanbanNote:
    """One entry in a card's FIFO-capped progress journal (`KanbanNotes.append_note`).

    Long-task-kanban-continuation increment (Sprint 1a, AGR-012/AGR-017,
    REQ-LTK-014): a worker resuming a previously-attempted card reads
    `metadata.notes` to see what earlier attempts already tried, instead of
    repeating dead ends.

    Attributes:
        kind: `"attempt"` for a run's terminal outcome, `"progress"` for an
            in-run note left via the `kanban_note` tool.
        text: Human-readable note body.
        at: ISO-8601 UTC timestamp the note was recorded.
        run_id: ID of the run that recorded this note, or None.
        outcome: Free-form outcome label (e.g. `"failed"`, `"completed"`)
            for an `"attempt"` note, or None.
    """

    kind: Literal["attempt", "progress"]
    text: str
    at: str
    run_id: str | None = None
    outcome: str | None = None
