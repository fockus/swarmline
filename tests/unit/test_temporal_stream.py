"""Unit tests for the Temporal runtime's event relay (stream.py)."""

from __future__ import annotations

from swarmline.observability.event_bus import InMemoryEventBus
from swarmline.runtime.temporal.stream import (
    RunEventPublisher,
    RunEventSubscriber,
    run_channel,
)


class TestRunEventRelay:
    async def test_publish_subscribe_roundtrip(self) -> None:
        bus = InMemoryEventBus()
        sub = RunEventSubscriber(bus, "r1")
        sub.attach()

        pub = RunEventPublisher(bus)
        await pub.publish(
            "r1",
            [
                {"id": "a", "type": "assistant_delta", "data": {"text": "hi"}},
                {"id": "b", "type": "tool_call_started", "data": {"name": "calc"}},
            ],
        )

        first = await sub.next(timeout=0.5)
        second = await sub.next(timeout=0.5)
        assert first is not None and first["id"] == "a"
        assert second is not None and second["id"] == "b"
        sub.detach()

    async def test_duplicate_ids_are_dropped(self) -> None:
        """Activity retries republish the same deterministic ids — dedup."""
        bus = InMemoryEventBus()
        sub = RunEventSubscriber(bus, "r1")
        sub.attach()

        pub = RunEventPublisher(bus)
        event = {"id": "a", "type": "assistant_delta", "data": {"text": "hi"}}
        await pub.publish("r1", [event])
        await pub.publish("r1", [event])  # retry republish

        assert await sub.next(timeout=0.5) is not None
        assert await sub.next(timeout=0.05) is None
        sub.detach()

    async def test_runs_are_isolated_by_channel(self) -> None:
        bus = InMemoryEventBus()
        sub = RunEventSubscriber(bus, "r1")
        sub.attach()

        await RunEventPublisher(bus).publish(
            "other-run", [{"id": "x", "type": "status", "data": {}}]
        )

        assert await sub.next(timeout=0.05) is None
        sub.detach()

    async def test_drain_returns_queued_events(self) -> None:
        bus = InMemoryEventBus()
        sub = RunEventSubscriber(bus, "r1")
        sub.attach()

        await RunEventPublisher(bus).publish(
            "r1",
            [
                {"id": "a", "type": "status", "data": {}},
                {"id": "b", "type": "status", "data": {}},
            ],
        )

        drained = sub.drain()
        assert [e["id"] for e in drained] == ["a", "b"]
        assert sub.drain() == []
        sub.detach()

    def test_channel_name(self) -> None:
        assert run_channel("abc") == "swarmline.temporal.run.abc"
