"""Shared Temporal client helpers (connection + workflow id scheme)."""

from __future__ import annotations

from typing import Any

from swarmline.runtime.temporal.options import TemporalRuntimeOptions


def workflow_id_for_run(options: TemporalRuntimeOptions, run_id: str) -> str:
    """Workflow id for a run — the reattach/signal addressing scheme."""
    return f"{options.workflow_id_prefix}{run_id}"


async def connect_client(options: TemporalRuntimeOptions) -> Any:
    """Connect a ``temporalio.client.Client`` from runtime options.

    Wires the redaction codec (``options.redact_payloads``, default on) and
    the OpenTelemetry tracing interceptor (``options.otel_interceptor``,
    opt-in). Workers built from this client inherit both.
    """
    from temporalio.client import Client

    connect_kwargs: dict[str, Any] = {"namespace": options.namespace}
    if options.api_key:
        connect_kwargs["api_key"] = options.api_key
        connect_kwargs["tls"] = True
    elif options.tls:
        connect_kwargs["tls"] = True
    if options.redact_payloads:
        from swarmline.runtime.temporal.codec import build_data_converter

        connect_kwargs["data_converter"] = build_data_converter()
    if options.otel_interceptor:
        try:
            from temporalio.contrib.opentelemetry import TracingInterceptor
        except ImportError as exc:
            raise ImportError(
                "otel_interceptor=True requires OpenTelemetry: "
                "pip install 'swarmline[otel]' opentelemetry-sdk"
            ) from exc
        connect_kwargs["interceptors"] = [TracingInterceptor()]
    return await Client.connect(options.address, **connect_kwargs)
