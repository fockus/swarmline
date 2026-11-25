"""InMemoryRunTimeline — event tracking with status transition validation.

Thread-safe in-memory implementation of RunTimelinePort.
"""

from __future__ import annotations

import threading

from swarmline.hitl.timeline_types import RunTimeline, StepStatus, TimelineEvent

# Valid status transitions: from_status -> set of valid to_statuses
_VALID_TRANSITIONS: dict[StepStatus, frozenset[StepStatus]] = {
    StepStatus.PENDING: frozenset({StepStatus.RUNNING, StepStatus.SKIPPED}),
    StepStatus.RUNNING: frozenset({StepStatus.COMPLETED, StepStatus.FAILED}),
    StepStatus.FAILED: frozenset({StepStatus.RETRYING}),
    StepStatus.RETRYING: frozenset({StepStatus.RUNNING}),
    StepStatus.COMPLETED: frozenset(),
    StepStatus.SKIPPED: frozenset(),
}

_TERMINAL_STATUSES: frozenset[StepStatus] = frozenset(
    {StepStatus.COMPLETED, StepStatus.FAILED}
)


class InMemoryRunTimeline:
    """In-memory run timeline with status transition validation."""

    def __init__(self) -> None:
        self._events: dict[str, list[TimelineEvent]] = {}
        self._step_status: dict[str, dict[str, StepStatus]] = {}
        self._lock = threading.Lock()

    def record_event(self, event: TimelineEvent) -> None:
        """Record a timeline event, validating status transition."""
        with self._lock:
            run_id = event.run_id
            step_name = event.step_name

            step_statuses = self._step_status.get(run_id, {})
            current_status = step_statuses.get(step_name)

            if current_status is not None:
                valid_next = _VALID_TRANSITIONS.get(current_status, frozenset())
                if event.status not in valid_next:
                    msg = (
                        f"Invalid status transition for step '{step_name}': "
                        f"{current_status.value} -> {event.status.value}"
                    )
                    raise ValueError(msg)

            self._events.setdefault(run_id, []).append(event)
            self._step_status.setdefault(run_id, {})[step_name] = event.status

    def get_timeline(self, run_id: str) -> RunTimeline | None:
        """Build RunTimeline from stored events."""
        with self._lock:
            events = self._events.get(run_id)
            if not events:
                return None

            current_phase: str | None = None
            for ev in events:
                if ev.step_name.startswith("phase:"):
                    current_phase = ev.step_name

            last_event = events[-1]
            end_time = (
                last_event.timestamp
                if last_event.status in _TERMINAL_STATUSES
                else None
            )

            return RunTimeline(
                run_id=run_id,
                events=tuple(events),
                current_phase=current_phase,
                start_time=events[0].timestamp,
                end_time=end_time,
            )

    def get_current_status(self, run_id: str) -> StepStatus | None:
        """Return status of the latest event for run_id."""
        with self._lock:
            events = self._events.get(run_id)
            if not events:
                return None
            return events[-1].status
