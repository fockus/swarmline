"""Tests for InMemoryRetryManager.

TDD: these tests were written BEFORE the implementation.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from swarmline.hitl.hitl_protocols import RetryManagerPort
from swarmline.hitl.timeline_types import (
    RetryContext,
    RunTimeline,
    StepStatus,
    TimelineEvent,
)


def _make_event(
    event_id: str = "evt-1",
    run_id: str = "run-1",
    step_name: str = "step-a",
    status: StepStatus = StepStatus.COMPLETED,
) -> TimelineEvent:
    return TimelineEvent(
        event_id=event_id,
        run_id=run_id,
        step_name=step_name,
        status=status,
        timestamp=datetime.now(UTC),
    )


class _StubRunTimeline:
    """Stub RunTimelinePort for testing RetryManager."""

    def __init__(self) -> None:
        self._events: dict[str, list[TimelineEvent]] = {}

    def record_event(self, event: TimelineEvent) -> None:
        self._events.setdefault(event.run_id, []).append(event)

    def get_timeline(self, run_id: str) -> RunTimeline | None:
        events = self._events.get(run_id)
        if events is None:
            return None
        return RunTimeline(
            run_id=run_id,
            events=tuple(events),
            current_phase=None,
            start_time=events[0].timestamp,
        )

    def get_current_status(self, run_id: str) -> StepStatus | None:
        events = self._events.get(run_id)
        if not events:
            return None
        return events[-1].status


@pytest.fixture()
def timeline_port() -> _StubRunTimeline:
    return _StubRunTimeline()


@pytest.fixture()
def manager(timeline_port: _StubRunTimeline) -> RetryManagerPort:
    from swarmline.hitl.retry_manager import InMemoryRetryManager

    return InMemoryRetryManager(timeline_port=timeline_port, max_attempts=3)


class TestInMemoryRetryManager:
    """InMemoryRetryManager implementation tests."""

    def test_satisfies_protocol(self, manager: RetryManagerPort) -> None:
        assert isinstance(manager, RetryManagerPort)

    def test_can_retry_true_when_no_attempts(self, manager: RetryManagerPort) -> None:
        assert manager.can_retry("run-1", "step-a") is True

    def test_can_retry_false_after_max_attempts(
        self, manager: RetryManagerPort
    ) -> None:
        manager.retry_step("run-1", "step-a")
        manager.retry_step("run-1", "step-a")
        manager.retry_step("run-1", "step-a")
        assert manager.can_retry("run-1", "step-a") is False

    def test_can_retry_true_with_attempts_remaining(
        self, manager: RetryManagerPort
    ) -> None:
        manager.retry_step("run-1", "step-a")
        manager.retry_step("run-1", "step-a")
        assert manager.can_retry("run-1", "step-a") is True

    def test_retry_step_returns_retry_context(self, manager: RetryManagerPort) -> None:
        result = manager.retry_step("run-1", "step-a")
        assert isinstance(result, RetryContext)

    def test_retry_step_increments_attempt(self, manager: RetryManagerPort) -> None:
        r1 = manager.retry_step("run-1", "step-a")
        r2 = manager.retry_step("run-1", "step-a")
        assert r1.attempt_number == 1
        assert r2.attempt_number == 2

    def test_retry_step_has_correct_run_id_and_step(
        self, manager: RetryManagerPort
    ) -> None:
        result = manager.retry_step("run-42", "step-b")
        assert result.run_id == "run-42"
        assert result.step_name == "step-b"

    def test_retry_step_max_attempts_matches(
        self, timeline_port: _StubRunTimeline
    ) -> None:
        from swarmline.hitl.retry_manager import InMemoryRetryManager

        mgr = InMemoryRetryManager(timeline_port=timeline_port, max_attempts=5)
        result = mgr.retry_step("run-1", "step-a")
        assert result.max_attempts == 5

    def test_retry_step_finds_original_event(
        self, timeline_port: _StubRunTimeline, manager: RetryManagerPort
    ) -> None:
        event = _make_event(event_id="evt-orig", run_id="run-1", step_name="step-a")
        timeline_port.record_event(event)
        result = manager.retry_step("run-1", "step-a")
        assert result.original_event_id == "evt-orig"

    def test_retry_step_no_event_empty_original_id(
        self, manager: RetryManagerPort
    ) -> None:
        result = manager.retry_step("run-1", "step-a")
        assert result.original_event_id == ""

    def test_retry_step_preserved_state_is_dict(
        self, manager: RetryManagerPort
    ) -> None:
        result = manager.retry_step("run-1", "step-a")
        assert isinstance(result.preserved_state, dict)

    def test_resume_run_returns_timeline(
        self, timeline_port: _StubRunTimeline, manager: RetryManagerPort
    ) -> None:
        timeline_port.record_event(
            _make_event(
                event_id="e1",
                run_id="run-1",
                step_name="step-a",
                status=StepStatus.COMPLETED,
            )
        )
        timeline_port.record_event(
            _make_event(
                event_id="e2",
                run_id="run-1",
                step_name="step-b",
                status=StepStatus.FAILED,
            )
        )
        result = manager.resume_run("run-1")
        assert isinstance(result, RunTimeline)
        assert result.run_id == "run-1"

    def test_resume_run_from_last_completed(
        self, timeline_port: _StubRunTimeline, manager: RetryManagerPort
    ) -> None:
        timeline_port.record_event(
            _make_event(
                event_id="e1",
                run_id="run-1",
                step_name="step-a",
                status=StepStatus.COMPLETED,
            )
        )
        timeline_port.record_event(
            _make_event(
                event_id="e2",
                run_id="run-1",
                step_name="step-b",
                status=StepStatus.COMPLETED,
            )
        )
        timeline_port.record_event(
            _make_event(
                event_id="e3",
                run_id="run-1",
                step_name="step-c",
                status=StepStatus.FAILED,
            )
        )
        result = manager.resume_run("run-1")
        # Should contain events from after last completed (step-c onward)
        step_names = [e.step_name for e in result.events]
        assert "step-c" in step_names

    def test_resume_run_no_events_returns_empty_timeline(
        self, timeline_port: _StubRunTimeline, manager: RetryManagerPort
    ) -> None:
        result = manager.resume_run("run-1")
        assert isinstance(result, RunTimeline)
        assert result.events == ()

    def test_max_retries_exhausted(self, manager: RetryManagerPort) -> None:
        for _ in range(3):
            manager.retry_step("run-1", "step-a")
        assert manager.can_retry("run-1", "step-a") is False

    def test_different_steps_tracked_independently(
        self, manager: RetryManagerPort
    ) -> None:
        manager.retry_step("run-1", "step-a")
        manager.retry_step("run-1", "step-a")
        manager.retry_step("run-1", "step-a")
        assert manager.can_retry("run-1", "step-a") is False
        assert manager.can_retry("run-1", "step-b") is True

    def test_different_runs_tracked_independently(
        self, manager: RetryManagerPort
    ) -> None:
        for _ in range(3):
            manager.retry_step("run-1", "step-a")
        assert manager.can_retry("run-1", "step-a") is False
        assert manager.can_retry("run-2", "step-a") is True
