"""Unit tests for OTelExporter -- EventBus to OpenTelemetry spans bridge.

Uses real OpenTelemetry SDK TracerProvider with a custom InMemorySpanExporter
to capture and verify actual OTel Span objects. Module skipped gracefully if
opentelemetry SDK is not installed.
"""

from __future__ import annotations

from typing import Sequence
from unittest.mock import patch

import pytest

from swarmline.observability.event_bus import InMemoryEventBus

# Skip entire module if opentelemetry SDK not installed
otel_sdk = pytest.importorskip("opentelemetry.sdk")

from opentelemetry.sdk.trace import ReadableSpan, TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult  # noqa: E402
from opentelemetry.trace import StatusCode  # noqa: E402

from swarmline.observability.otel_exporter import OTelExporter  # noqa: E402


# ---------------------------------------------------------------------------
# Helper: in-memory span exporter (not shipped with otel-sdk >= 1.40)
# ---------------------------------------------------------------------------


class _InMemorySpanExporter(SpanExporter):
    """Captures finished spans in a list for test assertions."""

    def __init__(self) -> None:
        self._spans: list[ReadableSpan] = []
        self._shutdown = False

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        if self._shutdown:
            return SpanExportResult.FAILURE
        self._spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        self._shutdown = True

    def force_flush(self, timeout_millis: int = 0) -> bool:
        return True

    def get_finished_spans(self) -> list[ReadableSpan]:
        return list(self._spans)

    def clear(self) -> None:
        self._spans.clear()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def otel_setup():
    """Create TracerProvider + _InMemorySpanExporter for capturing spans."""
    exporter = _InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield provider, exporter
    provider.shutdown()


@pytest.fixture
def event_bus():
    return InMemoryEventBus()


# ---------------------------------------------------------------------------
# LLM call spans
# ---------------------------------------------------------------------------


class TestOTelExporterLlmCallSpan:
    """LLM call events create properly attributed OTel spans."""

    async def test_llm_call_start_end_creates_single_span(
        self, event_bus: InMemoryEventBus, otel_setup: tuple
    ) -> None:
        """emit llm_call_start + llm_call_end produces exactly 1 finished span."""
        provider, span_exporter = otel_setup
        exporter = OTelExporter(event_bus, tracer_provider=provider)
        exporter.attach()

        await event_bus.emit("llm_call_start", {"model": "sonnet"})
        await event_bus.emit("llm_call_end", {"model": "sonnet"})

        exporter.detach()

        spans = span_exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "swarmline.llm.sonnet"

    async def test_llm_call_span_has_genai_attributes(
        self, event_bus: InMemoryEventBus, otel_setup: tuple
    ) -> None:
        """Span carries gen_ai.system and gen_ai.request.model attributes."""
        provider, span_exporter = otel_setup
        exporter = OTelExporter(event_bus, tracer_provider=provider)
        exporter.attach()

        await event_bus.emit("llm_call_start", {"model": "opus"})
        await event_bus.emit("llm_call_end", {"model": "opus"})

        exporter.detach()

        spans = span_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes or {})
        assert attrs["gen_ai.system"] == "swarmline"
        assert attrs["gen_ai.request.model"] == "opus"

    async def test_llm_call_with_token_usage_sets_usage_attributes(
        self, event_bus: InMemoryEventBus, otel_setup: tuple
    ) -> None:
        """Token usage from llm_call_end is recorded on the span."""
        provider, span_exporter = otel_setup
        exporter = OTelExporter(event_bus, tracer_provider=provider)
        exporter.attach()

        await event_bus.emit("llm_call_start", {"model": "sonnet"})
        await event_bus.emit(
            "llm_call_end",
            {"model": "sonnet", "input_tokens": 150, "output_tokens": 42},
        )

        exporter.detach()

        attrs = dict(span_exporter.get_finished_spans()[0].attributes or {})
        assert attrs["gen_ai.usage.input_tokens"] == 150
        assert attrs["gen_ai.usage.output_tokens"] == 42

    async def test_llm_call_error_sets_error_status(
        self, event_bus: InMemoryEventBus, otel_setup: tuple
    ) -> None:
        """llm_call_end with error=True results in StatusCode.ERROR."""
        provider, span_exporter = otel_setup
        exporter = OTelExporter(event_bus, tracer_provider=provider)
        exporter.attach()

        await event_bus.emit("llm_call_start", {"model": "sonnet"})
        await event_bus.emit(
            "llm_call_end",
            {"model": "sonnet", "error": True, "error_message": "rate limit"},
        )

        exporter.detach()

        span = span_exporter.get_finished_spans()[0]
        assert span.status.status_code == StatusCode.ERROR
        assert "rate limit" in (span.status.description or "")

    async def test_llm_call_success_sets_ok_status(
        self, event_bus: InMemoryEventBus, otel_setup: tuple
    ) -> None:
        """Normal llm_call_end results in StatusCode.OK."""
        provider, span_exporter = otel_setup
        exporter = OTelExporter(event_bus, tracer_provider=provider)
        exporter.attach()

        await event_bus.emit("llm_call_start", {"model": "sonnet"})
        await event_bus.emit(
            "llm_call_end", {"model": "sonnet", "finish_reason": "stop"}
        )

        exporter.detach()

        span = span_exporter.get_finished_spans()[0]
        assert span.status.status_code == StatusCode.OK


