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
| `llm_call_start` | Before LLM request | `model`, `correlation_id`, `messages`* |
| `llm_call_end` | After LLM response | `model`, `correlation_id`, `duration_ms`, `error` + `error_message` (if failed), `response`* |
| `tool_call_start` | Before tool execution | `name`, `correlation_id` |
| `tool_call_end` | After tool execution | `name`, `ok`, `correlation_id` |

`correlation_id` pairs each `llm_call_start` with its `llm_call_end`, so
concurrent LLM calls are tracked separately by every exporter.

\* `messages` / `response` are **opt-in content capture** for LLM
observability platforms. Off by default (default-secure). Enable per config:

```python
config = RuntimeConfig(
    runtime_name="thin",
    event_bus=bus,
    extra={"capture_llm_content": True},
)
```

Captured content is passed through `redact_secrets()` and truncated to
4000 chars per field before it reaches the bus. Streaming responses are
not captured (only the final text of buffered calls).

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

## JSONL Telemetry Sink

Use `JsonlTelemetrySink` when you want durable append-only telemetry without
bringing an observability backend. It works with any event type and redacts
common secret fields recursively.

```python
from swarmline.observability import InMemoryEventBus, JsonlTelemetrySink

bus = InMemoryEventBus()
sink = JsonlTelemetrySink("output/swarmline_events.jsonl")

sink.attach(
    bus,
    event_types=[
        "llm_call_start",
        "llm_call_end",
        "structured_retry",
        "pipeline_stage_end",
        "fallback_selected",
    ],
)

await bus.emit("pipeline_stage_end", {"stage": "judge", "ok": True})
sink.detach()
```

You can also record directly:

```python
await sink.record("model_compare", {"provider": "openrouter", "model": "gpt-oss"})
```

Each row contains `schema_version`, `timestamp`, `event_type`, and `data`.

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

### Vendor-neutral OTLP (Logfire / Langfuse / SigNoz / Arize)

Any backend that accepts OpenTelemetry Protocol (OTLP) — Logfire, Langfuse, SigNoz, Arize Phoenix, Grafana Tempo, Jaeger, Datadog, and others — can receive Swarmline spans with zero code changes via environment variables.

#### Zero-code env-var route (recommended)

Set these standard OTEL variables before starting your process:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="https://ingest.logfire.dev"        # your backend
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer <token>"        # auth header
export OTEL_SERVICE_NAME="my-agent"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"                      # or "grpc"
```

Then call `configure_otlp_from_env()` once at startup:

```python
from swarmline.observability import configure_otlp_from_env

# Reads OTEL_* env vars automatically; returns None when endpoint is unset.
provider = configure_otlp_from_env(set_global=True)
```

`configure_otlp_from_env()` is a **no-op** when `OTEL_EXPORTER_OTLP_ENDPOINT` is absent or empty, so it is safe to call unconditionally in library code.

#### Python helper (programmatic control)

```python
from swarmline.observability import configure_otlp_from_env

provider = configure_otlp_from_env(
    service_name="my-agent",        # overrides OTEL_SERVICE_NAME
    set_global=True,                # register as the global TracerProvider
)
```

Or supply a custom exporter factory (useful in tests or for exotic backends):

```python
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

def my_factory(*, endpoint, headers, protocol):
    return OTLPSpanExporter(endpoint=endpoint, headers=headers)

configure_otlp_from_env(exporter_factory=my_factory, set_global=True)
```

#### Installation

```bash
pip install swarmline[otel]                   # OTel SDK (required)
pip install opentelemetry-exporter-otlp       # OTLP gRPC + HTTP exporters
pip install swarmline[logfire]                # optional: Logfire client extras
```

#### Backend quick-reference

| Backend | Endpoint | Protocol | Extra install |
|---------|----------|----------|---------------|
| **Logfire** | `https://ingest.logfire.dev` | `http/protobuf` | `swarmline[logfire]` |
| **Langfuse** | `https://cloud.langfuse.com/api/public/otel` | `http/protobuf` | — |
| **SigNoz** | `http://<host>:4317` | `grpc` | — |
| **Arize Phoenix** | `http://localhost:6006/v1/traces` | `http/protobuf` | — |
| **Grafana Tempo** | `http://<tempo>:4317` | `grpc` | — |
| **Datadog Agent** | `http://localhost:4317` | `grpc` | — |

