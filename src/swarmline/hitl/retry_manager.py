"""In-memory RetryManager — implements RetryManagerPort."""

from __future__ import annotations

from datetime import UTC, datetime

from swarmline.hitl.hitl_protocols import RunTimelinePort
from swarmline.hitl.timeline_types import RetryContext, RunTimeline, StepStatus


class InMemoryRetryManager:
    """Track retry attempts per (run_id, step_name).

    Depends on RunTimelinePort for reading timeline state (resume_run).
    """

    def __init__(
        self,
        *,
        timeline_port: RunTimelinePort,
        max_attempts: int = 3,
    ) -> None:
        self._timeline_port = timeline_port
        self._max_attempts = max_attempts
        self._attempts: dict[str, dict[str, int]] = {}

    def can_retry(self, run_id: str, step_name: str) -> bool:
        """Return True if attempt count < max_attempts."""
        attempts = self._attempts.get(run_id, {}).get(step_name, 0)
        return attempts < self._max_attempts

    def retry_step(self, run_id: str, step_name: str) -> RetryContext:
        """Create RetryContext and increment attempt counter."""
        self._attempts.setdefault(run_id, {})
        current = self._attempts[run_id].get(step_name, 0) + 1
        self._attempts[run_id][step_name] = current

        # Find original event from timeline
        original_id = ""
        timeline = self._timeline_port.get_timeline(run_id)
        if timeline is not None:
            for ev in timeline.events:
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
        """Find last COMPLETED event in timeline, return from next step."""
        timeline = self._timeline_port.get_timeline(run_id)
        if timeline is None or not timeline.events:
            return RunTimeline(
                run_id=run_id,
                events=(),
                current_phase=None,
                start_time=datetime.now(UTC),
            )

        # Find index of last COMPLETED event
        last_completed_idx = -1
        for i, ev in enumerate(timeline.events):
            if ev.status == StepStatus.COMPLETED:
                last_completed_idx = i

        # Return events from after last completed
        if last_completed_idx == -1:
            resume_events = timeline.events
        else:
            resume_events = timeline.events[last_completed_idx + 1 :]

        return RunTimeline(
            run_id=run_id,
            events=resume_events,
            current_phase=timeline.current_phase,
            start_time=timeline.start_time,
        )
