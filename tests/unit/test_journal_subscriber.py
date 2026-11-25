"""Tests for JournalSubscriber -- EventBus to EventJournal bridge (REQ-008/015).

Mirrors the OTelExporter / ActivityLogSubscriber attach/detach pattern:
subscribe to a set of bus topics, append every observed event into the
configured journal, unsubscribe cleanly on detach().
"""

from __future__ import annotations

from typing import Any

import pytest
from structlog.testing import capture_logs

from swarmline.observability.event_bus import InMemoryEventBus
from swarmline.observability.journal import InMemoryEventJournal
from swarmline.observability.journal_subscriber import DEFAULT_TOPICS, JournalSubscriber


class TestJournalSubscriberAttach:
    """REQ-008: bus events reach the journal via the subscriber."""

    @pytest.mark.asyncio
    async def test_bus_topics_recorded_via_subscriber(self) -> None:
        bus = InMemoryEventBus()
        journal = InMemoryEventJournal()
        subscriber = JournalSubscriber(journal)

        subscriber.attach(
            bus, topics=["graph.orchestrator.started", "pipeline.started"]
        )

        await bus.emit("graph.orchestrator.started", {"agent_id": "a1"})
        await bus.emit("pipeline.started", {"goal": "g", "phase_count": 3})
        await bus.emit("unrelated.topic", {"x": 1})  # not subscribed -> ignored

        entries = [entry async for entry in journal.read()]
        assert len(entries) == 2
        assert entries[0].event_type == "graph.orchestrator.started"
        assert entries[0].data == {"agent_id": "a1"}
        assert entries[1].event_type == "pipeline.started"
        assert entries[1].data == {"goal": "g", "phase_count": 3}

    @pytest.mark.asyncio
    async def test_attach_with_default_topics_records_graph_and_pipeline_events(
        self,
    ) -> None:
        bus = InMemoryEventBus()
        journal = InMemoryEventJournal()
        subscriber = JournalSubscriber(journal)

        subscriber.attach(bus)  # default topics

        await bus.emit("graph.orchestrator.started", {"agent_id": "a1"})
        await bus.emit("pipeline.completed", {"status": "ok"})

        entries = [entry async for entry in journal.read()]
        assert {entry.event_type for entry in entries} == {
            "graph.orchestrator.started",
            "pipeline.completed",
        }

    def test_default_topics_cover_graph_orchestrator_and_pipeline_prefixes(
        self,
    ) -> None:
        assert DEFAULT_TOPICS  # non-empty
        assert all(
            topic.startswith("graph.") or topic.startswith("pipeline.")
            for topic in DEFAULT_TOPICS
        )
        assert "graph.orchestrator.started" in DEFAULT_TOPICS
        assert "pipeline.started" in DEFAULT_TOPICS

    @pytest.mark.asyncio
    async def test_attach_default_records_pipeline_budget_threshold_exceeded(
        self,
    ) -> None:
        """Regression: pipeline.budget.threshold_exceeded (emitted by
        pipeline/budget_store.py) must be in DEFAULT_TOPICS -- previously
        missing, so a default attach() silently never recorded it (REQ-008
        coverage gap)."""
        bus = InMemoryEventBus()
        journal = InMemoryEventJournal()
        subscriber = JournalSubscriber(journal)

        subscriber.attach(bus)  # default topics, no explicit list

        payload = {
            "scope_type": "goal",
            "scope_id": "g1",
            "window": "daily",
            "usage_usd": 12.5,
            "limit_usd": 10.0,
        }
        await bus.emit("pipeline.budget.threshold_exceeded", payload)

        entries = [entry async for entry in journal.read()]
        assert len(entries) == 1
        assert entries[0].event_type == "pipeline.budget.threshold_exceeded"
        assert entries[0].data == payload

    @pytest.mark.asyncio
    async def test_every_default_topic_is_recorded_via_default_attach(self) -> None:
        """Self-verifying: emit one event per DEFAULT_TOPICS entry through a
        real bus with a default attach() and assert every single one lands in
        the journal -- guards against silent typos/omissions in the list
        (this is exactly the class of gap that let pipeline.budget.threshold_
        exceeded go missing)."""
        bus = InMemoryEventBus()
        journal = InMemoryEventJournal()
        subscriber = JournalSubscriber(journal)
        subscriber.attach(bus)

        for topic in DEFAULT_TOPICS:
            await bus.emit(topic, {"topic": topic})

        entries = [entry async for entry in journal.read()]
        recorded_topics = [entry.event_type for entry in entries]
        assert recorded_topics == list(DEFAULT_TOPICS)
        assert all(entry.data == {"topic": entry.event_type} for entry in entries)


class TestJournalSubscriberDetach:
    """detach() stops recording new events."""

    @pytest.mark.asyncio
    async def test_detach_stops_recording_new_events(self) -> None:
        bus = InMemoryEventBus()
        journal = InMemoryEventJournal()
        subscriber = JournalSubscriber(journal)
        subscriber.attach(bus, topics=["pipeline.started"])

        await bus.emit("pipeline.started", {"goal": "before-detach"})
        subscriber.detach()
        await bus.emit("pipeline.started", {"goal": "after-detach"})

        entries = [entry async for entry in journal.read()]
        assert len(entries) == 1
        assert entries[0].data == {"goal": "before-detach"}

    def test_detach_before_attach_is_a_noop(self) -> None:
        journal = InMemoryEventJournal()
        subscriber = JournalSubscriber(journal)

        subscriber.detach()  # must not raise


class TestJournalSubscriberFailureIsolation:
    """REQ-015: append failures inside the subscriber callback are isolated.

    The bus swallows callback exceptions silently (event_bus.py) -- so the
    try/except + structured log must live INSIDE the subscriber's own
    callback, not rely on the bus.
    """

    @pytest.mark.asyncio
    async def test_append_failure_logged_not_raised(self) -> None:
        class ExplodingJournal:
            async def append(self, event_type: str, data: dict[str, Any]) -> int:
                raise RuntimeError("journal backend unavailable")

            async def last_seq(self) -> int:
                return 0

        bus = InMemoryEventBus()
        subscriber = JournalSubscriber(ExplodingJournal())
        subscriber.attach(bus, topics=["pipeline.started"])

        with capture_logs() as logs:
            await bus.emit("pipeline.started", {"goal": "g"})  # must not raise

        warnings = [entry for entry in logs if entry.get("log_level") == "warning"]
        assert warnings, f"expected a structured warning log, got: {logs}"
