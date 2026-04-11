"""Unit: Redis & NATS backends — import, shape, protocol coverage.

No real Redis/NATS required — tests verify structure only.
"""

from __future__ import annotations

import inspect


# ---------------------------------------------------------------------------
# EventBus — Redis & NATS
# ---------------------------------------------------------------------------


class TestEventBusImports:

    def test_import_redis_event_bus(self) -> None:
        from swarmline.observability.event_bus_redis import RedisEventBus
        assert RedisEventBus is not None

    def test_import_nats_event_bus(self) -> None:
        from swarmline.observability.event_bus_nats import NatsEventBus
        assert NatsEventBus is not None


class TestEventBusMethods:

    def test_redis_event_bus_methods(self) -> None:
        from swarmline.observability.event_bus_redis import RedisEventBus
        required = {"subscribe", "unsubscribe", "emit", "connect", "close"}
        actual = {m for m in dir(RedisEventBus) if not m.startswith("_")}
        assert required <= actual, f"Missing: {required - actual}"

    def test_nats_event_bus_methods(self) -> None:
        from swarmline.observability.event_bus_nats import NatsEventBus
        required = {"subscribe", "unsubscribe", "emit", "connect", "close"}
        actual = {m for m in dir(NatsEventBus) if not m.startswith("_")}
        assert required <= actual, f"Missing: {required - actual}"

    def test_redis_emit_is_async(self) -> None:
        from swarmline.observability.event_bus_redis import RedisEventBus
        assert inspect.iscoroutinefunction(RedisEventBus.emit)

    def test_nats_emit_is_async(self) -> None:
        from swarmline.observability.event_bus_nats import NatsEventBus
        assert inspect.iscoroutinefunction(NatsEventBus.emit)


class TestEventBusConstructors:

    def test_redis_takes_url(self) -> None:
        from swarmline.observability.event_bus_redis import RedisEventBus
        bus = RedisEventBus(redis_url="redis://localhost:6379/0")
        assert bus is not None

    def test_nats_takes_url(self) -> None:
        from swarmline.observability.event_bus_nats import NatsEventBus
        bus = NatsEventBus(nats_url="nats://localhost:4222")
        assert bus is not None

    def test_redis_custom_prefix(self) -> None:
        from swarmline.observability.event_bus_redis import RedisEventBus
        bus = RedisEventBus(redis_url="redis://test:6379/0", channel_prefix="myapp")
        assert bus is not None

    def test_nats_custom_prefix(self) -> None:
        from swarmline.observability.event_bus_nats import NatsEventBus
        bus = NatsEventBus(nats_url="nats://test:4222", subject_prefix="myapp")
        assert bus is not None


class TestLocalDispatchWithoutConnection:
    """EventBus local dispatch works without Redis/NATS connection."""

    async def test_redis_local_subscribe_emit(self) -> None:
        from swarmline.observability.event_bus_redis import RedisEventBus
        bus = RedisEventBus(redis_url="redis://test:6379/0")
        received: list[dict] = []
        bus.subscribe("test.event", lambda d: received.append(d))
        # emit without connect — local dispatch only, no Redis publish
        await bus._dispatch_local("test.event", {"key": "val"})
        assert len(received) == 1
        assert received[0]["key"] == "val"

    async def test_nats_local_subscribe_emit(self) -> None:
        from swarmline.observability.event_bus_nats import NatsEventBus
        bus = NatsEventBus(nats_url="nats://test:4222")
        received: list[dict] = []
        bus.subscribe("test.event", lambda d: received.append(d))
        await bus._dispatch_local("test.event", {"key": "val"})
        assert len(received) == 1

    async def test_redis_unsubscribe(self) -> None:
        from swarmline.observability.event_bus_redis import RedisEventBus
        bus = RedisEventBus(redis_url="redis://test:6379/0")
        received: list[dict] = []
        sub_id = bus.subscribe("test.event", lambda d: received.append(d))
        bus.unsubscribe(sub_id)
        await bus._dispatch_local("test.event", {"key": "val"})
        assert len(received) == 0

    async def test_nats_unsubscribe(self) -> None:
        from swarmline.observability.event_bus_nats import NatsEventBus
        bus = NatsEventBus(nats_url="nats://test:4222")
        received: list[dict] = []
        sub_id = bus.subscribe("test.event", lambda d: received.append(d))
        bus.unsubscribe(sub_id)
        await bus._dispatch_local("test.event", {"key": "val"})
        assert len(received) == 0


# ---------------------------------------------------------------------------
# GraphCommunication — Redis & NATS
# ---------------------------------------------------------------------------


class TestCommImports:

    def test_import_redis_comm(self) -> None:
        from swarmline.multi_agent.graph_communication_redis import RedisGraphCommunication
        assert RedisGraphCommunication is not None

    def test_import_nats_comm(self) -> None:
        from swarmline.multi_agent.graph_communication_nats import NatsGraphCommunication
        assert NatsGraphCommunication is not None


class TestCommMethods:

    def test_redis_comm_methods(self) -> None:
        from swarmline.multi_agent.graph_communication_redis import RedisGraphCommunication
        required = {"send_direct", "broadcast_subtree", "escalate",
                     "get_inbox", "get_thread", "connect", "close"}
        actual = {m for m in dir(RedisGraphCommunication) if not m.startswith("_")}
        assert required <= actual, f"Missing: {required - actual}"

    def test_nats_comm_methods(self) -> None:
        from swarmline.multi_agent.graph_communication_nats import NatsGraphCommunication
        required = {"send_direct", "broadcast_subtree", "escalate",
                     "get_inbox", "get_thread", "connect", "close"}
        actual = {m for m in dir(NatsGraphCommunication) if not m.startswith("_")}
        assert required <= actual, f"Missing: {required - actual}"

    def test_all_async(self) -> None:
        from swarmline.multi_agent.graph_communication_nats import NatsGraphCommunication
        from swarmline.multi_agent.graph_communication_redis import RedisGraphCommunication
        for cls in [RedisGraphCommunication, NatsGraphCommunication]:
            for name, method in inspect.getmembers(cls, predicate=inspect.isfunction):
                if name.startswith("_"):
                    continue
                assert inspect.iscoroutinefunction(method), (
                    f"{cls.__name__}.{name} is not async"
                )


class TestCommConstructors:

    def test_redis_comm_params(self) -> None:
        from swarmline.multi_agent.graph_communication_redis import RedisGraphCommunication
        sig = inspect.signature(RedisGraphCommunication.__init__)
        params = list(sig.parameters.keys())
        assert "redis_url" in params
        assert "graph_query" in params
        assert "event_bus" in params

    def test_nats_comm_params(self) -> None:
        from swarmline.multi_agent.graph_communication_nats import NatsGraphCommunication
        sig = inspect.signature(NatsGraphCommunication.__init__)
        params = list(sig.parameters.keys())
        assert "nats_url" in params
        assert "graph_query" in params
        assert "event_bus" in params
