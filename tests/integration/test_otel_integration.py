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
def otel_pipeline() -> tuple[InMemoryEventBus, OTelExporter, InMemorySpanExporter]:
    """Set up EventBus -> OTelExporter -> InMemorySpanExporter pipeline."""
    bus = InMemoryEventBus()
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    otel = OTelExporter(bus, tracer_provider=provider, service_name="cognitia-test")
    otel.attach()

    return bus, otel, exporter


class TestFullAgentTurnLifecycle:
    """Simulate a full agent turn and verify span creation."""

    async def test_full_agent_turn_lifecycle_creates_correct_spans(
        self,
        otel_pipeline: tuple[InMemoryEventBus, OTelExporter, InMemorySpanExporter],
    ) -> None:
        bus, otel, exporter = otel_pipeline

        # Simulate: LLM call -> tool call -> second LLM call
        await bus.emit("llm_call_start", {"model": "sonnet", "call_id": "llm-1"})
        await bus.emit("llm_call_end", {"model": "sonnet", "call_id": "llm-1"})

        await bus.emit(
            "tool_call_start",
            {"name": "web_search", "correlation_id": "tool-1"},
        )
        await bus.emit(
            "tool_call_end",
            {"name": "web_search", "ok": True, "correlation_id": "tool-1"},
        )

        await bus.emit("llm_call_start", {"model": "sonnet", "call_id": "llm-2"})
        await bus.emit("llm_call_end", {"model": "sonnet", "call_id": "llm-2"})

        spans = exporter.get_finished_spans()
        assert len(spans) == 3

        span_names = [s.name for s in spans]
        assert span_names.count("llm_call") == 2
        assert span_names.count("tool_call") == 1

        # All spans must have gen_ai.system attribute
        for span in spans:
            assert span.attributes is not None
            assert span.attributes.get("gen_ai.system") == "cognitia-test"

    async def test_full_agent_turn_ordering_matches_emission_order(
        self,
        otel_pipeline: tuple[InMemoryEventBus, OTelExporter, InMemorySpanExporter],
    ) -> None:
        bus, otel, exporter = otel_pipeline

        await bus.emit("llm_call_start", {"model": "sonnet", "call_id": "llm-1"})
        await bus.emit("llm_call_end", {"model": "sonnet", "call_id": "llm-1"})

        await bus.emit(
            "tool_call_start",
            {"name": "calculator", "correlation_id": "tool-1"},
        )
        await bus.emit(
            "tool_call_end",
            {"name": "calculator", "ok": True, "correlation_id": "tool-1"},
        )

        spans = exporter.get_finished_spans()
        assert len(spans) == 2

        # First finished span should be the LLM call (started and ended first)
        assert spans[0].name == "llm_call"
        assert spans[1].name == "tool_call"


class TestMultipleToolCallsInSequence:
    """Multiple tool calls produce individual spans."""

    async def test_multiple_tool_calls_each_produce_individual_span(
        self,
        otel_pipeline: tuple[InMemoryEventBus, OTelExporter, InMemorySpanExporter],
    ) -> None:
        bus, otel, exporter = otel_pipeline

        await bus.emit("llm_call_start", {"model": "sonnet", "call_id": "llm-1"})

        tools = ["web_search", "calculator", "file_read"]
        for i, tool_name in enumerate(tools):
            cid = f"tool-{i}"
            await bus.emit(
                "tool_call_start", {"name": tool_name, "correlation_id": cid}
            )
            await bus.emit(
                "tool_call_end", {"name": tool_name, "ok": True, "correlation_id": cid}
            )

        await bus.emit("llm_call_end", {"model": "sonnet", "call_id": "llm-1"})

        spans = exporter.get_finished_spans()
        assert len(spans) == 4  # 3 tools + 1 LLM

        tool_spans = [s for s in spans if s.name == "tool_call"]
        assert len(tool_spans) == 3

        tool_names = [s.attributes["tool.name"] for s in tool_spans]  # type: ignore[index]
        assert tool_names == ["web_search", "calculator", "file_read"]


