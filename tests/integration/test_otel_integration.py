"""Integration test: EventBus -> OTelExporter -> OpenTelemetry spans pipeline."""

from __future__ import annotations

import pytest

otel_sdk = pytest.importorskip("opentelemetry.sdk")

from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # noqa: E402
from opentelemetry.trace import StatusCode  # noqa: E402

from cognitia.observability.event_bus import InMemoryEventBus  # noqa: E402
from cognitia.observability.otel_exporter import OTelExporter  # noqa: E402
from cognitia.observability.tracer import ConsoleTracer, TracingSubscriber  # noqa: E402


@pytest.fixture()
def otel_pipeline():
    """Set up EventBus -> OTelExporter -> InMemorySpanExporter pipeline."""
    bus = InMemoryEventBus()
    span_exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(span_exporter))

    otel = OTelExporter(tracer_provider=provider)
    otel.attach(bus)

    yield bus, otel, span_exporter
    otel.detach(bus)
    provider.shutdown()


class TestFullAgentTurnLifecycle:
    """Simulate a full agent turn and verify span creation."""

    async def test_full_turn_creates_correct_spans(self, otel_pipeline: tuple) -> None:
        bus, otel, span_exporter = otel_pipeline

        # LLM call -> tool call -> second LLM call
        await bus.emit("llm_call_start", {"model": "sonnet"})
        await bus.emit("llm_call_end", {"model": "sonnet"})

        await bus.emit("tool_call_start", {"name": "web_search", "correlation_id": "t1"})
        await bus.emit("tool_call_end", {"name": "web_search", "correlation_id": "t1"})

        await bus.emit("llm_call_start", {"model": "sonnet"})
        await bus.emit("llm_call_end", {"model": "sonnet"})

        spans = span_exporter.get_finished_spans()
        assert len(spans) == 3

        # Verify span names contain expected prefixes
        llm_spans = [s for s in spans if "llm" in s.name]
        tool_spans = [s for s in spans if "tool" in s.name]
        assert len(llm_spans) == 2
        assert len(tool_spans) == 1

        # All spans have gen_ai.system
        for span in spans:
            assert span.attributes is not None
            assert span.attributes.get("gen_ai.system") == "cognitia"

    async def test_turn_ordering(self, otel_pipeline: tuple) -> None:
        bus, otel, span_exporter = otel_pipeline

        await bus.emit("llm_call_start", {"model": "sonnet"})
        await bus.emit("llm_call_end", {"model": "sonnet"})

        await bus.emit("tool_call_start", {"name": "calc", "correlation_id": "t1"})
        await bus.emit("tool_call_end", {"name": "calc", "correlation_id": "t1"})

        spans = span_exporter.get_finished_spans()
        assert len(spans) == 2
        assert "llm" in spans[0].name
        assert "tool" in spans[1].name


class TestMultipleToolCallsInSequence:
    """Multiple tool calls produce individual spans."""

    async def test_multiple_tool_calls(self, otel_pipeline: tuple) -> None:
        bus, otel, span_exporter = otel_pipeline

        await bus.emit("llm_call_start", {"model": "sonnet"})

        for i, tool_name in enumerate(["web_search", "calculator", "file_read"]):
            cid = f"tool-{i}"
            await bus.emit("tool_call_start", {"name": tool_name, "correlation_id": cid})
            await bus.emit("tool_call_end", {"name": tool_name, "correlation_id": cid})

        await bus.emit("llm_call_end", {"model": "sonnet"})

        spans = span_exporter.get_finished_spans()
        # 3 tool spans + 1 LLM span = 4
        assert len(spans) == 4

        tool_spans = [s for s in spans if "tool" in s.name]
        assert len(tool_spans) == 3

        tool_names = [s.attributes["tool.name"] for s in tool_spans]
        assert tool_names == ["web_search", "calculator", "file_read"]


class TestErrorPropagationInPipeline:
    """Error events produce ERROR status spans."""

    async def test_llm_error_status(self, otel_pipeline: tuple) -> None:
        bus, otel, span_exporter = otel_pipeline

        await bus.emit("llm_call_start", {"model": "sonnet"})
        await bus.emit("llm_call_end", {"model": "sonnet", "error": True})

        spans = span_exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].status.status_code == StatusCode.ERROR

    async def test_tool_error_status(self, otel_pipeline: tuple) -> None:
        bus, otel, span_exporter = otel_pipeline

        await bus.emit("tool_call_start", {"name": "sandbox", "correlation_id": "t1"})
        await bus.emit("tool_call_end", {"correlation_id": "t1", "error": "timeout"})

        spans = span_exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].status.status_code == StatusCode.ERROR


class TestCoexistenceWithTracingSubscriber:
    """OTelExporter and TracingSubscriber coexist on the same EventBus."""

    async def test_both_receive_events(self) -> None:
        bus = InMemoryEventBus()

        span_exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(span_exporter))
        otel = OTelExporter(tracer_provider=provider)
        otel.attach(bus)

        console_tracer = ConsoleTracer()
        tracing_sub = TracingSubscriber(bus, console_tracer)
        tracing_sub.attach()

        await bus.emit("llm_call_start", {"model": "sonnet"})
        await bus.emit("llm_call_end", {"model": "sonnet"})
        await bus.emit("tool_call_start", {"name": "web_search", "correlation_id": "t1"})
        await bus.emit("tool_call_end", {"name": "web_search", "correlation_id": "t1"})

        # OTel spans
        assert len(span_exporter.get_finished_spans()) == 2

        # ConsoleTracer spans
        console_names = {s["name"] for s in console_tracer._spans.values()}
        assert "llm_call" in console_names
        assert "tool_call" in console_names

        tracing_sub.detach()
        otel.detach(bus)
        provider.shutdown()


class TestAttachDetachLifecycle:
    """OTelExporter stops creating spans after detach."""

    async def test_detach_stops_spans(self) -> None:
        bus = InMemoryEventBus()
        span_exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(span_exporter))
        otel = OTelExporter(tracer_provider=provider)
        otel.attach(bus)

        await bus.emit("llm_call_start", {"model": "sonnet"})
        await bus.emit("llm_call_end", {"model": "sonnet"})
        assert len(span_exporter.get_finished_spans()) == 1

        otel.detach(bus)

        await bus.emit("llm_call_start", {"model": "sonnet"})
        await bus.emit("llm_call_end", {"model": "sonnet"})
        assert len(span_exporter.get_finished_spans()) == 1  # Still 1

        provider.shutdown()

    async def test_reattach_resumes(self) -> None:
        bus = InMemoryEventBus()
        span_exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(span_exporter))
        otel = OTelExporter(tracer_provider=provider)

        otel.attach(bus)
        await bus.emit("llm_call_start", {"model": "sonnet"})
        await bus.emit("llm_call_end", {"model": "sonnet"})
        assert len(span_exporter.get_finished_spans()) == 1

        otel.detach(bus)
        otel.attach(bus)

        await bus.emit("llm_call_start", {"model": "sonnet"})
        await bus.emit("llm_call_end", {"model": "sonnet"})
        assert len(span_exporter.get_finished_spans()) == 2

        otel.detach(bus)
        provider.shutdown()
