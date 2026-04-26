"""Unit tests for EventBus, Tracer, and TracingSubscriber."""

from __future__ import annotations

from typing import Any


from swarmline.observability.event_bus import EventBus, InMemoryEventBus
from swarmline.observability.tracer import (
    ConsoleTracer,
    NoopTracer,
    Tracer,
    TracingSubscriber,
)


# ---------------------------------------------------------------------------
# InMemoryEventBus
# ---------------------------------------------------------------------------


class TestInMemoryEventBusSubscribe:
    """subscribe() returns unique subscription IDs."""

    def test_subscribe_returns_string_id(self) -> None:
        bus = InMemoryEventBus()
        sub_id = bus.subscribe("test_event", lambda d: None)
        assert isinstance(sub_id, str)
        assert sub_id

    def test_subscribe_returns_unique_ids(self) -> None:
        bus = InMemoryEventBus()
        id1 = bus.subscribe("evt", lambda d: None)
        id2 = bus.subscribe("evt", lambda d: None)
        assert id1 != id2


class TestInMemoryEventBusEmit:
    """emit() dispatches data to subscribers."""

    async def test_emit_calls_subscriber_with_data(self) -> None:
        bus = InMemoryEventBus()
        received: list[dict[str, Any]] = []
        bus.subscribe("my_event", lambda d: received.append(d))

        await bus.emit("my_event", {"key": "value"})

        assert received == [{"key": "value"}]

    async def test_emit_with_no_subscribers_no_error(self) -> None:
        bus = InMemoryEventBus()
        # Should not raise
        await bus.emit("no_one_listens", {"x": 1})

    async def test_emit_multiple_subscribers_same_event(self) -> None:
        bus = InMemoryEventBus()
        calls: list[str] = []
        bus.subscribe("evt", lambda d: calls.append("a"))
        bus.subscribe("evt", lambda d: calls.append("b"))

        await bus.emit("evt", {})

        assert sorted(calls) == ["a", "b"]

    async def test_emit_different_event_types_isolated(self) -> None:
        bus = InMemoryEventBus()
        alpha: list[dict] = []
        beta: list[dict] = []
        bus.subscribe("alpha", lambda d: alpha.append(d))
        bus.subscribe("beta", lambda d: beta.append(d))

        await bus.emit("alpha", {"v": 1})

        assert alpha == [{"v": 1}]
        assert beta == []

    async def test_emit_supports_async_callbacks(self) -> None:
        bus = InMemoryEventBus()
        received: list[dict] = []

        async def async_cb(data: dict) -> None:
            received.append(data)

        bus.subscribe("async_evt", async_cb)
        await bus.emit("async_evt", {"ok": True})

        assert received == [{"ok": True}]

    async def test_emit_callback_error_does_not_break_others(self) -> None:
        bus = InMemoryEventBus()
        results: list[str] = []

        def bad_cb(data: dict) -> None:
            raise RuntimeError("boom")

        # Subscribe bad first, then good — good should still be called
        bus.subscribe("evt", bad_cb)
        bus.subscribe("evt", lambda d: results.append("ok"))

        await bus.emit("evt", {})

        assert results == ["ok"]

    async def test_emit_async_callback_error_does_not_break_others(self) -> None:
        bus = InMemoryEventBus()
        results: list[str] = []

        async def bad_async(data: dict) -> None:
            raise ValueError("async boom")

        bus.subscribe("evt", bad_async)
        bus.subscribe("evt", lambda d: results.append("ok"))

        await bus.emit("evt", {})

        assert results == ["ok"]


class TestInMemoryEventBusUnsubscribe:
    """unsubscribe() removes callbacks."""

    async def test_unsubscribe_removes_callback(self) -> None:
        bus = InMemoryEventBus()
        calls: list[str] = []
        sub_id = bus.subscribe("evt", lambda d: calls.append("hit"))

        bus.unsubscribe(sub_id)
        await bus.emit("evt", {})

        assert calls == []

    def test_unsubscribe_unknown_id_no_error(self) -> None:
        bus = InMemoryEventBus()
        # Should not raise
        bus.unsubscribe("nonexistent_sub_999")


# ---------------------------------------------------------------------------
# EventBus protocol compliance
# ---------------------------------------------------------------------------


class TestEventBusProtocol:
    """InMemoryEventBus satisfies EventBus protocol."""

    def test_inmemory_event_bus_is_protocol_compliant(self) -> None:
        bus = InMemoryEventBus()
        assert isinstance(bus, EventBus)


# ---------------------------------------------------------------------------
# NoopTracer
# ---------------------------------------------------------------------------


