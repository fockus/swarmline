# Migration Guide

This guide has two parts:

- `v1.3.0 → v1.4.0`: secure-by-default stabilization and release sync.
- `v0.5.0 → v1.0.0`: legacy runtime/API migration notes kept for older installs.

---

## v1.3.0 → v1.4.0 (secure-by-default stabilization)

This release tightens the defaults around host execution and unauthenticated HTTP access.
Keep the defaults closed unless you explicitly trust the operator boundary.

### Defaults that changed

- `enable_host_exec=False` for MCP server startup
- `allow_host_execution=False` for `LocalSandboxProvider`
- `allow_unauthenticated_query=False` for `/v1/query`
- `LocalSandboxProvider` is an isolated file and command surface; keep host execution closed unless the calling context is trusted

### Upgrade recipe 1: MCP host exec

If you previously depended on the `swarmline_exec_code` tool, leave host execution closed by default and open it only for trusted operators:

```python
server = create_server(
    ...,
    enable_host_exec=True,
)
```

Use the explicit opt-in only in trusted environments. Keep the default `False` for all public or shared deployments.

### Upgrade recipe 2: LocalSandboxProvider host exec

If you relied on local command execution inside the sandbox, make the opt-in explicit:

```python
sandbox = LocalSandboxProvider(SandboxConfig(
    root_path="/data/sandbox",
    user_id="user-42",
    topic_id="project-7",
    allow_host_execution=True,
))
```

Treat `LocalSandboxProvider` as an isolated file and command surface. Only enable host execution when the calling context is trusted and the filesystem/network boundary is controlled.

### Upgrade recipe 3: Open `/v1/query` intentionally

If you need the HTTP query endpoint to accept unauthenticated traffic, make that a deliberate choice at the serve boundary:

```python
app = create_app(
    ...,
    allow_unauthenticated_query=True,
)
```

Prefer authenticated access whenever possible. If you intentionally open the route, keep it behind a network boundary, document the operator intent, and monitor access separately.

---

## Legacy: v0.5.0 to v1.0.0

This legacy section covers the original core migration from Swarmline 0.5.0 to 1.0.0-core.

## 1. Breaking Changes

### 1.1 RuntimePort renamed to AgentRuntime

The primary runtime protocol has been renamed. `RuntimePort` still exists but is
deprecated and will be removed in v2.0.

| v0.5.0 | v1.0.0 |
|--------|--------|
| `swarmline.protocols.RuntimePort` | `swarmline.runtime.base.AgentRuntime` |

**Old code:**

```python
from swarmline.protocols import RuntimePort

class MyRuntime:
    """Implements RuntimePort."""
    @property
    def is_connected(self) -> bool: ...
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    def stream_reply(self, user_text: str) -> AsyncIterator[Any]: ...
```

**New code:**

```python
from swarmline.runtime.base import AgentRuntime
# or: from swarmline import AgentRuntime

class MyRuntime:
    """Implements AgentRuntime."""
    def run(
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        config: RuntimeConfig | None = None,
        mode_hint: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]: ...

    async def cleanup(self) -> None: ...
    def cancel(self) -> None: ...
```

Key differences in the new contract:

- `AgentRuntime.run()` replaces `stream_reply()`. It accepts structured
  `messages`, `system_prompt`, `active_tools`, and optional `config`/`mode_hint`.
- `cleanup()` replaces `disconnect()`. There is no `connect()` -- runtimes
  initialize on construction or on first `run()` call.
- `cancel()` is new -- cooperative cancellation support.
- `AgentRuntime` supports async context manager (`async with runtime as r:`).
- The runtime no longer owns connection state (`is_connected` is removed).

### 1.2 Protocols package restructured (ISP split)

`protocols.py` (single file) has been split into a package with dedicated
modules. All protocols are still re-exported from `swarmline.protocols` for
backward compatibility.

| Module | Protocols |
|--------|-----------|
| `swarmline.protocols.memory` | `MessageStore`, `FactStore`, `SummaryStore`, `GoalStore`, `SessionStateStore`, `UserStore`, `PhaseStore`, `ToolEventStore`, `SummaryGenerator` |
| `swarmline.protocols.session` | `SessionFactory`, `SessionLifecycle`, `SessionManager`, `SessionRehydrator` |
| `swarmline.protocols.routing` | `ContextBuilder`, `ModelSelector`, `RoleRouter`, `RoleSkillsProvider` |
| `swarmline.protocols.tools` | `LocalToolResolver`, `ToolIdCodec` |
| `swarmline.protocols.runtime` | `RuntimePort` (deprecated), re-exports `AgentRuntime` |
| `swarmline.protocols.multi_agent` | `AgentTool`, `TaskQueue`, `AgentRegistry` |

