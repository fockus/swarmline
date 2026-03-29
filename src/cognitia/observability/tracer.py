"""Tracer — tracing interface for spans.

Provides:
- Tracer: Protocol defining the tracing contract.
- NoopTracer: No-op implementation (tracing disabled).
- ConsoleTracer: Logs spans via structlog (dev/debug).
- TracingSubscriber: Bridges EventBus events to Tracer spans.
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from typing import Any, Protocol, runtime_checkable

from cognitia.observability.event_bus import EventBus


@runtime_checkable
class Tracer(Protocol):
    """Tracing interface for spans."""

    def start_span(self, name: str, attrs: dict[str, Any] | None = None) -> str:
        """Start a new span. Returns span ID."""
        ...

    def end_span(self, span_id: str) -> None:
        """End a span by ID."""
        ...

    def add_event(
        self, span_id: str, name: str, attrs: dict[str, Any] | None = None
    ) -> None:
        """Add an event to an existing span."""
        ...


class NoopTracer:
    """No-op tracer for when tracing is disabled."""

    def start_span(self, name: str, attrs: dict[str, Any] | None = None) -> str:
        """Return a dummy span ID."""
        return f"noop_{uuid.uuid4().hex[:8]}"

    def end_span(self, span_id: str) -> None:
        """No-op."""

    def add_event(
        self, span_id: str, name: str, attrs: dict[str, Any] | None = None
    ) -> None:
        """No-op."""


class ConsoleTracer:
    """Simple tracer that logs spans to structlog.

    Also tracks spans internally for testing/introspection.
    """

    def __init__(self, max_completed: int = 1000) -> None:
        import structlog

        self._log = structlog.get_logger(component="tracer")
        self._spans: dict[str, dict[str, Any]] = {}
        self._completed_spans: deque[dict[str, Any]] = deque(maxlen=max_completed)
        self._counter = 0

    def start_span(self, name: str, attrs: dict[str, Any] | None = None) -> str:
        """Start a span and log it."""
        span_id = f"span_{self._counter}_{uuid.uuid4().hex[:6]}"
        self._counter += 1
        self._spans[span_id] = {
            "name": name,
            "attrs": attrs or {},
            "events": [],
            "started_at": time.monotonic(),
            "ended": False,
        }
        self._log.info("span_start", span_id=span_id, name=name, attrs=attrs or {})
        return span_id

    def end_span(self, span_id: str) -> None:
        """End a span, log duration, and move from active to completed."""
        span = self._spans.pop(span_id, None)
        if span is not None:
            duration_ms = int((time.monotonic() - span["started_at"]) * 1000)
            span["ended"] = True
            span["duration_ms"] = duration_ms
            self._completed_spans.append(span)
            self._log.info(
                "span_end",
                span_id=span_id,
                name=span["name"],
                duration_ms=duration_ms,
            )

    def add_event(
        self, span_id: str, name: str, attrs: dict[str, Any] | None = None
    ) -> None:
        """Add an event to a span."""
        span = self._spans.get(span_id)
        if span is not None:
            span["events"].append({"name": name, "attrs": attrs or {}})
            self._log.info(
                "span_event",
                span_id=span_id,
                event_name=name,
                attrs=attrs or {},
            )


class TracingSubscriber:
    """Bridges EventBus events to Tracer spans.

    Subscribes to:
    - llm_call_start / llm_call_end -> creates "llm_call" spans
    - tool_call_start / tool_call_end -> creates "tool_call" spans
    """

    def __init__(self, bus: EventBus, tracer: Tracer) -> None:
        self._bus = bus
        self._tracer = tracer
        self._active_spans: dict[str, str] = {}  # event_key -> span_id
        self._sub_ids: list[str] = []

    def attach(self) -> None:
        """Subscribe to relevant EventBus events."""
        self._sub_ids.append(
            self._bus.subscribe("llm_call_start", self._on_llm_start)
        )
        self._sub_ids.append(
            self._bus.subscribe("llm_call_end", self._on_llm_end)
        )
        self._sub_ids.append(
            self._bus.subscribe("tool_call_start", self._on_tool_start)
        )
        self._sub_ids.append(
            self._bus.subscribe("tool_call_end", self._on_tool_end)
        )

    def detach(self) -> None:
        """Unsubscribe from all events."""
        for sid in self._sub_ids:
            self._bus.unsubscribe(sid)
        self._sub_ids.clear()

    def _on_llm_start(self, data: dict[str, Any]) -> None:
        span_id = self._tracer.start_span("llm_call", data)
        key = f"llm_call:{data.get('correlation_id', span_id)}"
        self._active_spans[key] = span_id

    def _on_llm_end(self, data: dict[str, Any]) -> None:
        key = f"llm_call:{data.get('correlation_id', '')}"
        span_id = self._active_spans.pop(key, None)
        if span_id is None:
            # Fallback: find any llm_call span
            for k in list(self._active_spans):
                if k.startswith("llm_call:"):
                    span_id = self._active_spans.pop(k)
                    break
        if span_id is not None:
            self._tracer.add_event(span_id, "llm_call_end", data)
            self._tracer.end_span(span_id)

    def _on_tool_start(self, data: dict[str, Any]) -> None:
        correlation_id = data.get("correlation_id", data.get("name", "unknown"))
        key = f"tool_call:{correlation_id}"
        span_id = self._tracer.start_span("tool_call", data)
        self._active_spans[key] = span_id

    def _on_tool_end(self, data: dict[str, Any]) -> None:
        correlation_id = data.get("correlation_id", data.get("name", "unknown"))
        key = f"tool_call:{correlation_id}"
        span_id = self._active_spans.pop(key, None)
        if span_id is not None:
            self._tracer.add_event(span_id, "tool_call_end", data)
            self._tracer.end_span(span_id)
