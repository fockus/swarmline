"""Tests for NamespacedEventBus — pattern-matching event routing (COG-06)."""

from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock

import pytest

from swarmline.observability.event_bus import EventBus
from swarmline.observability.namespaced_event_bus import NamespacedEventBus


@pytest.fixture
def bus() -> NamespacedEventBus:
    return NamespacedEventBus()


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


class TestNamespacedEventBusProtocol:
    """NamespacedEventBus satisfies EventBus Protocol."""

    def test_isinstance_event_bus(self) -> None:
        assert isinstance(NamespacedEventBus(), EventBus)


# ---------------------------------------------------------------------------
# Exact matching
# ---------------------------------------------------------------------------


class TestExactMatching:
    """Exact 'namespace:event_type' matching."""

    @pytest.mark.asyncio
    async def test_exact_match_calls_callback(self, bus: NamespacedEventBus) -> None:
        cb = MagicMock()
        bus.subscribe("goal-a:task_completed", cb)
        await bus.emit("goal-a:task_completed", {"task_id": "t1"})
        cb.assert_called_once_with({"task_id": "t1"})

    @pytest.mark.asyncio
    async def test_exact_match_different_namespace_not_called(
        self, bus: NamespacedEventBus
    ) -> None:
        cb = MagicMock()
        bus.subscribe("goal-a:task_completed", cb)
        await bus.emit("goal-b:task_completed", {"task_id": "t1"})
        cb.assert_not_called()


# ---------------------------------------------------------------------------
# Wildcard namespace matching ("namespace:*")
# ---------------------------------------------------------------------------


class TestNamespaceWildcard:
    """Subscribe to all events in a namespace via 'namespace:*'."""

    @pytest.mark.asyncio
    async def test_namespace_wildcard_matches_any_event(
        self, bus: NamespacedEventBus
    ) -> None:
        cb = MagicMock()
        bus.subscribe("goal-a:*", cb)
        await bus.emit("goal-a:task_completed", {"x": 1})
        await bus.emit("goal-a:budget_warning", {"x": 2})
        assert cb.call_count == 2

    @pytest.mark.asyncio
    async def test_namespace_wildcard_ignores_other_namespaces(
        self, bus: NamespacedEventBus
    ) -> None:
        cb = MagicMock()
        bus.subscribe("goal-a:*", cb)
        await bus.emit("goal-b:task_completed", {"x": 1})
        cb.assert_not_called()


# ---------------------------------------------------------------------------
# Wildcard event_type matching ("*:event_type")
# ---------------------------------------------------------------------------


class TestEventTypeWildcard:
    """Subscribe to an event_type across all namespaces via '*:event_type'."""

    @pytest.mark.asyncio
    async def test_event_type_wildcard_matches_any_namespace(
        self, bus: NamespacedEventBus
    ) -> None:
        cb = MagicMock()
        bus.subscribe("*:budget_threshold", cb)
        await bus.emit("goal-a:budget_threshold", {"pct": 80})
        await bus.emit("goal-b:budget_threshold", {"pct": 90})
        assert cb.call_count == 2

    @pytest.mark.asyncio
    async def test_event_type_wildcard_ignores_other_events(
        self, bus: NamespacedEventBus
    ) -> None:
        cb = MagicMock()
        bus.subscribe("*:budget_threshold", cb)
        await bus.emit("goal-a:task_completed", {"x": 1})
        cb.assert_not_called()


# ---------------------------------------------------------------------------
# Global wildcard ("*:*")
# ---------------------------------------------------------------------------


class TestGlobalWildcard:
    """Subscribe to all namespaced events via '*:*'."""

    @pytest.mark.asyncio
    async def test_global_wildcard_matches_everything(
        self, bus: NamespacedEventBus
    ) -> None:
        cb = MagicMock()
        bus.subscribe("*:*", cb)
        await bus.emit("goal-a:task_completed", {"x": 1})
        await bus.emit("goal-b:budget_warning", {"x": 2})
        assert cb.call_count == 2


# ---------------------------------------------------------------------------
# Non-namespaced fallback
# ---------------------------------------------------------------------------


