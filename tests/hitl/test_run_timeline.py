"""Tests for InMemoryRunTimeline implementation.

TDD: tests written BEFORE implementation.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from swarmline.hitl.hitl_protocols import RunTimelinePort
from swarmline.hitl.timeline_types import StepStatus, TimelineEvent


def _make_event(
    event_id: str = "evt-1",
    run_id: str = "run-1",
    step_name: str = "step-a",
    status: StepStatus = StepStatus.PENDING,
    timestamp: datetime | None = None,
    tool_name: str | None = None,
    tool_args: dict | None = None,
    output: str | None = None,
    error: str | None = None,
    duration_ms: int | None = None,
) -> TimelineEvent:
    return TimelineEvent(
        event_id=event_id,
        run_id=run_id,
        step_name=step_name,
        status=status,
        timestamp=timestamp or datetime.now(timezone.utc),
        tool_name=tool_name,
        tool_args=tool_args,
        output=output,
        error=error,
        duration_ms=duration_ms,
    )


@pytest.fixture()
def timeline():
    from swarmline.hitl.run_timeline import InMemoryRunTimeline

    return InMemoryRunTimeline()


class TestInMemoryRunTimelineSatisfiesProtocol:
    def test_satisfies_run_timeline_port(self, timeline) -> None:
        assert isinstance(timeline, RunTimelinePort)


class TestRecordAndRetrieveEvents:
    def test_record_event_and_get_timeline(self, timeline) -> None:
        event = _make_event()
        timeline.record_event(event)
        tl = timeline.get_timeline("run-1")
        assert tl is not None
        assert len(tl.events) == 1
        assert tl.events[0].event_id == "evt-1"

    def test_multiple_events_in_order(self, timeline) -> None:
        e1 = _make_event(event_id="e1", status=StepStatus.PENDING)
        e2 = _make_event(event_id="e2", status=StepStatus.RUNNING)
        e3 = _make_event(event_id="e3", status=StepStatus.COMPLETED)
        timeline.record_event(e1)
        timeline.record_event(e2)
        timeline.record_event(e3)
        tl = timeline.get_timeline("run-1")
        assert tl is not None
        assert tuple(e.event_id for e in tl.events) == ("e1", "e2", "e3")

    def test_get_timeline_empty_run_returns_none(self, timeline) -> None:
        assert timeline.get_timeline("nonexistent") is None

    def test_timeline_start_time_is_first_event(self, timeline) -> None:
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        event = _make_event(timestamp=ts)
        timeline.record_event(event)
        tl = timeline.get_timeline("run-1")
        assert tl is not None
        assert tl.start_time == ts

    def test_timeline_end_time_none_when_not_completed(self, timeline) -> None:
        timeline.record_event(_make_event(status=StepStatus.RUNNING))
        tl = timeline.get_timeline("run-1")
        assert tl is not None
        assert tl.end_time is None

    def test_timeline_end_time_set_when_completed(self, timeline) -> None:
        ts_end = datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc)
        timeline.record_event(_make_event(event_id="e1", status=StepStatus.PENDING))
        timeline.record_event(_make_event(event_id="e2", status=StepStatus.RUNNING))
        timeline.record_event(
            _make_event(event_id="e3", status=StepStatus.COMPLETED, timestamp=ts_end)
        )
        tl = timeline.get_timeline("run-1")
        assert tl is not None
        assert tl.end_time == ts_end

    def test_timeline_end_time_set_when_failed(self, timeline) -> None:
        ts_end = datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc)
        timeline.record_event(_make_event(event_id="e1", status=StepStatus.RUNNING))
        timeline.record_event(
            _make_event(event_id="e2", status=StepStatus.FAILED, timestamp=ts_end)
        )
        tl = timeline.get_timeline("run-1")
        assert tl is not None
        assert tl.end_time == ts_end


class TestStatusTransitions:
    @pytest.mark.parametrize(
        ("from_status", "to_status"),
        [
            (StepStatus.PENDING, StepStatus.RUNNING),
            (StepStatus.RUNNING, StepStatus.COMPLETED),
            (StepStatus.RUNNING, StepStatus.FAILED),
            (StepStatus.PENDING, StepStatus.SKIPPED),
            (StepStatus.FAILED, StepStatus.RETRYING),
            (StepStatus.RETRYING, StepStatus.RUNNING),
        ],
    )
    def test_valid_transition_accepted(
        self, timeline, from_status: StepStatus, to_status: StepStatus
    ) -> None:
        timeline.record_event(
            _make_event(event_id="e1", step_name="s", status=from_status)
        )
        timeline.record_event(
            _make_event(event_id="e2", step_name="s", status=to_status)
        )
        assert timeline.get_current_status("run-1") == to_status

    @pytest.mark.parametrize(
        ("from_status", "to_status"),
        [
            (StepStatus.COMPLETED, StepStatus.RUNNING),
            (StepStatus.SKIPPED, StepStatus.RUNNING),
            (StepStatus.PENDING, StepStatus.COMPLETED),
            (StepStatus.PENDING, StepStatus.FAILED),
        ],
    )
    def test_invalid_transition_raises_value_error(
        self, timeline, from_status: StepStatus, to_status: StepStatus
    ) -> None:
        timeline.record_event(
            _make_event(event_id="e1", step_name="s", status=from_status)
        )
        with pytest.raises(ValueError, match="Invalid status transition"):
            timeline.record_event(
                _make_event(event_id="e2", step_name="s", status=to_status)
            )

    def test_first_event_any_status_accepted(self, timeline) -> None:
        timeline.record_event(_make_event(status=StepStatus.RUNNING))
        assert timeline.get_current_status("run-1") == StepStatus.RUNNING


class TestGetCurrentStatus:
    def test_returns_latest_status(self, timeline) -> None:
        timeline.record_event(_make_event(event_id="e1", status=StepStatus.PENDING))
        timeline.record_event(_make_event(event_id="e2", status=StepStatus.RUNNING))
        assert timeline.get_current_status("run-1") == StepStatus.RUNNING

    def test_returns_none_for_unknown_run(self, timeline) -> None:
        assert timeline.get_current_status("nonexistent") is None


class TestPhaseBoundary:
    def test_phase_event_sets_current_phase(self, timeline) -> None:
        timeline.record_event(
            _make_event(
                event_id="e1", step_name="phase:planning", status=StepStatus.RUNNING
            )
        )
        tl = timeline.get_timeline("run-1")
        assert tl is not None
        assert tl.current_phase == "phase:planning"

    def test_latest_phase_wins(self, timeline) -> None:
        timeline.record_event(
            _make_event(
                event_id="e1", step_name="phase:planning", status=StepStatus.COMPLETED
            )
        )
        timeline.record_event(
            _make_event(
                event_id="e2", step_name="phase:execution", status=StepStatus.RUNNING
            )
        )
        tl = timeline.get_timeline("run-1")
        assert tl is not None
        assert tl.current_phase == "phase:execution"

    def test_non_phase_event_does_not_change_phase(self, timeline) -> None:
        timeline.record_event(
            _make_event(
                event_id="e1", step_name="phase:planning", status=StepStatus.RUNNING
            )
        )
        timeline.record_event(
            _make_event(event_id="e2", step_name="tool-call", status=StepStatus.RUNNING)
        )
        tl = timeline.get_timeline("run-1")
        assert tl is not None
        assert tl.current_phase == "phase:planning"


class TestMultipleRunsIsolation:
    def test_runs_are_isolated(self, timeline) -> None:
        timeline.record_event(_make_event(event_id="e1", run_id="run-a"))
        timeline.record_event(_make_event(event_id="e2", run_id="run-b"))
        tl_a = timeline.get_timeline("run-a")
        tl_b = timeline.get_timeline("run-b")
        assert tl_a is not None and len(tl_a.events) == 1
        assert tl_b is not None and len(tl_b.events) == 1
        assert tl_a.events[0].event_id == "e1"
        assert tl_b.events[0].event_id == "e2"


class TestThreadSafety:
    def test_has_lock_attribute(self, timeline) -> None:
        import threading

        assert hasattr(timeline, "_lock")
        assert isinstance(timeline._lock, type(threading.Lock()))