# ---------------------------------------------------------------------------
# Tool call spans
# ---------------------------------------------------------------------------


class TestOTelExporterToolCallSpan:
    """Tool call events create properly attributed OTel spans."""

    async def test_tool_call_creates_span_with_tool_name(
        self, event_bus: InMemoryEventBus, otel_setup: tuple
    ) -> None:
        """emit tool_call_start + tool_call_end produces a span with tool.name."""
        provider, span_exporter = otel_setup
        exporter = OTelExporter(event_bus, tracer_provider=provider)
        exporter.attach()

        await event_bus.emit(
            "tool_call_start", {"name": "web_search", "correlation_id": "c1"}
        )
        await event_bus.emit(
            "tool_call_end", {"name": "web_search", "correlation_id": "c1"}
        )

        exporter.detach()

        spans = span_exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "swarmline.tool.web_search"
        attrs = dict(spans[0].attributes or {})
        assert attrs["tool.name"] == "web_search"

    async def test_tool_call_correlation_id_attribute(
        self, event_bus: InMemoryEventBus, otel_setup: tuple
    ) -> None:
        """Correlation ID is recorded as a span attribute."""
        provider, span_exporter = otel_setup
        exporter = OTelExporter(event_bus, tracer_provider=provider)
        exporter.attach()

        await event_bus.emit(
            "tool_call_start", {"name": "calc", "correlation_id": "corr-42"}
        )
        await event_bus.emit(
            "tool_call_end", {"name": "calc", "correlation_id": "corr-42"}
        )

        exporter.detach()

        attrs = dict(span_exporter.get_finished_spans()[0].attributes or {})
        assert attrs["tool.correlation_id"] == "corr-42"

    async def test_tool_call_error_sets_error_status(
        self, event_bus: InMemoryEventBus, otel_setup: tuple
    ) -> None:
        """Tool end with error=True results in StatusCode.ERROR."""
        provider, span_exporter = otel_setup
        exporter = OTelExporter(event_bus, tracer_provider=provider)
        exporter.attach()

        await event_bus.emit(
            "tool_call_start", {"name": "sandbox", "correlation_id": "c1"}
        )
        await event_bus.emit(
            "tool_call_end",
            {
                "name": "sandbox",
                "correlation_id": "c1",
                "error": True,
                "error_message": "timeout",
            },
        )

        exporter.detach()

        span = span_exporter.get_finished_spans()[0]
        assert span.status.status_code == StatusCode.ERROR

    async def test_multiple_concurrent_tool_calls_tracked_separately(
        self, event_bus: InMemoryEventBus, otel_setup: tuple
    ) -> None:
        """Two tools start, then end in reverse order -- both spans are correct."""
        provider, span_exporter = otel_setup
        exporter = OTelExporter(event_bus, tracer_provider=provider)
        exporter.attach()

        await event_bus.emit(
            "tool_call_start", {"name": "tool_a", "correlation_id": "a1"}
        )
        await event_bus.emit(
            "tool_call_start", {"name": "tool_b", "correlation_id": "b1"}
        )
        # End in reverse order
        await event_bus.emit(
            "tool_call_end", {"name": "tool_b", "correlation_id": "b1"}
        )
        await event_bus.emit(
            "tool_call_end", {"name": "tool_a", "correlation_id": "a1"}
        )

        exporter.detach()

        spans = span_exporter.get_finished_spans()
        assert len(spans) == 2

        span_names = {s.name for s in spans}
        assert span_names == {"swarmline.tool.tool_a", "swarmline.tool.tool_b"}

        # Each span has its own correlation_id
        for span in spans:
            attrs = dict(span.attributes or {})
            if span.name == "swarmline.tool.tool_a":
                assert attrs["tool.correlation_id"] == "a1"
            else:
                assert attrs["tool.correlation_id"] == "b1"


# ---------------------------------------------------------------------------
# Configuration and custom attributes
# ---------------------------------------------------------------------------