**Action required:** If you imported from `swarmline.protocols`, no changes are
needed -- all names are re-exported from `swarmline.protocols.__init__`. If you
imported directly from `swarmline.protocols` as a single-file module in a
non-standard way, update to the package import.

### 1.3 RuntimeEvent changes

`RuntimeEvent` gains new static factory methods and typed accessors. The event
type set has expanded:

| New event type | Purpose |
|---------------|---------|
| `native_notice` | Runtime-specific semantics notice |
| `user_input_requested` | Runtime requests human input |

New `RuntimeEvent` properties (typed accessors, no need to dig into `.data`):

- `.text` -- text content for `assistant_delta`, `status`, `final` events
- `.tool_name` -- tool name for `tool_call_started`/`tool_call_finished`
- `.is_final`, `.is_error`, `.is_text` -- type guards
- `.structured_output` -- parsed structured output from `final` events

New static factory methods:

- `RuntimeEvent.assistant_delta(text)`, `.status(text)`, `.final(...)`,
  `.error(error)`, `.tool_call_started(...)`, `.tool_call_finished(...)`,
  `.approval_required(...)`, `.user_input_requested(...)`, `.native_notice(...)`

**Action required:** If you constructed `RuntimeEvent` manually, switch to
factory methods. If you read `event.data["text"]`, you can now use `event.text`.
Existing `event.data` access still works.

### 1.4 RuntimeConfig new fields

`RuntimeConfig` has several new fields. Existing code using only the old fields
will work without changes.

| New field | Type | Default | Purpose |
|-----------|------|---------|---------|
| `output_type` | `type \| None` | `None` | Pydantic model for structured output |
| `output_format` | `dict \| None` | `None` | JSON Schema (auto-generated from `output_type`) |
| `cancellation_token` | `CancellationToken \| None` | `None` | Cooperative cancellation |
| `cost_budget` | `CostBudget \| None` | `None` | Per-session cost limit |
| `input_guardrails` | `list` | `[]` | Pre-LLM guardrail checks |
| `output_guardrails` | `list` | `[]` | Post-LLM guardrail checks |
| `input_filters` | `list` | `[]` | Pre-LLM input transformations |
| `retry_policy` | `RetryPolicy \| None` | `None` | Retry with backoff |
| `event_bus` | `EventBus \| None` | `None` | Pub-sub for runtime events |
| `tracer` | `Tracer \| None` | `None` | Span-based tracing |
| `retriever` | `Retriever \| None` | `None` | RAG context injection |

### 1.5 RuntimeErrorData new error kinds

New error kinds added to `RUNTIME_ERROR_KINDS`:

- `cancelled` -- operation cancelled via `CancellationToken`
- `guardrail_tripwire` -- guardrail check failed
- `retry` -- retrying LLM call after transient failure

Existing error handling code will still work; these are additive.

---

## 2. New Features

### 2.1 Structured Output

Extract typed responses from LLM output using Pydantic models.

```python
from pydantic import BaseModel
from swarmline import Agent, AgentConfig

class SentimentResult(BaseModel):
    sentiment: str
    confidence: float

agent = Agent(AgentConfig(
    system_prompt="Classify sentiment.",
    runtime="thin",
    output_format=SentimentResult.model_json_schema(),
))
result = await agent.query("I love this product!")
# result.structured_output -> SentimentResult instance
```

See [Structured Output docs](structured-output.md) for details on `output_type`,
validation retries, and `max_model_retries`.

### 2.2 @tool Decorator

Define tools with automatic JSON Schema inference from type hints and docstrings.

```python
from swarmline import tool

@tool
def get_weather(city: str, units: str = "celsius") -> str:
    """Get current weather for a city.

    Args:
        city: The city name to look up.
        units: Temperature units (celsius or fahrenheit).
    """
    return f"Weather in {city}: 22 {units}"
```

