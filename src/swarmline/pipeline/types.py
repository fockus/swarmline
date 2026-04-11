"""Pipeline domain types — phases, goals, costs, budget, gate results."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PhaseStatus(str, Enum):
    """Lifecycle status of a pipeline phase."""

    PENDING = "pending"
    RUNNING = "running"
    GATE_CHECK = "gate_check"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class PipelinePhase:
    """A phase in the pipeline execution."""

    id: str
    name: str
    goal: str
    agent_filter: str | None = None  # role filter — which agents work on this
    order: int = 0
    timeout_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Goal:
    """A hierarchical goal that decomposes into sub-goals."""

    id: str
    title: str
    description: str = ""
    parent_goal_id: str | None = None
    phase_id: str | None = None
    acceptance_criteria: tuple[str, ...] = ()
    priority: int = 0  # lower = higher priority


@dataclass(frozen=True)
class CostRecord:
    """A single cost entry — one agent execution."""

    agent_id: str
    task_id: str
    phase_id: str | None = None
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    duration_seconds: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class BudgetPolicy:
    """Budget enforcement policy."""

    max_total_usd: float | None = None
    max_per_phase_usd: float | None = None
    max_per_agent_usd: float | None = None
    warn_at_percent: float = 80.0


@dataclass(frozen=True)
class GateResult:
    """Result of a quality gate check."""

    passed: bool
    gate_name: str
    details: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class PhaseResult:
    """Result of executing a single pipeline phase."""

    phase_id: str
    status: PhaseStatus
    gate_results: tuple[GateResult, ...] = ()
    duration_seconds: float = 0.0
    task_ids: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class PipelineResult:
    """Aggregate result of the entire pipeline run."""

    phases: tuple[PhaseResult, ...]
    total_duration_seconds: float = 0.0
    total_cost_usd: float = 0.0
    status: str = "completed"  # completed | failed | stopped (str for backward compat)
