"""Contract tests for RunTimelinePort.

These tests verify the Protocol contract, not any specific implementation.
Any class implementing record_event + get_timeline + get_current_status should pass.
"""

from __future__ import annotations

from datetime import datetime, timezone


from swarmline.hitl.timeline_types import (
    RunTimeline,
    StepStatus,
    TimelineEvent,
)
from swarmline.hitl.hitl_protocols import RunTimelinePort


def _make_event(
    run_id: str = "run-1",
    step_name: str = "step-a",
    status: StepStatus = StepStatus.PENDING,
    **kwargs: object,
) -> TimelineEvent:
    return TimelineEvent(
        event_id=kwargs.get("event_id", "evt-1"),  # type: ignore[arg-type]
        run_id=run_id,
        step_name=step_name,
        status=status,
        timestamp=kwargs.get("timestamp", datetime.now(timezone.utc)),  # type: ignore[arg-type]
        tool_name=kwargs.get("tool_name"),  # type: ignore[arg-type]
        tool_args=kwargs.get("tool_args"),  # type: ignore[arg-type]
        output=kwargs.get("output"),  # type: ignore[arg-type]
        error=kwargs.get("error"),  # type: ignore[arg-type]
        duration_ms=kwargs.get("duration_ms"),  # type: ignore[arg-type]
    )


class _StubRunTimeline:
    """Minimal valid implementation for contract testing."""

    def __init__(self) -> None:
        self._events: dict[str, list[TimelineEvent]] = {}

    def record_event(self, event: TimelineEvent) -> None:
        self._events.setdefault(event.run_id, []).append(event)

    def get_timeline(self, run_id: str) -> RunTimeline | None:
        events = self._events.get(run_id)
        if not events:
            return None
        return RunTimeline(
            run_id=run_id,
            events=tuple(events),
            current_phase=None,
            start_time=events[0].timestamp,
            end_time=None,
        )

    def get_current_status(self, run_id: str) -> StepStatus | None:
        events = self._events.get(run_id)
        if not events:
            return None
        return events[-1].status


class _InvalidRunTimeline:
    """Class without required methods — should NOT satisfy Protocol."""

    pass


class TestRunTimelinePortContract:
    """RunTimelinePort contract tests."""

    def test_protocol_is_runtime_checkable(self) -> None:
        impl = _StubRunTimeline()
        assert isinstance(impl, RunTimelinePort)

    def test_invalid_impl_fails_isinstance(self) -> None:
        invalid = _InvalidRunTimeline()
        assert not isinstance(invalid, RunTimelinePort)

    def test_record_event_returns_none(self) -> None:
        impl = _StubRunTimeline()
        event = _make_event()
        result = impl.record_event(event)
        assert result is None

    def test_get_timeline_returns_run_timeline(self) -> None:
        impl = _StubRunTimeline()
        impl.record_event(_make_event(run_id="run-1"))
        result = impl.get_timeline("run-1")
        assert isinstance(result, RunTimeline)

    def test_get_timeline_unknown_run_returns_none(self) -> None:
        impl = _StubRunTimeline()
        assert impl.get_timeline("nonexistent") is None

    def test_get_timeline_events_are_tuple(self) -> None:
        impl = _StubRunTimeline()
        impl.record_event(_make_event(run_id="run-1"))
        tl = impl.get_timeline("run-1")
        assert tl is not None
        assert isinstance(tl.events, tuple)

    def test_get_current_status_returns_step_status(self) -> None:
        impl = _StubRunTimeline()
        impl.record_event(_make_event(status=StepStatus.RUNNING))
        result = impl.get_current_status("run-1")
        assert isinstance(result, StepStatus)
        assert result == StepStatus.RUNNING

    def test_get_current_status_unknown_run_returns_none(self) -> None:
        impl = _StubRunTimeline()
        assert impl.get_current_status("nonexistent") is None

    def test_timeline_preserves_event_order(self) -> None:
        impl = _StubRunTimeline()
        e1 = _make_event(event_id="evt-1", status=StepStatus.PENDING)
        e2 = _make_event(event_id="evt-2", status=StepStatus.RUNNING)
        impl.record_event(e1)
        impl.record_event(e2)
        tl = impl.get_timeline("run-1")
        assert tl is not None
        assert tl.events[0].event_id == "evt-1"
        assert tl.events[1].event_id == "evt-2"

    def test_timeline_run_id_matches(self) -> None:
        impl = _StubRunTimeline()
        impl.record_event(_make_event(run_id="run-42"))
        tl = impl.get_timeline("run-42")
        assert tl is not None
        assert tl.run_id == "run-42"