`ToolDefinition.to_tool_spec()` bridges decorator-defined tools to `ToolSpec`
for runtime compatibility.

See [Tools and Skills docs](tools-and-skills.md).

### 2.3 Runtime Registry

Thread-safe, extensible runtime registry with plugin discovery via entry points.

```python
from swarmline.runtime.registry import RuntimeRegistry

# Register a custom runtime
RuntimeRegistry.register("my_runtime", MyRuntimeFactory)

# Use it
agent = Agent(AgentConfig(system_prompt="...", runtime="my_runtime"))
```

See [Runtime Registry docs](runtime-registry.md).

### 2.4 Cost Budget

Per-session budget enforcement with bundled pricing data.

```python
from swarmline.runtime.cost import CostBudget, CostTracker
from swarmline.runtime.types import RuntimeConfig

budget = CostBudget(max_usd=1.0, action_on_exceed="error")
config = RuntimeConfig(cost_budget=budget)
```

### 2.5 Guardrails and CallerPolicy

Input/output guardrails with parallel execution. Built-in guards include
`ContentLengthGuardrail`, `RegexGuardrail`, and `CallerAllowlistGuardrail`.

```python
from swarmline.guardrails import ContentLengthGuardrail, RegexGuardrail

config = RuntimeConfig(
    input_guardrails=[ContentLengthGuardrail(max_chars=10000)],
    output_guardrails=[RegexGuardrail(deny_patterns=[r"(?i)password"])],
)
```

### 2.6 Input Filters

Pre-process user input before LLM calls. Built-in filters: `MaxTokensFilter`,
`SystemPromptInjector`.

```python
from swarmline.filters import MaxTokensFilter, SystemPromptInjector

config = RuntimeConfig(
    input_filters=[
        MaxTokensFilter(max_tokens=4096),
        SystemPromptInjector(suffix="Always respond in JSON."),
    ],
)
```

### 2.7 Retry and Fallback

Resilient LLM calls with configurable retry policies and model fallback chains.

```python
from swarmline.resilience import ExponentialBackoff, ModelFallbackChain

config = RuntimeConfig(
    retry_policy=ExponentialBackoff(max_retries=3, base_delay=1.0),
)
```

### 2.8 Session Backends

Pluggable session persistence with `SessionBackend` protocol. Built-in:
`InMemorySessionBackend`, `SqliteSessionBackend`.

See [Sessions docs](sessions.md).

### 2.9 Event Bus and Tracing

Pub-sub event bus for runtime observability and span-based tracing.

```python
from swarmline.observability.event_bus import InMemoryEventBus
from swarmline.observability.tracing import ConsoleTracer, TracingSubscriber

bus = InMemoryEventBus()
tracer = ConsoleTracer()
TracingSubscriber(bus, tracer)  # auto-subscribes

config = RuntimeConfig(event_bus=bus, tracer=tracer)
```

ThinRuntime emits `llm_call_start/end` and `tool_call_start/end` events.

See [Observability docs](observability.md).

### 2.10 UI Projection

Transform runtime event streams into UI-friendly blocks for frontend rendering.

```python
from swarmline.ui.projection import ChatProjection, project_stream

projection = ChatProjection()
async for ui_state in project_stream(event_stream, projection):
    send_to_frontend(ui_state.to_dict())
```

Block types: `TextBlock`, `ToolCallBlock`, `ToolResultBlock`, `ErrorBlock`.

See [UI Projection docs](ui-projection.md).

### 2.11 RAG / Retriever

Automatic context injection via `Retriever` protocol and `RagInputFilter`.

```python
from swarmline.rag import SimpleRetriever, Document

retriever = SimpleRetriever(documents=[
    Document(content="Swarmline supports 3 runtimes.", metadata={"source": "docs"}),
])
config = RuntimeConfig(retriever=retriever)
```

See [RAG docs](rag.md).

### 2.12 Multi-Agent Coordination

Agent-as-tool pattern, task queues, and agent registries for multi-agent systems.

- `AgentTool` protocol -- expose any runtime as a callable tool
- `create_agent_tool_spec()` / `execute_agent_tool()` utility functions
- `TaskQueue` protocol with `InMemoryTaskQueue` and `SqliteTaskQueue`
- `AgentRegistry` protocol with `InMemoryAgentRegistry`

