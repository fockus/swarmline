"""Event relay: streams RuntimeEvents from worker activities to the client.

Temporal workflows cannot stream to their caller, so activities publish
events to an EventBus channel keyed by ``run_id`` and the client facade
subscribes before starting the workflow. Any ``EventBus`` implementation
works; production needs one reachable from both workers and the client
(Redis/NATS backends in ``swarmline.observability``).

Delivery is at-least-once (activity retries republish), so every event
carries a deterministic ``id`` (``run:iteration:kind:index``) and the
subscriber deduplicates.
"""

from __future__ import annotations

import asyncio
from typing import Any

CHANNEL_PREFIX = "swarmline.temporal.run."


def run_channel(run_id: str) -> str:
    """EventBus event type for one run's stream."""
    return f"{CHANNEL_PREFIX}{run_id}"


class RunEventPublisher:
    """Worker-side publisher — used by activities when streaming is enabled."""

    def __init__(self, bus: Any) -> None:
        self._bus = bus

    async def publish(self, run_id: str, events: list[dict[str, Any]]) -> None:
        """Publish events to the run channel (best-effort)."""
        channel = run_channel(run_id)
        for event in events:
            await self._bus.emit(channel, event)


class RunEventSubscriber:
    """Client-side subscriber — feeds a queue, dedups by event id."""

    def __init__(self, bus: Any, run_id: str) -> None:
        self._bus = bus
        self._run_id = run_id
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._seen: set[str] = set()
        self._sub_id: str | None = None

    def attach(self) -> None:
        """Subscribe to the run channel."""
        self._sub_id = self._bus.subscribe(run_channel(self._run_id), self._on_event)

    def detach(self) -> None:
        """Unsubscribe from the run channel."""
        if self._sub_id is not None:
            self._bus.unsubscribe(self._sub_id)
            self._sub_id = None

    def _on_event(self, data: dict[str, Any]) -> None:
        event_id = data.get("id")
        if isinstance(event_id, str):
            if event_id in self._seen:
                return
            self._seen.add(event_id)
        self._queue.put_nowait(data)

    async def next(self, timeout: float) -> dict[str, Any] | None:
        """Next event, or None after ``timeout`` seconds of silence."""
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except TimeoutError:
            return None

    def drain(self) -> list[dict[str, Any]]:
        """All currently queued events without waiting."""
        drained: list[dict[str, Any]] = []
        while True:
            try:
                drained.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                return drained