---

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

## Langfuse Integration

`LangfuseExporter` bridges EventBus events to [Langfuse](https://langfuse.com): LLM calls become Langfuse **generations** (model, token usage, latency, errors), tool calls become **spans**. Works with Langfuse Cloud and self-hosted.

### Installation

```bash
pip install swarmline[langfuse]
export LANGFUSE_PUBLIC_KEY=pk-lf-...
export LANGFUSE_SECRET_KEY=sk-lf-...
export LANGFUSE_HOST=https://cloud.langfuse.com   # or your self-hosted URL
```

### Quick Start

```python
from swarmline.observability import InMemoryEventBus, LangfuseExporter
from swarmline.runtime.types import RuntimeConfig

bus = InMemoryEventBus()

langfuse = LangfuseExporter(bus, runtime_name="thin", session_id="chat-42")
langfuse.attach()

config = RuntimeConfig(
    runtime_name="thin",
    event_bus=bus,
    # opt-in: send prompts/completions (redacted + truncated) to Langfuse
    extra={"capture_llm_content": True},
)
# ... run your agent ...
langfuse.detach()   # ends open observations and flushes the client
```

Without `capture_llm_content`, generations carry model, timing, token usage
(when available), and error status — but no prompt/completion text.
`session_id` is promoted to the Langfuse trace session, so all calls of one
conversation group together in the Langfuse UI.

### Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `bus` | `EventBus` | `None` | EventBus; can also be passed to `attach()` |
| `client` | Langfuse client | `None` | Pre-built client (else built from env / keys) |
| `public_key` / `secret_key` / `host` | `str \| None` | env vars | Explicit credentials |
| `runtime_name` | `str \| None` | `None` | Added to observation metadata |
| `session_id` | `str \| None` | `None` | Langfuse trace session + metadata |

Export failures are logged and swallowed — a Langfuse outage never breaks an agent run.

---

## LangSmith Integration

`LangSmithExporter` bridges EventBus events to [LangSmith](https://smith.langchain.com): LLM calls become runs of type `llm`, tool calls become runs of type `tool`, each with inputs/outputs, timing, and error status.

### Installation

```bash
pip install swarmline[langsmith]
export LANGSMITH_API_KEY=lsv2_...
export LANGSMITH_PROJECT=my-agent     # optional, or pass project_name=
```

### Quick Start

```python
from swarmline.observability import InMemoryEventBus, LangSmithExporter
from swarmline.runtime.types import RuntimeConfig

bus = InMemoryEventBus()

langsmith = LangSmithExporter(
    bus,
    project_name="my-agent",
    runtime_name="thin",
    session_id="chat-42",
)
langsmith.attach()

config = RuntimeConfig(
    runtime_name="thin",
    event_bus=bus,
    extra={"capture_llm_content": True},  # opt-in content capture
)
# ... run your agent ...
langsmith.detach()
```

`session_id` and `runtime_name` land in run metadata, so runs of one session
are filterable in the LangSmith UI.

### Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `bus` | `EventBus` | `None` | EventBus; can also be passed to `attach()` |
| `client` | LangSmith client | `None` | Pre-built client (else built from env / keys) |
| `api_key` / `api_url` | `str \| None` | env vars | Explicit credentials |
| `project_name` | `str \| None` | SDK default | Target LangSmith project |
| `runtime_name` | `str \| None` | `None` | Added to run metadata |
| `session_id` | `str \| None` | `None` | Added to run metadata |

Export failures are logged and swallowed — a LangSmith outage never breaks an agent run.

### Running Multiple Exporters

All exporters are independent EventBus subscribers — OTel, Langfuse, LangSmith,
and `TracingSubscriber` can run simultaneously on the same bus:

```python
bus = InMemoryEventBus()
OTelExporter(bus, tracer_provider=provider).attach()
LangfuseExporter(bus).attach()
LangSmithExporter(bus).attach()
```

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
