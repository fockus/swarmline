# API Reference

Complete reference for all public classes, methods, protocols, and types in swarmline.

## Agent Facade (`swarmline.agent`)

### Agent

High-level facade for interacting with AI agents.

```python
from swarmline import Agent, AgentConfig

agent = Agent(config: AgentConfig)
```

#### Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `query` | `async query(prompt: str) -> Result` | One-shot request. Applies middleware chain, returns collected result |
| `stream` | `async stream(prompt: str) -> AsyncIterator[StreamEvent]` | Streaming request. Yields events as they arrive |
| `conversation` | `conversation(session_id: str \| None = None) -> Conversation` | Create multi-turn conversation |
| `cleanup` | `async cleanup() -> None` | Release resources (runtime, subprocess) |

#### Properties

| Property | Type | Description |
|----------|------|-------------|
| `config` | `AgentConfig` | The agent's configuration |
| `runtime_capabilities` | `RuntimeCapabilities` | Capability descriptor of the selected runtime |

#### Context Manager

```python
async with Agent(config) as agent:
    result = await agent.query("Hello")
# cleanup called automatically
```

---

### AgentConfig

Frozen dataclass with all agent configuration. Only `system_prompt` is required.

```python
from swarmline import AgentConfig
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `system_prompt` | `str` | **required** | System prompt for the agent |
| `model` | `str` | `"sonnet"` | Model alias or full ID |
| `runtime` | `str` | `"claude_sdk"` | Runtime: `"thin"` \| `"claude_sdk"` \| `"deepagents"` \| `"cli"` \| `"openai_agents"` \| `"pi_sdk"` |
| `tools` | `tuple[ToolDefinition, ...]` | `()` | Tools from `@tool` decorator |
| `middleware` | `tuple[Middleware, ...]` | `()` | Middleware chain |
| `mcp_servers` | `dict[str, Any]` | `{}` | Remote MCP server configs |
| `hooks` | `HookRegistry \| None` | `None` | Lifecycle hooks |
| `max_turns` | `int \| None` | `None` | Max conversation turns |
| `max_budget_usd` | `float \| None` | `None` | Cost budget limit |
| `output_format` | `dict[str, Any] \| None` | `None` | JSON Schema for structured output |
| `cwd` | `str \| None` | `None` | Working directory for tools |
| `env` | `dict[str, str]` | `{}` | Environment variables |
| `betas` | `tuple[str, ...]` | `()` | SDK beta features |
| `sandbox` | `dict[str, Any] \| None` | `None` | SDK sandbox config |
| `max_thinking_tokens` | `int \| None` | `None` | Extended thinking token limit |
| `fallback_model` | `str \| None` | `None` | Fallback model on failure |
| `permission_mode` | `str` | `"bypassPermissions"` | SDK permission mode |
| `setting_sources` | `tuple[str, ...]` | `()` | SDK setting sources |
| `runtime_options` | runtime-specific dataclass | `None` | Typed options such as `CliConfig` or `PiSdkOptions` |
| `feature_mode` | `str` | `"portable"` | `"portable"` \| `"hybrid"` \| `"native_first"` |
| `require_capabilities` | `CapabilityRequirements \| None` | `None` | Fail-fast capability check |
| `allow_native_features` | `bool` | `False` | Allow runtime-native features |
| `native_config` | `dict[str, Any]` | `{}` | Runtime-specific extra config |

#### Properties

| Property | Type | Description |
|----------|------|-------------|
| `resolved_model` | `str` | Full model name after alias resolution |

---

### Result

Frozen dataclass returned by `query()` and `conversation.say()`.

```python
from swarmline.agent import Result
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `text` | `str` | `""` | Response text |
| `session_id` | `str \| None` | `None` | Session identifier |
| `total_cost_usd` | `float \| None` | `None` | Total cost of the request |
| `usage` | `dict[str, Any] \| None` | `None` | Token usage (`input_tokens`, `output_tokens`) |
| `structured_output` | `Any` | `None` | Parsed structured output (if `output_format` set) |
| `error` | `str \| None` | `None` | Error message (if failed) |

| Property | Type | Description |
|----------|------|-------------|
| `ok` | `bool` | `True` if `error is None` |

---

### Conversation

