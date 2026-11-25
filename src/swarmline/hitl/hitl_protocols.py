"""HITL UX protocols — ISP-compliant ports for human-in-the-loop operations.

Each protocol has at most 5 methods. All are @runtime_checkable.
Imports only from hitl.timeline_types (pure domain).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from swarmline.hitl.timeline_types import (
    DiffDecision,
    DiffReview,
    EvidenceSurface,
    RetryContext,
    RunTimeline,
    StepStatus,
    TimelineEvent,
)


@runtime_checkable
class RunTimelinePort(Protocol):
    """Port for recording and querying run timeline events."""

    def record_event(self, event: TimelineEvent) -> None: ...

    def get_timeline(self, run_id: str) -> RunTimeline | None: ...

    def get_current_status(self, run_id: str) -> StepStatus | None: ...


@runtime_checkable
class DiffReviewPort(Protocol):
    """Port for submitting and deciding on code diff reviews."""

    def submit_diff(self, review: DiffReview) -> None: ...

    def get_review(self, diff_id: str) -> DiffReview | None: ...

    def decide(
        self, diff_id: str, decision: DiffDecision, reason: str
    ) -> DiffReview: ...


@runtime_checkable
class EvidenceSurfacePort(Protocol):
    """Port for collecting and retrieving evidence from agent runs."""

    def collect_evidence(
        self,
        run_id: str,
        *,
        test_results: tuple[str, ...] = (),
        logs: tuple[str, ...] = (),
        artifacts: tuple[str, ...] = (),
        changed_files: tuple[str, ...] = (),
        plan_state: str | None = None,
    ) -> EvidenceSurface: ...

    def get_evidence(self, run_id: str) -> EvidenceSurface | None: ...


@runtime_checkable
class RetryManagerPort(Protocol):
    """Port for managing step retries within agent runs."""

    def can_retry(self, run_id: str, step_name: str) -> bool: ...

    def retry_step(self, run_id: str, step_name: str) -> RetryContext: ...

    def resume_run(self, run_id: str) -> RunTimeline: ...