class TestErrorPropagationInPipeline:
    """Error events produce ERROR status spans."""

    async def test_llm_call_end_with_error_sets_span_error_status(
        self,
        otel_pipeline: tuple[InMemoryEventBus, OTelExporter, InMemorySpanExporter],
    ) -> None:
        bus, otel, exporter = otel_pipeline

        await bus.emit("llm_call_start", {"model": "sonnet", "call_id": "llm-err"})
        await bus.emit(
            "llm_call_end",
            {"model": "sonnet", "call_id": "llm-err", "error": "rate_limit_exceeded"},
        )

        spans = exporter.get_finished_spans()
        assert len(spans) == 1

        span = spans[0]
        assert span.status.status_code == StatusCode.ERROR
        assert "rate_limit_exceeded" in (span.status.description or "")

    async def test_tool_call_end_with_ok_false_sets_span_error_status(
        self,
        otel_pipeline: tuple[InMemoryEventBus, OTelExporter, InMemorySpanExporter],
    ) -> None:
        bus, otel, exporter = otel_pipeline

        await bus.emit(
            "tool_call_start",
            {"name": "sandbox", "correlation_id": "tool-err"},
        )
        await bus.emit(
            "tool_call_end",
            {
                "name": "sandbox",
                "ok": False,
                "correlation_id": "tool-err",
                "error": "timeout",
            },
        )

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].status.status_code == StatusCode.ERROR


class TestOTelExporterCoexistsWithTracingSubscriber:
    """OTelExporter and TracingSubscriber can both subscribe to the same EventBus."""

    async def test_both_subscribers_receive_events_without_interference(self) -> None:
        bus = InMemoryEventBus()

        # Set up OTel pipeline
        otel_exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(otel_exporter))
        otel = OTelExporter(bus, tracer_provider=provider, service_name="coexist-test")
        otel.attach()

        # Set up TracingSubscriber with ConsoleTracer
        console_tracer = ConsoleTracer()
        tracing_sub = TracingSubscriber(bus, console_tracer)
        tracing_sub.attach()

        # Emit events
        await bus.emit("llm_call_start", {"model": "sonnet", "call_id": "llm-co"})
        await bus.emit("llm_call_end", {"model": "sonnet", "call_id": "llm-co"})

        await bus.emit(
            "tool_call_start",
            {"name": "web_search", "correlation_id": "tool-co"},
        )
        await bus.emit(
            "tool_call_end",
            {"name": "web_search", "ok": True, "correlation_id": "tool-co"},
        )

        # OTel spans created
        otel_spans = otel_exporter.get_finished_spans()
        assert len(otel_spans) == 2

        # ConsoleTracer spans created
        console_span_names = {s["name"] for s in console_tracer._spans.values()}
        assert "llm_call" in console_span_names
        assert "tool_call" in console_span_names

        # Clean up
        tracing_sub.detach()
        otel.detach()


class TestAttachDetachLifecycle:
    """OTelExporter stops creating spans after detach."""

    async def test_detach_stops_span_creation(self) -> None:
        bus = InMemoryEventBus()
        otel_exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(otel_exporter))
        otel = OTelExporter(bus, tracer_provider=provider, service_name="lifecycle-test")
        otel.attach()

        # Emit while attached -> spans created
        await bus.emit("llm_call_start", {"model": "sonnet", "call_id": "llm-a"})
        await bus.emit("llm_call_end", {"model": "sonnet", "call_id": "llm-a"})

        assert len(otel_exporter.get_finished_spans()) == 1

        # Detach
        otel.detach()

        # Emit after detach -> NO new spans
        await bus.emit("llm_call_start", {"model": "sonnet", "call_id": "llm-b"})
        await bus.emit("llm_call_end", {"model": "sonnet", "call_id": "llm-b"})

        assert len(otel_exporter.get_finished_spans()) == 1  # Still 1, not 2

    async def test_reattach_resumes_span_creation(self) -> None:
        bus = InMemoryEventBus()
        otel_exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(otel_exporter))
        otel = OTelExporter(bus, tracer_provider=provider, service_name="reattach-test")

        otel.attach()
        await bus.emit("llm_call_start", {"model": "sonnet", "call_id": "llm-1"})
        await bus.emit("llm_call_end", {"model": "sonnet", "call_id": "llm-1"})
        assert len(otel_exporter.get_finished_spans()) == 1

        otel.detach()
        otel.attach()

        await bus.emit("llm_call_start", {"model": "sonnet", "call_id": "llm-2"})
        await bus.emit("llm_call_end", {"model": "sonnet", "call_id": "llm-2"})
        assert len(otel_exporter.get_finished_spans()) == 2
