"""Domain types for task queue (Phase 9B-MVP).

All types are frozen dataclasses or str enums.
Zero external dependencies — stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    """Status of a task in the queue."""

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskPriority(str, Enum):
    """Priority level for task scheduling."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class TaskItem:
    """Immutable task entry in the queue.

    Attributes:
        id: Unique task identifier.
        title: Short human-readable title.
        description: Detailed task description.
        status: Current task status.
        priority: Task priority for scheduling.
        assignee_agent_id: Agent assigned to this task (None = unassigned).
        metadata: Arbitrary key-value metadata.
        created_at: Unix timestamp of creation.
    """

    id: str
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.MEDIUM
    assignee_agent_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0


@dataclass(frozen=True)
class TaskFilter:
    """Filter criteria for querying tasks. All fields optional.

    Attributes:
        status: Filter by task status.
        priority: Filter by priority level.
        assignee_agent_id: Filter by assigned agent.
    """

    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    assignee_agent_id: str | None = None
