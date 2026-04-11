"""Event bus and tracing for runtime observability.

Demonstrates: InMemoryEventBus, NoopTracer, ConsoleTracer, TracingSubscriber.
No API keys required.
"""

import asyncio

from swarmline.observability.event_bus import InMemoryEventBus
from swarmline.observability.tracer import NoopTracer, TracingSubscriber


async def main() -> None:
    # 1. Create event bus
    bus = InMemoryEventBus()

    # 2. Subscribe to events
    events_log: list[dict] = []

    async def on_llm_call(data: dict) -> None:
        events_log.append(data)
        print(f"  [Event] llm_call_end: model={data.get('model')}, tokens={data.get('tokens')}")

    async def on_tool_call(data: dict) -> None:
        events_log.append(data)
        print(f"  [Event] tool_call_end: tool={data.get('name')}")

    sub1 = bus.subscribe("llm_call_end", on_llm_call)
    bus.subscribe("tool_call_end", on_tool_call)

    # 3. Emit events (ThinRuntime does this automatically)
    print("=== Emitting Events ===")
    await bus.emit("llm_call_end", {"model": "sonnet", "tokens": 150, "cost_usd": 0.002})
    await bus.emit("tool_call_end", {"name": "get_weather", "success": True})
    await bus.emit("llm_call_end", {"model": "sonnet", "tokens": 300, "cost_usd": 0.004})

    print(f"\nTotal events captured: {len(events_log)}")

    # 4. Unsubscribe
    bus.unsubscribe(sub1)
    await bus.emit("llm_call_end", {"model": "sonnet", "tokens": 100})
    print(f"After unsubscribe: {len(events_log)} events (unchanged)")

    # 5. TracingSubscriber -- bridge EventBus to Tracer
    print("\n=== Tracing Subscriber ===")
    tracer = NoopTracer()
    subscriber = TracingSubscriber(bus, tracer)
    subscriber.attach()
    print("TracingSubscriber attached -- events now create tracer spans")

    await bus.emit("llm_call_start", {"model": "opus", "prompt": "Hello"})
    await bus.emit("llm_call_end", {"model": "opus", "tokens": 500})

    subscriber.detach()
    print("TracingSubscriber detached")

    # 6. ConsoleTracer (requires structlog -- uncomment to try)
    # from swarmline.observability.tracer import ConsoleTracer
    # console_tracer = ConsoleTracer()
    # span_id = console_tracer.start_span("my_operation", {"key": "value"})
    # console_tracer.add_event(span_id, "checkpoint", {"step": 1})
    # console_tracer.end_span(span_id)


if __name__ == "__main__":
    asyncio.run(main())
