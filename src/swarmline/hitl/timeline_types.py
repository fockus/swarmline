"""HITL UX timeline types — pure domain, stdlib only.

Frozen dataclasses for run timelines, diff reviews, evidence surfaces, retry contexts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class StepStatus(Enum):
    """Status of a step within an agent run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


@dataclass(frozen=True)
class TimelineEvent:
    """Single event in the run timeline."""

    event_id: str
    run_id: str
    step_name: str
    status: StepStatus
    timestamp: datetime
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    output: str | None = None
    error: str | None = None
    duration_ms: int | None = None


@dataclass(frozen=True)
class RunTimeline:
    """Aggregated timeline for a single run."""

    run_id: str
    events: tuple[TimelineEvent, ...]
    current_phase: str | None
    start_time: datetime
    end_time: datetime | None = None


class DiffDecision(Enum):
    """Decision on a diff review."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


@dataclass(frozen=True)
class DiffReview:
    """Human review of a code diff produced by an agent."""

    diff_id: str
    run_id: str
    file_path: str
    diff_content: str
    decision: DiffDecision = DiffDecision.PENDING
    reason: str = ""


@dataclass(frozen=True)
class EvidenceSurface:
    """Collected evidence from an agent run for human review."""

    run_id: str
    test_results: tuple[str, ...] = ()
    logs: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    changed_files: tuple[str, ...] = ()
    plan_state: str | None = None


@dataclass(frozen=True)
class RetryContext:
    """Context for retrying a failed step."""

    original_event_id: str
    run_id: str
    step_name: str
    attempt_number: int
    max_attempts: int
    preserved_state: dict[str, Any] = field(default_factory=dict)
