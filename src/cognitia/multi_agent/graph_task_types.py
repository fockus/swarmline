"""Hierarchical task board types — tasks with parent-child, DoD, comments, goal ancestry."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from cognitia.multi_agent.task_types import TaskPriority, TaskStatus


@dataclass(frozen=True)
class GraphTaskItem:
    """A task in the hierarchical task board."""

    id: str
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.MEDIUM
    assignee_agent_id: str | None = None
    parent_task_id: str | None = None
    goal_id: str | None = None
    dod_criteria: tuple[str, ...] = ()
    dod_verified: bool = False
    checkout_agent_id: str | None = None  # atomic lock
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskComment:
    """A comment on a task — for inter-agent communication audit trail."""

    id: str
    task_id: str
    author_agent_id: str
    content: str
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class GoalAncestry:
    """The chain of tasks from root goal to current task."""

    root_goal_id: str
    chain: tuple[str, ...]  # task IDs from root to current (inclusive)

    @property
    def depth(self) -> int:
        return len(self.chain)