class TestOTelExporterConfig:
    """Constructor parameters propagate to span attributes."""

    async def test_custom_runtime_and_session_attributes(
        self, event_bus: InMemoryEventBus, otel_setup: tuple
    ) -> None:
        """runtime_name and session_id appear as span attributes."""
        provider, span_exporter = otel_setup
        exporter = OTelExporter(
            event_bus,
            tracer_provider=provider,
            runtime_name="thin",
            session_id="s1",
        )
        exporter.attach()

        await event_bus.emit("llm_call_start", {"model": "sonnet"})
        await event_bus.emit("llm_call_end", {"model": "sonnet"})

        exporter.detach()

        attrs = dict(span_exporter.get_finished_spans()[0].attributes or {})
        assert attrs["swarmline.runtime"] == "thin"
        assert attrs["swarmline.session_id"] == "s1"

    async def test_finish_reason_attribute(
        self, event_bus: InMemoryEventBus, otel_setup: tuple
    ) -> None:
        """finish_reason from llm_call_end is set as gen_ai.response.finish_reasons."""
        provider, span_exporter = otel_setup
        exporter = OTelExporter(event_bus, tracer_provider=provider)
        exporter.attach()

        await event_bus.emit("llm_call_start", {"model": "sonnet"})
        await event_bus.emit(
            "llm_call_end", {"model": "sonnet", "finish_reason": "end_turn"}
        )

        exporter.detach()

        attrs = dict(span_exporter.get_finished_spans()[0].attributes or {})
        assert attrs["gen_ai.response.finish_reasons"] == "end_turn"

    async def test_span_without_optional_attrs_omits_them(
        self, event_bus: InMemoryEventBus, otel_setup: tuple
    ) -> None:
        """When runtime_name/session_id not set, those attributes are absent."""
        provider, span_exporter = otel_setup
        exporter = OTelExporter(event_bus, tracer_provider=provider)
        exporter.attach()

        await event_bus.emit("llm_call_start", {"model": "m"})
        await event_bus.emit("llm_call_end", {"model": "m"})

        exporter.detach()

        attrs = dict(span_exporter.get_finished_spans()[0].attributes or {})
        assert "swarmline.runtime" not in attrs
        assert "swarmline.session_id" not in attrs


# ---------------------------------------------------------------------------
# Lifecycle: detach, edge cases
# ---------------------------------------------------------------------------


class TestOTelExporterLifecycle:
    """Detach and edge-case behavior."""

    async def test_detach_ends_lingering_spans(
        self, event_bus: InMemoryEventBus, otel_setup: tuple
    ) -> None:
        """Start span without end, then detach -- span is forcibly ended."""
        provider, span_exporter = otel_setup
        exporter = OTelExporter(event_bus, tracer_provider=provider)
        exporter.attach()

        await event_bus.emit("llm_call_start", {"model": "sonnet"})
        # No llm_call_end -- detach should clean up
        exporter.detach()

        spans = span_exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "swarmline.llm.sonnet"

    async def test_detach_clears_subscriptions_no_new_spans(
        self, event_bus: InMemoryEventBus, otel_setup: tuple
    ) -> None:
        """After detach, new events do not create spans."""
        provider, span_exporter = otel_setup
        exporter = OTelExporter(event_bus, tracer_provider=provider)
        exporter.attach()
        exporter.detach()

        # These should be ignored -- no subscriber
        await event_bus.emit("llm_call_start", {"model": "sonnet"})
        await event_bus.emit("llm_call_end", {"model": "sonnet"})

        spans = span_exporter.get_finished_spans()
        assert len(spans) == 0

    async def test_end_without_start_llm_is_noop(
        self, event_bus: InMemoryEventBus, otel_setup: tuple
    ) -> None:
        """Emitting llm_call_end without a prior start does not crash or create a span."""
        provider, span_exporter = otel_setup
        exporter = OTelExporter(event_bus, tracer_provider=provider)
        exporter.attach()

        await event_bus.emit("llm_call_end", {"model": "sonnet"})

        exporter.detach()

        spans = span_exporter.get_finished_spans()
        assert len(spans) == 0

    async def test_end_without_start_tool_is_noop(
        self, event_bus: InMemoryEventBus, otel_setup: tuple
    ) -> None:
        """Emitting tool_call_end without a prior start does not crash or create a span."""
        provider, span_exporter = otel_setup
        exporter = OTelExporter(event_bus, tracer_provider=provider)
        exporter.attach()

        await event_bus.emit(
            "tool_call_end", {"name": "calc", "correlation_id": "c1"}
        )

        exporter.detach()

        spans = span_exporter.get_finished_spans()
        assert len(spans) == 0


# ---------------------------------------------------------------------------
# Import error handling
# ---------------------------------------------------------------------------


class TestOTelExporterImportGuard:
    """Missing opentelemetry raises a helpful ImportError."""

    def test_missing_otel_gives_clear_error(self) -> None:
        """If opentelemetry is not installed, _try_import_otel raises ImportError with install hint."""
        with patch.dict(
            "sys.modules",
            {"opentelemetry": None, "opentelemetry.trace": None},
        ):
            from swarmline.observability.otel_exporter import _try_import_otel

            with pytest.raises(ImportError, match="(?i)opentelemetry"):
                _try_import_otel()