class TestNoopTracer:
    """NoopTracer does nothing but satisfies the Tracer protocol."""

    def test_start_span_returns_string(self) -> None:
        tracer = NoopTracer()
        span_id = tracer.start_span("test_span")
        assert isinstance(span_id, str)

    def test_end_span_no_error(self) -> None:
        tracer = NoopTracer()
        span_id = tracer.start_span("span")
        tracer.end_span(span_id)  # should not raise

    def test_add_event_no_error(self) -> None:
        tracer = NoopTracer()
        span_id = tracer.start_span("span")
        tracer.add_event(span_id, "some_event", {"k": "v"})  # should not raise

    def test_noop_tracer_is_protocol_compliant(self) -> None:
        assert isinstance(NoopTracer(), Tracer)


# ---------------------------------------------------------------------------
# ConsoleTracer
# ---------------------------------------------------------------------------


class TestConsoleTracer:
    """ConsoleTracer logs spans via structlog."""

    def test_start_span_returns_unique_id(self) -> None:
        tracer = ConsoleTracer()
        id1 = tracer.start_span("span_a")
        id2 = tracer.start_span("span_b")
        assert isinstance(id1, str)
        assert id1 != id2

    def test_end_span_no_error(self) -> None:
        tracer = ConsoleTracer()
        sid = tracer.start_span("s")
        tracer.end_span(sid)

    def test_add_event_no_error(self) -> None:
        tracer = ConsoleTracer()
        sid = tracer.start_span("s")
        tracer.add_event(sid, "ev", {"detail": 42})

    def test_console_tracer_is_protocol_compliant(self) -> None:
        assert isinstance(ConsoleTracer(), Tracer)


# ---------------------------------------------------------------------------
# Tracer protocol compliance
# ---------------------------------------------------------------------------


class TestTracerProtocol:
    """Tracer protocol compliance checks."""

    def test_tracer_protocol_is_runtime_checkable(self) -> None:
        assert isinstance(NoopTracer(), Tracer)
        assert isinstance(ConsoleTracer(), Tracer)


# ---------------------------------------------------------------------------
# RuntimeConfig integration — event_bus / tracer fields
# ---------------------------------------------------------------------------


class TestRuntimeConfigEventBusFields:
    """RuntimeConfig accepts event_bus and tracer fields."""

    def test_runtime_config_default_event_bus_none(self) -> None:
        from swarmline.runtime.types import RuntimeConfig

        cfg = RuntimeConfig(runtime_name="thin")
        assert cfg.event_bus is None
        assert cfg.tracer is None

    def test_runtime_config_with_event_bus(self) -> None:
        from swarmline.runtime.types import RuntimeConfig

        bus = InMemoryEventBus()
        tracer = NoopTracer()
        cfg = RuntimeConfig(runtime_name="thin", event_bus=bus, tracer=tracer)
        assert cfg.event_bus is bus
        assert cfg.tracer is tracer


# ---------------------------------------------------------------------------
# TracingSubscriber
# ---------------------------------------------------------------------------


class TestTracingSubscriber:
    """TracingSubscriber bridges EventBus events to Tracer spans."""

    async def test_tracing_subscriber_creates_span_on_llm_call(self) -> None:
        bus = InMemoryEventBus()
        tracer = ConsoleTracer()
        subscriber = TracingSubscriber(bus, tracer)
        subscriber.attach()

        await bus.emit("llm_call_start", {"model": "test-model"})
        await bus.emit("llm_call_end", {"model": "test-model", "tokens": 100})

        # Verify span was created and completed (active spans cleared, completed tracked)
        assert len(tracer._spans) == 0
        assert len(tracer._completed_spans) == 1
        span = tracer._completed_spans[0]
        assert span["name"] == "llm_call"
        assert span["ended"]

    async def test_tracing_subscriber_creates_span_on_tool_call(self) -> None:
        bus = InMemoryEventBus()
        tracer = ConsoleTracer()
        subscriber = TracingSubscriber(bus, tracer)
        subscriber.attach()

        await bus.emit("tool_call_start", {"name": "search"})
        await bus.emit("tool_call_end", {"name": "search", "ok": True})

        assert len(tracer._spans) == 0
        assert len(tracer._completed_spans) == 1
        span = tracer._completed_spans[0]
        assert span["name"] == "tool_call"
        assert span["ended"]

    async def test_tracing_subscriber_handles_concurrent_spans(self) -> None:
        bus = InMemoryEventBus()
        tracer = ConsoleTracer()
        subscriber = TracingSubscriber(bus, tracer)
        subscriber.attach()

        await bus.emit("llm_call_start", {"model": "m1"})
        await bus.emit("tool_call_start", {"name": "t1"})
        await bus.emit("llm_call_end", {"model": "m1"})
        await bus.emit("tool_call_end", {"name": "t1"})

        assert len(tracer._spans) == 0
        assert len(tracer._completed_spans) == 2
        names = {s["name"] for s in tracer._completed_spans}
        assert names == {"llm_call", "tool_call"}
