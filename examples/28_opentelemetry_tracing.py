#!/usr/bin/env python3
"""Example: OpenTelemetry tracing with Cognitia EventBus.

Demonstrates how OTelExporter bridges EventBus events to OTel spans.
Uses InMemorySpanExporter to capture and print spans locally.

Requires: pip install cognitia[otel]
"""

from __future__ import annotations

import asyncio

try:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
except ImportError:
    raise SystemExit(
        "OpenTelemetry SDK is required for this example.\n"
        "Install with: pip install cognitia[otel]"
    ) from None

from cognitia.observability.event_bus import InMemoryEventBus
from cognitia.observability.otel_exporter import OTelExporter


async def main() -> None:
    # 1. Set up OTel with in-memory exporter (captures spans for inspection)
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    # 2. Create EventBus and attach OTelExporter
    bus = InMemoryEventBus()
    otel = OTelExporter(
        tracer_provider=provider,
        runtime_name="thin",
        session_id="demo-session-001",
    )
    otel.attach(bus)

    # 3. Simulate agent events
    await bus.emit("llm_call_start", {"model": "claude-sonnet-4-20250514"})
    await bus.emit("tool_call_start", {"name": "web_search", "correlation_id": "ws-1"})
    await bus.emit("tool_call_end", {"name": "web_search", "correlation_id": "ws-1"})
    await bus.emit("llm_call_end", {
        "model": "claude-sonnet-4-20250514",
        "input_tokens": 1200,
        "output_tokens": 350,
        "finish_reasons": ["stop"],
    })

    # 4. Detach and print captured spans
    otel.detach(bus)
    provider.shutdown()

    print(f"\nCaptured {len(exporter.get_finished_spans())} spans:\n")
    for span in exporter.get_finished_spans():
        print(f"  Span: {span.name}")
        print(f"    Status: {span.status.status_code.name}")
        for key, value in sorted(span.attributes.items()):
            print(f"    {key}: {value}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
