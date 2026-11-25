"""Vendor-neutral OTLP setup helper — reads OTEL_* env vars, builds a TracerProvider.

All OTel SDK imports are lazy (via importlib): callers without the SDK pay zero overhead,
and calling configure_otlp_from_env() when OTEL_EXPORTER_OTLP_ENDPOINT is unset/empty
is a guaranteed no-op.  Supports Logfire, Langfuse, SigNoz, Arize, Tempo, Jaeger …

Requires: ``pip install swarmline[otel]`` + ``opentelemetry-exporter-otlp``.
"""

from __future__ import annotations

import importlib
import os
from typing import Any, Callable


def _parse_headers(raw: str) -> dict[str, str]:
    """Parse 'k1=v1,k2=v2' into a dict; entries without '=' are silently ignored."""
    result: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if "=" in entry:
            k, v = entry.split("=", 1)
            result[k.strip()] = v.strip()
    return result


def _default_otlp_exporter(
    *, endpoint: str, headers: dict[str, str], protocol: str
) -> Any:
    """Lazy-load an OTLP SpanExporter for *protocol* (``"http/protobuf"`` or ``"grpc"``)."""
    if protocol not in ("http/protobuf", "grpc"):
        raise ValueError(
            f"Unsupported OTLP protocol: {protocol!r}. "
            "Expected 'http/protobuf' or 'grpc'."
        )
    if protocol == "http/protobuf":
        mod_path = "opentelemetry.exporter.otlp.proto.http.trace_exporter"
    else:
        mod_path = "opentelemetry.exporter.otlp.proto.grpc.trace_exporter"
    try:
        mod = importlib.import_module(mod_path)
    except ImportError:
        raise ImportError(
            "OTLP span exporter not found. "
            "Install it with: pip install opentelemetry-exporter-otlp"
        ) from None
    return mod.OTLPSpanExporter(endpoint=endpoint, headers=headers)


def configure_otlp_from_env(
    *,
    service_name: str | None = None,
    set_global: bool = False,
    exporter_factory: Callable[..., Any] | None = None,
) -> Any | None:
    """Configure a TracerProvider from standard OTEL_* environment variables.

    Returns ``None`` when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is absent or empty
    (checked before any SDK import — safe to call unconditionally).

    Parameters
    ----------
    service_name:
        Service name for spans. Falls back to ``OTEL_SERVICE_NAME``, then
        ``"swarmline"``.
    set_global:
        Register the provider globally via ``trace.set_tracer_provider()``.
        Default ``False`` — never mutates global state in library usage.
    exporter_factory:
        Callable receiving ``endpoint``, ``headers``, ``protocol`` kwargs;
        returns a ``SpanExporter``. Defaults to the bundled OTLP exporter.
    """
    # Early-exit: check endpoint BEFORE any OTel SDK import.
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        return None

    raw_headers = os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "")
    headers = _parse_headers(raw_headers) if raw_headers else {}
    # OTEL spec default is http/protobuf (works with HTTP-only backends like
    # Logfire / Langfuse / Arize that the docs promote); grpc is opt-in.
    protocol = os.environ.get("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")
    service = service_name or os.environ.get("OTEL_SERVICE_NAME") or "swarmline"

    # Lazy OTel SDK import via importlib — never causes unresolved-import errors.
    try:
        _trace_api = importlib.import_module("opentelemetry.trace")
        _sdk_resources = importlib.import_module("opentelemetry.sdk.resources")
        _sdk_trace = importlib.import_module("opentelemetry.sdk.trace")
        _sdk_trace_export = importlib.import_module("opentelemetry.sdk.trace.export")
    except ImportError:
        raise ImportError(
            "OpenTelemetry SDK is required for OTLP tracing. "
            "Install it with: pip install swarmline[otel]"
        ) from None

    Resource = _sdk_resources.Resource
    TracerProvider = _sdk_trace.TracerProvider
    BatchSpanProcessor = _sdk_trace_export.BatchSpanProcessor

    factory = exporter_factory or _default_otlp_exporter
    exporter = factory(endpoint=endpoint, headers=headers, protocol=protocol)

    resource = Resource.create({"service.name": service})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))

    if set_global:
        _trace_api.set_tracer_provider(provider)

    return provider
