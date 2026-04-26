"""Tests for ActivityLogSubscriber — EventBus to ActivityLog bridge."""

from __future__ import annotations

import pytest

from swarmline.observability.activity_log import InMemoryActivityLog
from swarmline.observability.activity_subscriber import ActivityLogSubscriber
from swarmline.observability.activity_types import (
    ActivityEntry,
    ActivityFilter,
    ActorType,
)
from swarmline.observability.event_bus import InMemoryEventBus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def activity_log():
    return InMemoryActivityLog()


@pytest.fixture
def event_bus():
    return InMemoryEventBus()


@pytest.fixture
def subscriber(activity_log, event_bus):
    sub = ActivityLogSubscriber(activity_log=activity_log, event_bus=event_bus)
    sub.subscribe_defaults()
    return sub


# ---------------------------------------------------------------------------
# Default topic subscriptions
# ---------------------------------------------------------------------------


class TestDefaultTopics:
    def test_subscriber_default_topics(self, activity_log, event_bus) -> None:
        """Verify all 9 default subscriptions are registered."""
        sub = ActivityLogSubscriber(activity_log=activity_log, event_bus=event_bus)
        sub.subscribe_defaults()

        expected_topics = {
            "graph.orchestrator.started",
            "graph.orchestrator.delegated",
            "graph.orchestrator.agent_completed",
            "graph.orchestrator.escalated",
            "graph.message.direct",
            "pipeline.started",
            "pipeline.phase.completed",
            "pipeline.phase.failed",
            "pipeline.budget.warning",
        }
        # InMemoryEventBus stores subscribers keyed by event_type
        registered = set(event_bus._subscribers.keys())
        assert expected_topics == registered


# ---------------------------------------------------------------------------
# Event → ActivityEntry mapping
# ---------------------------------------------------------------------------


class TestEventLogging:
    async def test_subscriber_logs_on_event_emit(
        self,
        subscriber,
        activity_log,
        event_bus,
    ) -> None:
        """Emit an event and verify activity_log receives an entry."""
        await event_bus.emit(
            "graph.orchestrator.started",
            {
                "actor_id": "orchestrator-1",
                "entity_type": "pipeline",
                "entity_id": "pipe-1",
                "run_id": "run-abc",
            },
        )

        results = await activity_log.query(ActivityFilter())
        assert len(results) == 1
        entry = results[0]
        assert entry.action == "orchestrator.started"
        assert entry.actor_type == ActorType.SYSTEM
        assert entry.entity_type == "pipeline"
        assert entry.entity_id == "pipe-1"

    async def test_subscriber_delegated_event(
        self,
        subscriber,
        activity_log,
        event_bus,
    ) -> None:
        await event_bus.emit(
            "graph.orchestrator.delegated",
            {
                "actor_id": "ceo",
                "entity_type": "task",
                "entity_id": "t-42",
                "agent_id": "dev-1",
            },
        )

        results = await activity_log.query(ActivityFilter(action="task.delegated"))
        assert len(results) == 1
        assert results[0].entity_id == "t-42"

    async def test_subscriber_budget_warning(
        self,
        subscriber,
        activity_log,
        event_bus,
    ) -> None:
        await event_bus.emit(
            "pipeline.budget.warning",
            {
                "actor_id": "budget-monitor",
                "entity_type": "pipeline",
                "entity_id": "pipe-1",
                "amount": 95.5,
            },
        )

        results = await activity_log.query(ActivityFilter(action="budget.warning"))
        assert len(results) == 1
        assert results[0].details.get("amount") == 95.5

    async def test_subscriber_multiple_events(
        self,
        subscriber,
        activity_log,
        event_bus,
    ) -> None:
        """Multiple events from different topics all get logged."""
        await event_bus.emit(
            "pipeline.started",
            {
                "entity_type": "pipeline",
                "entity_id": "p-1",
            },
        )
        await event_bus.emit(
            "pipeline.phase.completed",
            {
                "entity_type": "phase",
                "entity_id": "ph-1",
            },
        )
        await event_bus.emit(
            "pipeline.phase.failed",
            {
                "entity_type": "phase",
                "entity_id": "ph-2",
            },
        )

        count = await activity_log.count(ActivityFilter())
        assert count == 3


# ---------------------------------------------------------------------------
# Custom topic map
# ---------------------------------------------------------------------------


class TestCustomTopicMap:
    async def test_subscriber_custom_topic_map(
        self,
        activity_log,
        event_bus,
    ) -> None:
        """Custom topic mapping works instead of defaults."""

        def _map_custom(data: dict) -> ActivityEntry:
            return ActivityEntry(
                id="custom-1",
                actor_type=ActorType.USER,
                actor_id=data.get("user_id", "unknown"),
                action="custom.action",
                entity_type="widget",
                entity_id=data.get("widget_id", "w-0"),
                details=data,
            )

        custom_map = {"my.custom.topic": _map_custom}
        sub = ActivityLogSubscriber(
            activity_log=activity_log,
            event_bus=event_bus,
            topic_map=custom_map,
        )
        sub.subscribe_defaults()

        await event_bus.emit(
            "my.custom.topic",
            {
                "user_id": "user-42",
                "widget_id": "w-7",
            },
        )

        results = await activity_log.query(ActivityFilter())
        assert len(results) == 1
        entry = results[0]
        assert entry.action == "custom.action"
        assert entry.actor_type == ActorType.USER
        assert entry.entity_id == "w-7"

    async def test_custom_map_does_not_include_defaults(
        self,
        activity_log,
        event_bus,
    ) -> None:
        """When custom topic_map provided, only those topics are subscribed."""
        custom_map = {
            "my.topic": lambda d: ActivityEntry(
                id="x",
                actor_type=ActorType.SYSTEM,
                actor_id="s",
                action="x",
                entity_type="x",
                entity_id="x",
            )
        }
        sub = ActivityLogSubscriber(
            activity_log=activity_log,
            event_bus=event_bus,
            topic_map=custom_map,
        )
        sub.subscribe_defaults()

        registered = set(event_bus._subscribers.keys())
        assert "my.topic" in registered
        # Default topics should NOT be registered
        assert "graph.orchestrator.started" not in registered
