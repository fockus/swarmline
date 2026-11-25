"""Contract tests for RetryManagerPort.

These tests verify the Protocol contract, not any specific implementation.
Any class implementing can_retry + retry_step + resume_run should pass.
"""

from __future__ import annotations

from datetime import datetime, timezone


from swarmline.hitl.timeline_types import (
    RetryContext,
    RunTimeline,
    StepStatus,
    TimelineEvent,
)
from swarmline.hitl.hitl_protocols import RetryManagerPort


def _make_event(
    event_id: str = "evt-1",
    run_id: str = "run-1",
    step_name: str = "step-a",
    status: StepStatus = StepStatus.FAILED,
) -> TimelineEvent:
    return TimelineEvent(
        event_id=event_id,
        run_id=run_id,
        step_name=step_name,
        status=status,
        timestamp=datetime.now(timezone.utc),
    )


class _StubRetryManager:
    """Minimal valid implementation for contract testing."""

    def __init__(self, max_attempts: int = 3) -> None:
        self._max_attempts = max_attempts
        self._attempts: dict[str, dict[str, int]] = {}
        self._events: dict[str, list[TimelineEvent]] = {}

    def _add_event(self, event: TimelineEvent) -> None:
        self._events.setdefault(event.run_id, []).append(event)

    def can_retry(self, run_id: str, step_name: str) -> bool:
        attempts = self._attempts.get(run_id, {}).get(step_name, 0)
        return attempts < self._max_attempts

    def retry_step(self, run_id: str, step_name: str) -> RetryContext:
        self._attempts.setdefault(run_id, {})
        current = self._attempts[run_id].get(step_name, 0) + 1
        self._attempts[run_id][step_name] = current
        events = self._events.get(run_id, [])
        original_id = ""
        for ev in events:
            if ev.step_name == step_name:
                original_id = ev.event_id
                break
        return RetryContext(
            original_event_id=original_id,
            run_id=run_id,
            step_name=step_name,
            attempt_number=current,
            max_attempts=self._max_attempts,
            preserved_state={},
        )

    def resume_run(self, run_id: str) -> RunTimeline:
        events = self._events.get(run_id, [])
        return RunTimeline(
            run_id=run_id,
            events=tuple(events),
            current_phase=None,
            start_time=events[0].timestamp if events else datetime.now(timezone.utc),
            end_time=None,
        )


class _InvalidRetryManager:
    """Class without required methods — should NOT satisfy Protocol."""

    pass


class TestRetryManagerPortContract:
    """RetryManagerPort contract tests."""

    def test_protocol_is_runtime_checkable(self) -> None:
        impl = _StubRetryManager()
        assert isinstance(impl, RetryManagerPort)

    def test_invalid_impl_fails_isinstance(self) -> None:
        invalid = _InvalidRetryManager()
        assert not isinstance(invalid, RetryManagerPort)

    def test_can_retry_returns_bool(self) -> None:
        impl = _StubRetryManager()
        result = impl.can_retry("run-1", "step-a")
        assert isinstance(result, bool)

    def test_can_retry_true_when_attempts_available(self) -> None:
        impl = _StubRetryManager(max_attempts=3)
        assert impl.can_retry("run-1", "step-a") is True

    def test_can_retry_false_after_max_attempts(self) -> None:
        impl = _StubRetryManager(max_attempts=2)
        impl.retry_step("run-1", "step-a")
        impl.retry_step("run-1", "step-a")
        assert impl.can_retry("run-1", "step-a") is False

    def test_retry_step_returns_retry_context(self) -> None:
        impl = _StubRetryManager()
        result = impl.retry_step("run-1", "step-a")
        assert isinstance(result, RetryContext)

    def test_retry_step_increments_attempt(self) -> None:
        impl = _StubRetryManager()
        r1 = impl.retry_step("run-1", "step-a")
        r2 = impl.retry_step("run-1", "step-a")
        assert r1.attempt_number == 1
        assert r2.attempt_number == 2

    def test_retry_context_has_correct_run_id(self) -> None:
        impl = _StubRetryManager()
        result = impl.retry_step("run-42", "step-b")
        assert result.run_id == "run-42"
        assert result.step_name == "step-b"

    def test_retry_context_max_attempts_matches(self) -> None:
        impl = _StubRetryManager(max_attempts=5)
        result = impl.retry_step("run-1", "step-a")
        assert result.max_attempts == 5

    def test_resume_run_returns_run_timeline(self) -> None:
        impl = _StubRetryManager()
        event = _make_event(run_id="run-1", status=StepStatus.FAILED)
        impl._add_event(event)
        result = impl.resume_run("run-1")
        assert isinstance(result, RunTimeline)
        assert result.run_id == "run-1"

    def test_retry_context_preserved_state_is_dict(self) -> None:
        impl = _StubRetryManager()
        result = impl.retry_step("run-1", "step-a")
        assert isinstance(result.preserved_state, dict)
