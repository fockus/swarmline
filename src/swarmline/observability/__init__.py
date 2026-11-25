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
from swarmline.observability.harness_infra import register_observability_infra
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
    "LangSmithExporter",
    "LangfuseExporter",
    "NoopTracer",
    "OTelExporter",
    "SqliteActivityLog",
    "Tracer",
    "TracingSubscriber",
    "configure_logging",
    "configure_otlp_from_env",
    "register_observability_infra",
]


def __getattr__(name: str) -> object:
    if name == "OTelExporter":
        from swarmline.observability.otel_exporter import OTelExporter

        return OTelExporter
    if name == "configure_otlp_from_env":
        from swarmline.observability.otlp_setup import configure_otlp_from_env

        return configure_otlp_from_env
    if name == "LangfuseExporter":
        from swarmline.observability.langfuse_exporter import LangfuseExporter

        return LangfuseExporter
    if name == "LangSmithExporter":
        from swarmline.observability.langsmith_exporter import LangSmithExporter

        return LangSmithExporter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
