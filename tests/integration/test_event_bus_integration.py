"""Integration tests for EventBus + ThinRuntime + TracingSubscriber."""

from __future__ import annotations

from typing import Any


from swarmline.observability.event_bus import InMemoryEventBus
from swarmline.observability.tracer import ConsoleTracer, TracingSubscriber
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import Message, RuntimeConfig
import pytest

pytestmark = pytest.mark.integration


def _make_echo_llm(text: str = "Hello!"):
    """Create a fake LLM call that returns a valid ActionEnvelope JSON."""
    import json

    envelope = json.dumps({"type": "final", "final_message": text})

    async def _llm_call(
        messages: list[dict[str, str]],
        system_prompt: str,
        **kwargs: Any,
    ) -> str:
        return envelope

    return _llm_call


class TestThinRuntimeWithEventBus:
    """ThinRuntime emits events to EventBus during run."""

    async def test_thin_runtime_emits_events_during_run(self) -> None:
        bus = InMemoryEventBus()
        collected: list[tuple[str, dict]] = []

        def collector(event_type: str):
            def cb(data: dict) -> None:
                collected.append((event_type, data))

            return cb

        bus.subscribe("llm_call_start", collector("llm_call_start"))
        bus.subscribe("llm_call_end", collector("llm_call_end"))

        config = RuntimeConfig(runtime_name="thin", event_bus=bus)
        rt = ThinRuntime(config=config, llm_call=_make_echo_llm("Hi"))

        events = []
        async for ev in rt.run(
            messages=[Message(role="user", content="Hello")],
            system_prompt="You are helpful.",
            active_tools=[],
        ):
            events.append(ev)

        # Should have emitted llm_call_start and llm_call_end
        event_types = [t for t, _ in collected]
        assert "llm_call_start" in event_types
        assert "llm_call_end" in event_types

    async def test_thin_runtime_without_event_bus_backward_compat(self) -> None:
        """ThinRuntime without event_bus still works normally."""
        config = RuntimeConfig(runtime_name="thin")
        rt = ThinRuntime(config=config, llm_call=_make_echo_llm("Bye"))

        events = []
        async for ev in rt.run(
            messages=[Message(role="user", content="Hello")],
            system_prompt="sys",
            active_tools=[],
        ):
            events.append(ev)

        final_events = [e for e in events if e.is_final]
        assert len(final_events) == 1
        assert "Bye" in final_events[0].data["text"]


class TestEventBusTracingSubscriberIntegration:
    """EventBus + TracingSubscriber creates spans from runtime events."""

    async def test_event_bus_with_tracing_subscriber_creates_spans(self) -> None:
        bus = InMemoryEventBus()
        tracer = ConsoleTracer()
        subscriber = TracingSubscriber(bus, tracer)
        subscriber.attach()

        config = RuntimeConfig(runtime_name="thin", event_bus=bus, tracer=tracer)
        rt = ThinRuntime(config=config, llm_call=_make_echo_llm("Traced!"))

        async for _ in rt.run(
            messages=[Message(role="user", content="Test")],
            system_prompt="sys",
            active_tools=[],
        ):
            pass

        # TracingSubscriber should have created at least one span (llm_call)
        assert len(tracer._completed_spans) >= 1
        span_names = {s["name"] for s in tracer._completed_spans}
        assert "llm_call" in span_names


class TestMultipleSubscribers:
    """Multiple subscribers receive same events."""

    async def test_multiple_subscribers_receive_same_events(self) -> None:
        bus = InMemoryEventBus()
        results_a: list[dict] = []
        results_b: list[dict] = []

        bus.subscribe("llm_call_start", lambda d: results_a.append(d))
        bus.subscribe("llm_call_start", lambda d: results_b.append(d))

        config = RuntimeConfig(runtime_name="thin", event_bus=bus)
        rt = ThinRuntime(config=config, llm_call=_make_echo_llm("Multi"))

        async for _ in rt.run(
            messages=[Message(role="user", content="Hi")],
            system_prompt="sys",
            active_tools=[],
        ):
            pass

        # Both subscribers should have received the llm_call_start event
        assert len(results_a) >= 1
        assert len(results_b) >= 1
        assert results_a == results_b
