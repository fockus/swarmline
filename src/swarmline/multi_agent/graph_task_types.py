"""Hierarchical task board types — tasks with parent-child, DoD, comments, goal ancestry."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from swarmline.multi_agent.task_types import TaskPriority, TaskStatus


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
    epic_id: str | None = None
    dod_criteria: tuple[str, ...] = ()
    dod_verified: bool = False
    checkout_agent_id: str | None = None  # atomic lock
    dependencies: tuple[str, ...] = ()  # IDs of tasks that must be DONE first (DAG edges)
    delegated_by: str | None = None  # agent_id who delegated this task
    delegation_reason: str | None = None  # why it was delegated
    estimated_effort: str | None = None  # XS/S/M/L/XL
    started_at: float | None = None  # set on checkout
    completed_at: float | None = None  # set on complete
    progress: float = 0.0
    stage: str = ""
    blocked_reason: str = ""
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


@dataclass(frozen=True)
class WorkflowStage:
    """A named stage in a custom workflow, mapped to a core TaskStatus."""

    name: str
    maps_to: TaskStatus
    order: int = 0
    description: str = ""


@dataclass(frozen=True)
class WorkflowConfig:
    """Consumer-defined workflow with custom stages mapped to core statuses."""

    name: str
    stages: tuple[WorkflowStage, ...] = ()

    def stage_for(self, name: str) -> WorkflowStage | None:
        """Lookup a stage by name. Returns None if not found."""
        return next((s for s in self.stages if s.name == name), None)

    def stages_for_status(self, status: TaskStatus) -> tuple[WorkflowStage, ...]:
        """Get all stages mapped to a given TaskStatus."""
        return tuple(s for s in self.stages if s.maps_to == status)
