"""Observability module — structured logs, event bus, tracing, activity log, OpenTelemetry."""

from swarmline.observability.activity_log import (
    ActivityLog,
    InMemoryActivityLog,
    SqliteActivityLog,
)
from swarmline.observability.activity_subscriber import ActivityLogSubscriber
from swarmline.observability.activity_types import (
    ActivityEntry,
    ActivityFilter,
    ActorType,
)
from swarmline.observability.event_bus import EventBus, InMemoryEventBus
from swarmline.observability.jsonl_sink import JsonlTelemetrySink
from swarmline.observability.logger import AgentLogger, configure_logging
from swarmline.observability.tracer import (
    ConsoleTracer,
    NoopTracer,
    Tracer,
    TracingSubscriber,
)

__all__ = [
    "ActivityEntry",
    "ActivityFilter",
    "ActivityLog",
    "ActivityLogSubscriber",
    "ActorType",
    "AgentLogger",
    "ConsoleTracer",
    "EventBus",
    "InMemoryActivityLog",
    "InMemoryEventBus",
    "JsonlTelemetrySink",
    "NoopTracer",
    "OTelExporter",
    "SqliteActivityLog",
    "Tracer",
    "TracingSubscriber",
    "configure_logging",
]


def __getattr__(name: str) -> object:
    if name == "OTelExporter":
        from swarmline.observability.otel_exporter import OTelExporter

        return OTelExporter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