Multi-turn dialog management with history tracking.

```python
conv = agent.conversation(session_id="optional-id")
```

| Method | Signature | Description |
|--------|-----------|-------------|
| `say` | `async say(prompt: str) -> Result` | Send message, get response |
| `stream` | `async stream(prompt: str) -> AsyncIterator[StreamEvent]` | Stream a response |
| `close` | `async close() -> None` | Release conversation resources |

| Property | Type | Description |
|----------|------|-------------|
| `session_id` | `str` | Unique session identifier |
| `history` | `list[Message]` | Accumulated messages (copy) |

Supports async context manager (`async with agent.conversation() as conv`).

Runtime behavior:
- **claude_sdk**: warm subprocess, continues conversation natively
- **thin/deepagents**: accumulated messages sent each turn

---

### @tool Decorator

Define tools with automatic JSON Schema inference from type hints.

```python
from swarmline import tool

@tool(name="my_tool", description="Description for LLM", schema=None)
async def my_tool(param: str) -> str:
    return "result"
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | required | Unique tool name |
| `description` | `str` | required | Description for the LLM |
| `schema` | `dict[str, Any] \| None` | `None` | Explicit JSON Schema (auto-inferred if `None`) |

#### Auto-Inferred Type Mapping

| Python Type | JSON Schema Type |
|-------------|-----------------|
| `str` | `"string"` |
| `int` | `"integer"` |
| `float` | `"number"` |
| `bool` | `"boolean"` |
| `T \| None = None` | not in `required` |

#### ToolDefinition

Attached to decorated functions as `fn.__tool_definition__`:

```python
td = my_tool.__tool_definition__
td.name          # "my_tool"
td.description   # "Description for LLM"
td.parameters    # {"type": "object", "properties": {...}, "required": [...]}
td.handler       # async function reference
td.to_tool_spec() # ToolSpec for runtime
```

---

### Middleware

Base class for request/response interceptors.

```python
from swarmline.agent import Middleware

class MyMiddleware(Middleware):
    async def before_query(self, prompt: str, config: AgentConfig) -> str:
        return prompt  # can modify prompt; raise to block

    async def after_result(self, result: Result) -> Result:
        return result  # can modify result

    def get_hooks(self) -> HookRegistry | None:
        return None  # optional lifecycle hooks
```

Execution order:
- `before_query`: mw1 → mw2 → mw3 (in order)
- `after_result`: mw1 → mw2 → mw3 (in order)

#### CostTracker

```python
from swarmline.agent import CostTracker

tracker = CostTracker(budget_usd=5.0)
tracker.total_cost_usd  # float — accumulated cost
tracker.reset()         # reset counter
# Raises BudgetExceededError when cost > budget
```

#### SecurityGuard

```python
from swarmline.agent import SecurityGuard

guard = SecurityGuard(block_patterns=["password", "secret"])
# Blocks tool inputs containing any of the patterns via PreToolUse hook
```

---

## Stream Events

Events yielded by `agent.stream()` and `conversation.stream()`:

| Type | Attributes | Description |
|------|-----------|-------------|
| `text_delta` | `text: str` | Incremental text from the model |
| `tool_use_start` | `tool_name: str`, `tool_input: dict` | Tool call initiated |
| `tool_use_result` | `tool_result: str` | Tool call completed |
| `done` | `text: str`, `session_id`, `total_cost_usd`, `usage`, `structured_output` | Final result |
| `error` | `text: str` | Error occurred |

---

## Runtime Types (`swarmline.runtime.types`)

### Message

Universal message for agent runtimes.

```python
from swarmline.runtime.types import Message

msg = Message(role="user", content="Hello")
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `role` | `str` | required | `"user"` \| `"assistant"` \| `"tool"` \| `"system"` |
| `content` | `str` | required | Message content |
| `name` | `str \| None` | `None` | Tool name (for `role="tool"`) |
| `tool_calls` | `list[dict] \| None` | `None` | Tool call requests |
| `metadata` | `dict \| None` | `None` | Extra metadata |

Methods: `to_dict()`, `Message.from_memory_message(mm)`.

### ToolSpec

Tool description for runtime.

