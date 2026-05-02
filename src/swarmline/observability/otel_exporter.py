"""OpenTelemetry exporter -- bridges EventBus events to OTel spans.

Subscribes to EventBus events (llm_call_start/end, tool_call_start/end)
and creates OpenTelemetry spans following the GenAI Semantic Conventions.

Usage::

    from swarmline.observability.otel_exporter import OTelExporter

    exporter = OTelExporter()  # uses global TracerProvider
    exporter.attach(event_bus)
    # ... agent runs, events flow ...
    exporter.detach(event_bus)

Requires: ``pip install swarmline[otel]``
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

# OTel GenAI Semantic Convention attribute names (v1.37+)
_ATTR_GEN_AI_SYSTEM = "gen_ai.system"
_ATTR_GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
_ATTR_GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
_ATTR_GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
_ATTR_GEN_AI_RESPONSE_FINISH_REASONS = "gen_ai.response.finish_reasons"
_ATTR_SWARMLINE_RUNTIME = "swarmline.runtime"
_ATTR_SWARMLINE_SESSION_ID = "swarmline.session_id"


def _try_import_otel() -> tuple[Any, Any]:
    """Lazy import OpenTelemetry.

    Returns
    -------
    tuple
        (trace module, StatusCode enum) or raises ImportError with install hint.
    """
    try:
        trace = importlib.import_module("opentelemetry.trace")
        StatusCode = getattr(trace, "StatusCode")

        return trace, StatusCode
    except ImportError:
        raise ImportError(
            "OpenTelemetry is required for OTelExporter. "
            "Install it with: pip install swarmline[otel]"
        ) from None


class OTelExporter:
    """Bridges Swarmline EventBus events to OpenTelemetry spans.

    Follows OTel GenAI Semantic Conventions (v1.37+).
    Each LLM call and tool call becomes an OTel span with standard attributes.

    Parameters
    ----------
    tracer_provider:
        Optional OTel TracerProvider. If ``None``, uses the global provider.
    service_name:
        Service name for the tracer. Default: ``"swarmline"``.
    runtime_name:
        Optional runtime identifier (e.g. ``"thin"``, ``"claude_code"``).
    session_id:
        Optional session identifier for correlating spans across turns.
    """

    def __init__(
        self,
        bus: Any = None,
        *,
        tracer_provider: Any = None,
        service_name: str = "swarmline",
        runtime_name: str | None = None,
        session_id: str | None = None,
    ) -> None:
        trace, self._StatusCode = _try_import_otel()

        if tracer_provider is not None:
            self._tracer = trace.get_tracer(
                service_name,
                tracer_provider=tracer_provider,
            )
        else:
            self._tracer = trace.get_tracer(service_name)

        self._bus = bus
        self._runtime_name = runtime_name
        self._session_id = session_id
        self._active_spans: dict[str, Any] = {}  # key -> OTel Span
        self._sub_ids: list[str] = []

    def attach(self, event_bus: Any = None) -> None:
        """Subscribe to EventBus events.

        Parameters
        ----------
        event_bus:
            EventBus to subscribe to. If ``None``, uses the bus passed
            to the constructor.
        """
        bus = event_bus or self._bus
        if bus is None:
            raise ValueError("No EventBus provided to attach()")
        self._bus = bus
        self._sub_ids.append(bus.subscribe("llm_call_start", self._on_llm_start))
        self._sub_ids.append(bus.subscribe("llm_call_end", self._on_llm_end))
        self._sub_ids.append(bus.subscribe("tool_call_start", self._on_tool_start))
        self._sub_ids.append(bus.subscribe("tool_call_end", self._on_tool_end))

    def detach(self, event_bus: Any = None) -> None:
        """Unsubscribe from all events and end any lingering spans.

        Parameters
        ----------
        event_bus:
            EventBus to unsubscribe from. If ``None``, uses the stored bus.
        """
        bus = event_bus or self._bus
        if bus is None:
            return
        for sid in self._sub_ids:
            bus.unsubscribe(sid)
        self._sub_ids.clear()
        for span in self._active_spans.values():
            try:
                span.end()
            except Exception:  # noqa: BLE001
                pass
        self._active_spans.clear()

    def _base_attributes(self) -> dict[str, Any]:
        """Common attributes for all spans."""
        attrs: dict[str, Any] = {_ATTR_GEN_AI_SYSTEM: "swarmline"}
        if self._runtime_name:
            attrs[_ATTR_SWARMLINE_RUNTIME] = self._runtime_name
        if self._session_id:
            attrs[_ATTR_SWARMLINE_SESSION_ID] = self._session_id
        return attrs

    def _on_llm_start(self, data: dict[str, Any]) -> None:
        """Handle llm_call_start event -- start OTel span."""
        model = data.get("model", "unknown")
        attrs = self._base_attributes()
        attrs[_ATTR_GEN_AI_REQUEST_MODEL] = model

        span = self._tracer.start_span(
            name=f"swarmline.llm.{model}",
            attributes=attrs,
        )
        span_key = f"llm_call:{data.get('correlation_id', id(span))}"
        self._active_spans[span_key] = span

    def _on_llm_end(self, data: dict[str, Any]) -> None:
        """Handle llm_call_end event -- end OTel span."""
        span_key = f"llm_call:{data.get('correlation_id', '')}"
        span = self._active_spans.pop(span_key, None)
        if span is None:
            # Fallback: find any llm_call span (backward compat)
            for k in list(self._active_spans):
                if k.startswith("llm_call:"):
                    span = self._active_spans.pop(k)
                    break
        if span is None:
            return

        if "input_tokens" in data:
            span.set_attribute(_ATTR_GEN_AI_USAGE_INPUT_TOKENS, data["input_tokens"])
        if "output_tokens" in data:
            span.set_attribute(_ATTR_GEN_AI_USAGE_OUTPUT_TOKENS, data["output_tokens"])
        if "finish_reasons" in data:
            span.set_attribute(
                _ATTR_GEN_AI_RESPONSE_FINISH_REASONS,
                str(data["finish_reasons"]),
            )
        elif "finish_reason" in data:
            span.set_attribute(
                _ATTR_GEN_AI_RESPONSE_FINISH_REASONS,
                str(data["finish_reason"]),
            )

        if data.get("error"):
            description = data.get("error_message", "LLM call failed")
            span.set_status(self._StatusCode.ERROR, description)
            if "error_message" in data:
                span.set_attribute("error.message", data["error_message"])
        else:
            span.set_status(self._StatusCode.OK)

        span.end()

    def _on_tool_start(self, data: dict[str, Any]) -> None:
        """Handle tool_call_start event -- start OTel span."""
        tool_name = data.get("name", "unknown_tool")
        correlation_id = data.get("correlation_id", tool_name)

        attrs = self._base_attributes()
        attrs["tool.name"] = tool_name
        if "correlation_id" in data:
            attrs["tool.correlation_id"] = correlation_id

        span = self._tracer.start_span(
            name=f"swarmline.tool.{tool_name}",
            attributes=attrs,
        )
        key = f"tool_call:{correlation_id}"
        self._active_spans[key] = span

    def _on_tool_end(self, data: dict[str, Any]) -> None:
        """Handle tool_call_end event -- end OTel span."""
        correlation_id = data.get("correlation_id", data.get("name", "unknown"))
        key = f"tool_call:{correlation_id}"
        span = self._active_spans.pop(key, None)
        if span is None:
            return

        if data.get("error"):
            description = data.get("error_message", "Tool call failed")
            span.set_status(self._StatusCode.ERROR, description)
            if "error_message" in data:
                span.set_attribute("error.message", data["error_message"])
        else:
            span.set_status(self._StatusCode.OK)

        span.end()
