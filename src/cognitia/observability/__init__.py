"""Observability module — structured logs, event bus, tracing, OpenTelemetry."""

from cognitia.observability.event_bus import EventBus, InMemoryEventBus
from cognitia.observability.logger import AgentLogger, configure_logging
from cognitia.observability.tracer import ConsoleTracer, NoopTracer, Tracer, TracingSubscriber

__all__ = [
    "AgentLogger",
    "ConsoleTracer",
    "EventBus",
    "InMemoryEventBus",
    "NoopTracer",
    "OTelExporter",
    "Tracer",
    "TracingSubscriber",
    "configure_logging",
]


def __getattr__(name: str) -> object:
    if name == "OTelExporter":
        from cognitia.observability.otel_exporter import OTelExporter

        return OTelExporter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