```python
from swarmline.runtime.types import ToolSpec

spec = ToolSpec(name="my_tool", description="...", parameters={...}, is_local=True)
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | required | Tool name (e.g., `"mcp__server__tool"`) |
| `description` | `str` | required | Description for the LLM |
| `parameters` | `dict[str, Any]` | required | JSON Schema |
| `is_local` | `bool` | `False` | `True` for locally executed tools |

### RuntimeEvent

Unified streaming event from runtimes.

| Type | Data Keys | Description |
|------|-----------|-------------|
| `assistant_delta` | `text` | Streaming text fragment |
| `status` | `text` | Status message |
| `tool_call_started` | `name`, `correlation_id`, `args` | Tool call began |
| `tool_call_finished` | `name`, `correlation_id`, `ok`, `result_summary` | Tool call completed |
| `final` | `text`, `new_messages`, `metrics`, `session_id`, `total_cost_usd`, `usage`, `structured_output` | Turn completed |
| `error` | `kind`, `message`, `recoverable` | Error occurred |

Static factory methods: `RuntimeEvent.assistant_delta(text)`, `RuntimeEvent.status(text)`, `RuntimeEvent.tool_call_started(name, args)`, `RuntimeEvent.tool_call_finished(name, correlation_id, ok, summary)`, `RuntimeEvent.final(text, ...)`, `RuntimeEvent.error(error_data)`.

### RuntimeConfig

```python
from swarmline.runtime.types import RuntimeConfig

config = RuntimeConfig(
    runtime_name="thin",              # thin | claude_sdk | deepagents | cli | openai_agents | pi_sdk
    model="claude-sonnet-4-20250514", # or alias
    max_iterations=6,                 # ReAct loop limit
    max_tool_calls=8,                 # tool calls per turn limit
    max_model_retries=2,              # retry on bad output
    base_url=None,                    # custom API endpoint
    feature_mode="portable",          # portable | hybrid | native_first
    required_capabilities=None,       # CapabilityRequirements
    allow_native_features=False,      # allow runtime-specific features
    native_config={},                 # runtime-specific extra config
)
```

### RuntimeErrorData

Typed error for runtime events.

| Field | Type | Description |
|-------|------|-------------|
| `kind` | `str` | Error kind (see below) |
| `message` | `str` | Human-readable message |
| `recoverable` | `bool` | Whether the error is recoverable |
| `details` | `dict \| None` | Extra details |

Error kinds: `runtime_crash`, `bad_model_output`, `loop_limit`, `budget_exceeded`, `mcp_timeout`, `tool_error`, `dependency_missing`, `capability_unsupported`.

### TurnMetrics

```python
from swarmline.runtime.types import TurnMetrics
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `latency_ms` | `int` | `0` | Turn latency |
| `iterations` | `int` | `0` | ReAct iterations |
| `tool_calls_count` | `int` | `0` | Number of tool calls |
| `tokens_in` | `int` | `0` | Input tokens |
| `tokens_out` | `int` | `0` | Output tokens |
| `model` | `str` | `""` | Model used |

---

## Runtime Capabilities (`swarmline.runtime.capabilities`)

### RuntimeCapabilities

Describes what a runtime supports.

```python
from swarmline.runtime.capabilities import get_runtime_capabilities

caps = get_runtime_capabilities("claude_sdk")
caps.tier              # "full"
caps.supports_mcp      # True
caps.enabled_flags()   # frozenset({"mcp", "resume", "interrupt"})
```

| Runtime | Tier | MCP | Resume | Interrupt | Provider Override |
|---------|------|-----|--------|-----------|-------------------|
| `claude_sdk` | `full` | Yes | Yes | Yes | No |
| `deepagents` | `full` | No | Yes | No | Yes |
| `thin` | `light` | Yes | No | No | Yes |
| `cli` | `light` | No | No | No | No |
| `openai_agents` | `full` | Yes | No | No | Yes |
| `pi_sdk` | `full` | No | Yes | Yes | Yes |

### CapabilityRequirements

Declare what your application needs. Fail-fast validation at config time.

```python
from swarmline.runtime.capabilities import CapabilityRequirements

reqs = CapabilityRequirements(
    tier="full",
    flags=("mcp", "resume"),
)
```

---

## Model Registry (`swarmline.runtime.types`)

### resolve_model_name

