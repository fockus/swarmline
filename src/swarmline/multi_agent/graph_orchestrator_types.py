"""Domain types for the graph orchestrator."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class OrchestratorRunState(str, Enum):
    """Lifecycle of an orchestration run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class AgentRunState(str, Enum):
    """Lifecycle of a single agent execution within a run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass(frozen=True)
class DelegationRequest:
    """Request to delegate a task to an agent."""

    task_id: str
    agent_id: str
    goal: str
    parent_task_id: str | None = None
    stage: str = ""
    max_retries: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentExecution:
    """Tracks a single agent's execution within the orchestration."""

    agent_id: str
    task_id: str
    state: AgentRunState = AgentRunState.PENDING
    result: str | None = None
    error: str | None = None
    retries: int = 0
    started_at: float | None = None
    finished_at: float | None = None


@dataclass(frozen=True)
class OrchestratorRunStatus:
    """Snapshot of a full orchestration run."""

    run_id: str
    state: OrchestratorRunState
    root_task_id: str
    root_agent_id: str
    executions: tuple[AgentExecution, ...] = ()
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    error: str | None = None

    @property
    def completed_count(self) -> int:
        return sum(1 for e in self.executions if e.state == AgentRunState.COMPLETED)

    @property
    def failed_count(self) -> int:
        return sum(1 for e in self.executions if e.state == AgentRunState.FAILED)
