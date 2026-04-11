"""Domain types for routine scheduling bridge.

Frozen dataclasses + str enums. Zero external dependencies.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RoutineStatus(str, Enum):
    """Lifecycle status of a registered routine."""

    ACTIVE = "active"
    PAUSED = "paused"
    REMOVED = "removed"


class RunStatus(str, Enum):
    """Outcome of a single routine trigger."""

    CREATED = "created"
    SKIPPED_DEDUP = "skipped_dedup"
    FAILED = "failed"


@dataclass(frozen=True)
class Routine:
    """A scheduled routine that auto-creates tasks on the task board.

    Attributes:
        id: Unique routine identifier.
        name: Human-readable name.
        interval_seconds: How often the routine fires.
        agent_id: Agent to assign created tasks to.
        goal_template: Title/goal for created tasks.
        dedup_key: If set, skip creation when an open task with same key exists.
        max_catchup_runs: Max missed runs to catch up on (unused in MVP).
        status: Current lifecycle status.
        metadata: Arbitrary key-value metadata.
    """

    id: str
    name: str
    interval_seconds: float
    agent_id: str
    goal_template: str
    dedup_key: str = ""
    max_catchup_runs: int = 3
    status: RoutineStatus = RoutineStatus.ACTIVE
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RoutineRun:
    """Record of a single routine trigger attempt.

    Attributes:
        routine_id: ID of the routine that fired.
        task_id: ID of the created task, or None if skipped.
        triggered_at: Wall-clock timestamp of the trigger.
        status: Outcome of the trigger.
        reason: Human-readable reason (e.g. why skipped).
    """

    routine_id: str
    task_id: str | None  # None if skipped
    triggered_at: float = field(default_factory=time.time)
    status: RunStatus = RunStatus.CREATED
    reason: str = ""