```python
from swarmline.runtime.types import resolve_model_name

resolve_model_name("sonnet")   # "claude-sonnet-4-20250514"
resolve_model_name("opus")     # "claude-opus-4-20250514"
resolve_model_name("haiku")    # "claude-haiku-3-20250307"
resolve_model_name("gpt-4o")   # "gpt-4o"
resolve_model_name("4o-mini")  # "gpt-4o-mini"
resolve_model_name("o3")       # "o3"
resolve_model_name("gemini")   # "gemini-2.5-pro"
resolve_model_name("r1")       # "deepseek-reasoner"
resolve_model_name(None)       # default model
```

Models and aliases are defined in `swarmline/runtime/models.yaml`.

---

## Memory Protocols (`swarmline.memory`)

All 8 protocols follow ISP (<=5 methods each). Three providers implement all 8: `InMemoryMemoryProvider`, `PostgresMemoryProvider`, `SQLiteMemoryProvider`.

### MessageStore

```python
class MessageStore(Protocol):
    async def save_message(self, user_id: str, topic_id: str, role: str, content: str, tool_calls: list[dict] | None = None) -> None: ...
    async def get_messages(self, user_id: str, topic_id: str, limit: int = 50) -> list[MemoryMessage]: ...
    async def count_messages(self, user_id: str, topic_id: str) -> int: ...
    async def delete_messages_before(self, user_id: str, topic_id: str, keep_last: int = 10) -> int: ...
```

### FactStore

```python
class FactStore(Protocol):
    async def upsert_fact(self, user_id: str, key: str, value: str, source: str = "") -> None: ...
    async def get_facts(self, user_id: str) -> dict[str, str]: ...
```

### GoalStore

```python
class GoalStore(Protocol):
    async def save_goal(self, user_id: str, topic_id: str, data: dict) -> None: ...
    async def get_active_goal(self, user_id: str, topic_id: str) -> dict | None: ...
```

### SummaryStore

```python
class SummaryStore(Protocol):
    async def save_summary(self, user_id: str, topic_id: str, summary: str, messages_covered: int) -> None: ...
    async def get_summary(self, user_id: str, topic_id: str) -> str | None: ...
```

### UserStore

```python
class UserStore(Protocol):
    async def ensure_user(self, external_id: str) -> str: ...
    async def get_user_profile(self, user_id: str) -> dict | None: ...
```

### SessionStateStore

```python
class SessionStateStore(Protocol):
    async def save_session_state(self, user_id: str, topic_id: str, role_id: str, active_skill_ids: list[str], prompt_hash: str) -> None: ...
    async def get_session_state(self, user_id: str, topic_id: str) -> dict | None: ...
```

### PhaseStore

```python
class PhaseStore(Protocol):
    async def save_phase_state(self, user_id: str, phase: str, notes: str = "") -> None: ...
    async def get_phase_state(self, user_id: str) -> dict | None: ...
```

### ToolEventStore

```python
class ToolEventStore(Protocol):
    async def save_tool_event(self, user_id: str, event_data: dict) -> None: ...
```

---

## Web Protocols (`swarmline.tools.web_protocols`)

### WebProvider

```python
class WebProvider(Protocol):
    async def fetch(self, url: str) -> str: ...
    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]: ...
```

### WebSearchProvider

```python
class WebSearchProvider(Protocol):
    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]: ...
```

### WebFetchProvider

```python
class WebFetchProvider(Protocol):
    async def fetch(self, url: str) -> str: ...
```

### SearchResult

```python
@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
```

See [Web Tools](web-tools.md) for provider implementations.

---

## Hooks (`swarmline.hooks`)

### HookRegistry

```python
from swarmline.hooks import HookRegistry

registry = HookRegistry()
registry.on_pre_tool_use(callback, matcher="Bash")
registry.on_post_tool_use(callback)
registry.on_stop(callback)
registry.on_user_prompt(callback)
```

Events: `PreToolUse`, `PostToolUse`, `Stop`, `UserPromptSubmit`.

### SDK Bridge

```python
from swarmline.hooks import registry_to_sdk_hooks

sdk_hooks = registry_to_sdk_hooks(registry)
# Pass to Claude Agent SDK options
```

---

