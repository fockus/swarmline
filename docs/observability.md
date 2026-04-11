# Observability

Lightweight event bus and structured tracing for runtime instrumentation.

## Event Bus

A pub-sub event bus for internal runtime events. Subscribers (tracing, metrics, UI) receive events without coupling to the runtime.

```python
from swarmline.observability.event_bus import InMemoryEventBus
from swarmline.runtime.types import RuntimeConfig

bus = InMemoryEventBus()

# Subscribe to events
metrics = []
bus.subscribe("llm_call_end", lambda data: metrics.append(data))

# Wire into runtime
config = RuntimeConfig(runtime_name="thin", event_bus=bus)
```

### Automatic Events

When `event_bus` is set in `RuntimeConfig`, ThinRuntime emits these events automatically:

| Event | When | Data fields |
|-------|------|-------------|
| `llm_call_start` | Before LLM request | `model` |
| `llm_call_end` | After LLM response | `model`, `error` (if failed) |
| `tool_call_start` | Before tool execution | `name`, `correlation_id` |
| `tool_call_end` | After tool execution | `name`, `ok`, `correlation_id` |

### EventBus Protocol

```python
class EventBus(Protocol):
    def subscribe(self, event_type: str, callback) -> str: ...     # returns subscription ID
    def unsubscribe(self, subscription_id: str) -> None: ...
    async def emit(self, event_type: str, data: dict) -> None: ...
```

- Supports both sync and async callbacks
- Errors in callbacks are caught and ignored (fire-and-forget semantics)
- Unsubscribing a non-existent ID is a no-op

---

## Tracing

Span-based structured tracing via the `Tracer` protocol. `TracingSubscriber` bridges EventBus events to Tracer spans automatically.

```python
from swarmline.observability.event_bus import InMemoryEventBus
from swarmline.observability.tracer import ConsoleTracer, TracingSubscriber
from swarmline.runtime.types import RuntimeConfig

bus = InMemoryEventBus()
tracer = ConsoleTracer()

# Bridge: EventBus events → Tracer spans
subscriber = TracingSubscriber(bus, tracer)
subscriber.attach()

config = RuntimeConfig(runtime_name="thin", event_bus=bus, tracer=tracer)

# After execution, inspect spans:
# tracer._spans contains all recorded spans with timing
subscriber.detach()
```

### Built-in Tracers

| Tracer | Description |
|--------|-------------|
| `NoopTracer` | Zero-overhead stub for production without tracing |
| `ConsoleTracer` | Logs spans via `structlog` with `duration_ms` timing |

### Tracer Protocol

```python
class Tracer(Protocol):
    def start_span(self, name: str, attrs: dict | None = None) -> str: ...  # span_id
    def end_span(self, span_id: str) -> None: ...
    def add_event(self, span_id: str, name: str, attrs: dict | None = None) -> None: ...
```

### Custom Tracers

Bridge to OpenTelemetry, Datadog, or any observability platform:

```python
from opentelemetry import trace

class OTelTracer:
    def __init__(self):
        self._tracer = trace.get_tracer("swarmline")
        self._spans = {}

    def start_span(self, name, attrs=None):
        span = self._tracer.start_span(name, attributes=attrs or {})
        span_id = f"otel_{id(span)}"
        self._spans[span_id] = span
        return span_id

    def end_span(self, span_id):
        if span_id in self._spans:
            self._spans.pop(span_id).end()

    def add_event(self, span_id, name, attrs=None):
        if span_id in self._spans:
            self._spans[span_id].add_event(name, attributes=attrs or {})
```

### TracingSubscriber Lifecycle

```python
subscriber = TracingSubscriber(bus, tracer)
subscriber.attach()   # subscribes to llm_call_start/end, tool_call_start/end
# ... runtime execution ...
subscriber.detach()   # removes all subscriptions
```

`attach()` / `detach()` provide explicit lifecycle control — the subscriber can be reused across multiple runs.

---

## Combining with Other Features

Event bus integrates naturally with other Swarmline features:

```python
from swarmline.runtime.cost import CostBudget
from swarmline.observability.event_bus import InMemoryEventBus
from swarmline.observability.tracer import ConsoleTracer, TracingSubscriber

bus = InMemoryEventBus()
tracer = ConsoleTracer()
TracingSubscriber(bus, tracer).attach()

config = RuntimeConfig(
    runtime_name="thin",
    event_bus=bus,
    tracer=tracer,
    cost_budget=CostBudget(max_cost_usd=10.0),
)
# Cost events, tool calls, and LLM calls are all traced automatically
```

---

## OpenTelemetry Integration

`OTelExporter` bridges EventBus events directly to OpenTelemetry spans, following the [GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/). Every LLM call and tool call becomes a first-class OTel span with standardized attributes.

### Installation

```bash
pip install swarmline[otel]
```

This installs `opentelemetry-api` and `opentelemetry-sdk`.

### Quick Start

```python
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter

from swarmline.observability.event_bus import InMemoryEventBus
from swarmline.observability.otel_exporter import OTelExporter
from swarmline.runtime.types import RuntimeConfig

bus = InMemoryEventBus()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

otel = OTelExporter(bus, tracer_provider=provider, service_name="my-agent")
otel.attach()

config = RuntimeConfig(runtime_name="thin", event_bus=bus)
# ... run your agent — spans are exported automatically ...
otel.detach()
```

### Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `bus` | `EventBus` | *(required)* | EventBus instance to subscribe to |
| `tracer_provider` | `TracerProvider` | global provider | OTel TracerProvider for span creation |
| `service_name` | `str` | `"swarmline"` | Value for `gen_ai.system` on every span |
| `runtime_name` | `str \| None` | `None` | Runtime identifier (e.g. `"thin"`, `"claude_code"`) |
| `session_id` | `str \| None` | `None` | Session ID for correlating spans across turns |

### GenAI Semantic Convention Attributes

Every span created by `OTelExporter` includes standardized attributes:

| Attribute | Span Type | Description |
|-----------|-----------|-------------|
| `gen_ai.system` | all | Service name (always present) |
| `gen_ai.request.model` | LLM | Model requested (e.g. `"sonnet"`) |
| `gen_ai.response.model` | LLM | Model that responded |
| `gen_ai.usage.input_tokens` | LLM | Input token count (when available) |
| `gen_ai.usage.output_tokens` | LLM | Output token count (when available) |
| `gen_ai.runtime` | all | Runtime name (when configured) |
| `session.id` | all | Session identifier (when configured) |
| `tool.name` | Tool | Tool name (e.g. `"web_search"`) |

### Exporting to Observability Backends

**Datadog** -- Use the OTLP exporter. Datadog Agent (v6.32+/v7.32+) accepts OTLP over gRPC on port 4317 by default:

```python
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
processor = SimpleSpanProcessor(OTLPSpanExporter(endpoint="http://localhost:4317"))
```

**Jaeger** -- Jaeger supports OTLP natively since v1.35. Point the OTLP exporter at Jaeger's collector endpoint (default `localhost:4317`).

**Grafana Tempo** -- Tempo accepts OTLP traces directly. Configure `OTLPSpanExporter(endpoint="http://tempo:4317")` and spans appear in Grafana's Explore view.

### Coexistence with ConsoleTracer / TracingSubscriber

`OTelExporter` and `TracingSubscriber` can both subscribe to the same EventBus simultaneously. They operate independently -- events are delivered to all subscribers with no interference:

```python
from swarmline.observability.event_bus import InMemoryEventBus
from swarmline.observability.tracer import ConsoleTracer, TracingSubscriber
from swarmline.observability.otel_exporter import OTelExporter

bus = InMemoryEventBus()

# Internal tracing (structlog)
tracer = ConsoleTracer()
TracingSubscriber(bus, tracer).attach()

# OpenTelemetry export (production)
otel = OTelExporter(bus, tracer_provider=provider, service_name="my-agent")
otel.attach()

# Both receive events from the same bus
config = RuntimeConfig(runtime_name="thin", event_bus=bus, tracer=tracer)
```

### Lifecycle

```python
otel = OTelExporter(bus, tracer_provider=provider)
otel.attach()    # subscribes to llm_call_start/end, tool_call_start/end
# ... agent execution ...
otel.detach()    # unsubscribes, ends any orphaned spans
```

`attach()` / `detach()` mirror the `TracingSubscriber` API. The exporter can be reattached after detaching.

---

## Activity Log

Persistent structured audit trail for agent actions. Tracks who did what to which entity with timestamps and metadata. Useful for compliance, debugging, and understanding agent behavior.

### Domain Types

```python
from swarmline.observability.activity_types import ActivityEntry, ActivityFilter, ActorType

# Create an audit entry
entry = ActivityEntry(
    id="act-001",
    actor_type=ActorType.AGENT,
    actor_id="researcher-1",
    action="task.delegated",
    entity_type="task",
    entity_id="task-42",
    details={"target_agent": "coder-1", "reason": "code implementation needed"},
)

# Filter entries
recent_agent_actions = ActivityFilter(
    actor_type=ActorType.AGENT,
    since=1711700000.0,
)
```

**ActorType** values: `AGENT`, `USER`, `SYSTEM`.

### ActivityLog Protocol

3-method ISP-compliant protocol:

```python
from swarmline.observability.activity_log import ActivityLog

class ActivityLog(Protocol):
    async def log(self, entry: ActivityEntry) -> None: ...
    async def query(self, filter: ActivityFilter) -> list[ActivityEntry]: ...
    async def count(self, filter: ActivityFilter) -> int: ...
```

### Implementations

**InMemoryActivityLog** -- zero-dependency, thread-safe:

```python
from swarmline.observability.activity_log import InMemoryActivityLog

log = InMemoryActivityLog()
await log.log(entry)
entries = await log.query(ActivityFilter(actor_type=ActorType.AGENT))
```

**SqliteActivityLog** -- persistent:

```python
from swarmline.observability.activity_log import SqliteActivityLog

log = SqliteActivityLog(db_path="activity.db")
await log.log(entry)
```

### ActivityLogSubscriber

Auto-bridges EventBus events to ActivityLog entries. Subscribes to graph and pipeline lifecycle events:

```python
from swarmline.observability.activity_subscriber import ActivityLogSubscriber
from swarmline.observability.activity_log import InMemoryActivityLog
from swarmline.observability.event_bus import InMemoryEventBus

bus = InMemoryEventBus()
activity_log = InMemoryActivityLog()

subscriber = ActivityLogSubscriber(bus, activity_log)
subscriber.attach()
# Graph/pipeline events are now automatically logged as ActivityEntries
```

Default topic mappings include: `graph.orchestrator.started`, `graph.orchestrator.delegated`, `graph.orchestrator.agent_completed`, `pipeline.phase.started`, `pipeline.phase.completed`, and more.

Custom mappers can be added via the `extra_mappers` parameter for domain-specific events.