class TestNonNamespaced:
    """Plain event_type (no colon) — exact match only, no patterns."""

    @pytest.mark.asyncio
    async def test_plain_event_exact_match(self, bus: NamespacedEventBus) -> None:
        cb = MagicMock()
        bus.subscribe("task_completed", cb)
        await bus.emit("task_completed", {"x": 1})
        cb.assert_called_once_with({"x": 1})

    @pytest.mark.asyncio
    async def test_global_wildcard_does_not_match_plain_events(
        self, bus: NamespacedEventBus
    ) -> None:
        cb = MagicMock()
        bus.subscribe("*:*", cb)
        await bus.emit("task_completed", {"x": 1})
        cb.assert_not_called()


# ---------------------------------------------------------------------------
# Unsubscribe
# ---------------------------------------------------------------------------


class TestUnsubscribe:
    """Unsubscribe removes callback."""

    @pytest.mark.asyncio
    async def test_unsubscribe_exact(self, bus: NamespacedEventBus) -> None:
        cb = MagicMock()
        sub_id = bus.subscribe("goal-a:task_completed", cb)
        bus.unsubscribe(sub_id)
        await bus.emit("goal-a:task_completed", {"x": 1})
        cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_unsubscribe_pattern(self, bus: NamespacedEventBus) -> None:
        cb = MagicMock()
        sub_id = bus.subscribe("goal-a:*", cb)
        bus.unsubscribe(sub_id)
        await bus.emit("goal-a:task_completed", {"x": 1})
        cb.assert_not_called()

    def test_unsubscribe_nonexistent_is_noop(self, bus: NamespacedEventBus) -> None:
        bus.unsubscribe("nonexistent_id")  # no error


# ---------------------------------------------------------------------------
# Async + sync callbacks
# ---------------------------------------------------------------------------


class TestAsyncSyncCallbacks:
    """Both sync and async callbacks work."""

    @pytest.mark.asyncio
    async def test_async_callback(self, bus: NamespacedEventBus) -> None:
        cb = AsyncMock()
        bus.subscribe("goal-a:done", cb)
        await bus.emit("goal-a:done", {"result": "ok"})
        cb.assert_awaited_once_with({"result": "ok"})

    @pytest.mark.asyncio
    async def test_sync_callback(self, bus: NamespacedEventBus) -> None:
        cb = MagicMock()
        bus.subscribe("goal-a:done", cb)
        await bus.emit("goal-a:done", {"result": "ok"})
        cb.assert_called_once_with({"result": "ok"})


# ---------------------------------------------------------------------------
# Fire-and-forget: exception safety
# ---------------------------------------------------------------------------


class TestFireAndForget:
    """Callback exceptions do not prevent other callbacks from firing."""

    @pytest.mark.asyncio
    async def test_exception_does_not_block_others(
        self, bus: NamespacedEventBus
    ) -> None:
        def bad_cb(data: dict) -> None:
            raise RuntimeError("boom")

        good_cb = MagicMock()
        bus.subscribe("goal-a:done", bad_cb)
        bus.subscribe("goal-a:done", good_cb)
        await bus.emit("goal-a:done", {"x": 1})
        good_cb.assert_called_once_with({"x": 1})

    @pytest.mark.asyncio
    async def test_async_exception_does_not_block_others(
        self, bus: NamespacedEventBus
    ) -> None:
        async def bad_cb(data: dict) -> None:
            raise RuntimeError("async boom")

        good_cb = MagicMock()
        bus.subscribe("ns:evt", bad_cb)
        bus.subscribe("ns:evt", good_cb)
        await bus.emit("ns:evt", {"x": 1})
        good_cb.assert_called_once_with({"x": 1})


# ---------------------------------------------------------------------------
# Subscribe returns unique IDs
# ---------------------------------------------------------------------------


class TestSubscriptionIds:
    """Each subscription gets a unique ID."""

    def test_unique_ids(self, bus: NamespacedEventBus) -> None:
        id1 = bus.subscribe("a:b", MagicMock())
        id2 = bus.subscribe("a:b", MagicMock())
        id3 = bus.subscribe("*:*", MagicMock())
        assert len({id1, id2, id3}) == 3