## Observability (`swarmline.observability`)

### AgentLogger

```python
from swarmline.observability import AgentLogger, configure_logging

configure_logging(level="info", fmt="json")
logger = AgentLogger(component="my_app")

logger.session_created(user_id="u1", topic_id="t1", role_id="coach")
logger.turn_start(user_id="u1", topic_id="t1")
logger.tool_call(tool_name="get_deposits", latency_ms=450)
logger.tool_policy_event(tool_name="Bash", allowed=False, reason="ALWAYS_DENIED")
logger.turn_complete(user_id="u1", topic_id="t1", role_id="coach", prompt_hash="abc123")
```

---

## Resilience (`swarmline.resilience`)

### CircuitBreaker

```python
from swarmline.resilience import CircuitBreaker

cb = CircuitBreaker(failure_threshold=3, recovery_timeout_s=60)

if cb.can_execute():
    try:
        result = await call_service()
        cb.record_success()
    except Exception:
        cb.record_failure()
```

States: `closed` (normal) → `open` (blocking) → `half_open` (testing recovery).

---

## Bootstrap (`swarmline.bootstrap`)

### SwarmlineStack

```python
from swarmline.bootstrap.stack import SwarmlineStack

stack = SwarmlineStack.create(
    prompts_dir=Path("prompts"),
    skills_dir=Path("skills"),
    project_root=Path("."),
    runtime_config=RuntimeConfig(...),
    sandbox_provider=...,           # SandboxProvider | None
    web_provider=...,               # WebProvider | None
    todo_provider=...,              # TodoProvider | None
    memory_bank_provider=...,       # MemoryBankProvider | None
    plan_manager=...,               # PlanManager | None
    thinking_enabled=True,          # bool
    allowed_system_tools={...},     # set[str]
    tool_budget_config=...,         # ToolBudgetConfig | None
    escalate_roles={...},           # set[str]
    local_tool_resolver=...,        # object | None
)
```

Returns a `SwarmlineStack` with:

| Attribute | Type | Description |
|-----------|------|-------------|
| `capability_specs` | `dict[str, ToolSpec]` | All capability tools |
| `capability_executors` | `dict[str, Callable]` | Tool executors |
| `tool_policy` | `DefaultToolPolicy` | Configured tool policy |
| `context_builder` | `DefaultContextBuilder` | System prompt builder |
| `runtime_factory` | `RuntimeFactory` | Runtime factory |
| `skill_registry` | `SkillRegistry` | Loaded MCP skills |
| `role_router` | `KeywordRoleRouter` | Role routing |

---

## Policy (`swarmline.policy`)

### DefaultToolPolicy

```python
from swarmline.policy import DefaultToolPolicy

policy = DefaultToolPolicy(
    allowed_system_tools={"bash", "read"},
    extra_denied={"dangerous_tool"},
)

result = policy.can_use_tool(tool_name, input_data, state)
```

Always denied: `Bash`, `Read`, `Write`, `Edit`, `MultiEdit`, `Glob`, `Grep`, `LS`, `TodoRead`, `TodoWrite`, `WebFetch`, `WebSearch` (and snake_case variants).

### ToolIdCodec

```python
from swarmline.policy import DefaultToolIdCodec

codec = DefaultToolIdCodec()
codec.encode("server", "tool")      # "mcp__server__tool"
codec.extract_server("mcp__s__t")   # "s"
codec.matches("mcp__s__t", "s")     # True
```

---

## Routing (`swarmline.routing`)

### KeywordRoleRouter

```python
from swarmline.routing import KeywordRoleRouter

router = KeywordRoleRouter(
    default_role="coach",
    keyword_map={
        "deposit_advisor": ["deposit", "savings"],
        "credit_advisor": ["credit", "loan"],
    },
)

router.resolve("I want a savings account")  # "deposit_advisor"
router.resolve("Hello")                      # "coach"
router.resolve("...", explicit_role="coach")  # "coach" (explicit wins)
```

---

## Commands (`swarmline.commands`)

### CommandRegistry

```python
from swarmline.commands import CommandRegistry

registry = CommandRegistry()
registry.register(name="help", handler=handler, aliases=["h", "?"], description="Show help")
result = await registry.dispatch("/help", context)
```