See [Multi-Agent docs](multi-agent.md).

### 2.13 CLI Agent Runtime

Subprocess-based runtime for external CLI agents (Claude Code, custom tools).

```python
agent = Agent(AgentConfig(system_prompt="...", runtime="cli"))
```

Registered in `RuntimeRegistry` as `"cli"`. Supports NDJSON parsing with
`ClaudeNdjsonParser` and `GenericNdjsonParser`.

See [CLI Runtime docs](cli-runtime.md).

### 2.14 Cancellation

Cooperative cancellation with callback support.

```python
from swarmline.runtime.cancellation import CancellationToken

token = CancellationToken()
config = RuntimeConfig(cancellation_token=token)

# Later, from another task:
token.cancel()
```

### 2.15 Memory Scopes

Namespace isolation for memory operations.

```python
from swarmline.memory.scopes import MemoryScope

key = MemoryScope.AGENT.scoped_key("agent-1", "preferences")
# -> "agent:agent-1:preferences"
```

---

## 3. Deprecations

| Deprecated | Replacement | Removal target |
|------------|-------------|----------------|
| `RuntimePort` protocol (`swarmline.protocols.runtime`) | `AgentRuntime` (`swarmline.runtime.base`) | v2.0.0 |
| `RuntimePort.stream_reply()` | `AgentRuntime.run()` | v2.0.0 |
| `RuntimePort.connect()` / `disconnect()` | `AgentRuntime` context manager / `cleanup()` | v2.0.0 |
| `RuntimePort.is_connected` property | Removed (no replacement) | v2.0.0 |
| `protocols.py` single-file import path | `swarmline.protocols` package (backward-compatible re-exports remain) | v2.0.0 |

---

## 4. Quick Upgrade Checklist

Follow these steps to upgrade from v0.5.0 to v1.0.0:

### Step 1: Update the dependency

```bash
pip install swarmline>=1.0.0
```

### Step 2: Replace RuntimePort with AgentRuntime

Search your codebase for `RuntimePort` references:

```bash
grep -rn "RuntimePort" src/
```

Replace with `AgentRuntime`:

```python
# Before
from swarmline.protocols import RuntimePort

# After
from swarmline import AgentRuntime
# or: from swarmline.runtime.base import AgentRuntime
```

If you have custom runtime implementations, update them to implement the
`AgentRuntime` protocol (see section 1.1 above for the method signatures).

### Step 3: Update custom runtime implementations

If you implemented `RuntimePort`:

1. Remove `is_connected` property, `connect()`, and `disconnect()`.
2. Rename `stream_reply(user_text)` to `run(*, messages, system_prompt, active_tools, config, mode_hint)`.
3. Return/yield `RuntimeEvent` objects (use factory methods).
4. Add `cleanup()` and `cancel()` methods.
5. Optionally implement `__aenter__`/`__aexit__` for context manager support.

### Step 4: Update RuntimeEvent usage

If you construct `RuntimeEvent` instances manually, switch to factory methods:

```python
# Before
event = RuntimeEvent(type="assistant_delta", data={"text": chunk})

# After
event = RuntimeEvent.assistant_delta(chunk)
```

If you read event data:

```python
# Before
text = event.data.get("text", "")

# After (preferred)
text = event.text
```

### Step 5: Update RuntimeConfig (if subclassed or extended)

If you pass `RuntimeConfig` directly, review the new fields. No changes required
if you only use the fields that existed in v0.5.0. New fields all have safe
defaults.

### Step 6: Adopt new features (optional)

These are additive and do not require changes to existing code:

- Add `output_type` to `RuntimeConfig` for structured output.
- Add guardrails and input filters to `RuntimeConfig`.
- Set up `CostBudget` for cost tracking.
- Configure `EventBus` and `Tracer` for observability.
- Use `RuntimeRegistry` to register custom runtimes.

### Step 7: Run tests

```bash
pytest
ruff check src/ tests/
mypy src/swarmline/
```

Verify that all tests pass and there are no import errors or type check failures
related to the renamed protocols.

---

## Need Help?

- [Getting Started](getting-started.md)
- [Architecture Overview](architecture.md)
- [API Reference](api-reference.md)
- [Examples](examples.md)
- [Full Changelog](https://github.com/fockus/swarmline/blob/main/CHANGELOG.md)
