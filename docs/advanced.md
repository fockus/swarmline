# Advanced Features

## Hooks System

Hooks intercept agent lifecycle events for security enforcement, logging, and custom logic.

### HookRegistry

Register callbacks for four event types:

```python
from cognitia.hooks import HookRegistry

registry = HookRegistry()

# PreToolUse — block or modify tool calls before execution
async def block_bash(tool_name: str, tool_input: dict, **kwargs):
    if tool_name == "Bash":
        return {"decision": "deny", "reason": "Bash is not allowed"}
    return None  # allow

registry.on_pre_tool_use(block_bash, matcher="Bash")

# PostToolUse — audit, log, or transform results after execution
async def log_tool(tool_name: str, **kwargs):
    print(f"Tool called: {tool_name}")
    return None

registry.on_post_tool_use(log_tool)

# Stop — hook when agent finishes
async def on_stop(**kwargs):
    print("Agent stopped")

registry.on_stop(on_stop)

# UserPromptSubmit — intercept user messages before processing
async def validate_prompt(**kwargs):
    print("User prompt submitted")

registry.on_user_prompt(validate_prompt)
```

**Events reference:**

| Event | Method | `matcher` param | Fires when |
|-------|--------|-----------------|------------|
| `PreToolUse` | `on_pre_tool_use(cb, matcher="")` | Tool name filter | Before tool execution |
| `PostToolUse` | `on_post_tool_use(cb, matcher="")` | Tool name filter | After tool execution |
| `Stop` | `on_stop(cb)` | N/A | Agent stops |
| `UserPromptSubmit` | `on_user_prompt(cb)` | N/A | User sends message |

### Merging Registries (v0.4.0+)

Combine hooks from multiple sources (e.g., base security + per-role hooks):

```python
security_hooks = HookRegistry()
security_hooks.on_pre_tool_use(block_bash, matcher="Bash")

role_hooks = HookRegistry()
role_hooks.on_post_tool_use(log_tool)

# merge() returns a NEW registry with hooks from both
combined = security_hooks.merge(role_hooks)
# Original registries are unchanged (immutable merge)
```

### SDK Bridge

Convert `HookRegistry` to Claude Agent SDK `HookMatcher` format:

```python
from cognitia.hooks import registry_to_sdk_hooks

sdk_hooks = registry_to_sdk_hooks(registry)
# Returns: dict[str, list[HookMatcher]] | None
# Pass to ClaudeAgentOptions.hooks
```

The bridge wraps cognitia callbacks (`(**kwargs) -> dict | None`) into SDK-compatible signatures (`(hook_input, tool_use_id, context) -> HookJSONOutput`). A `None` return from cognitia callbacks maps to `{"continue_": True}`.

!!! note
    Importing `registry_to_sdk_hooks` requires `claude_agent_sdk` as an optional dependency. Without it, `from cognitia.hooks import registry_to_sdk_hooks` raises `ImportError`.

---

## Resilience

### CircuitBreaker

Protects against cascading failures from flaky MCP servers. One breaker per `server_id`.

**State machine:** `CLOSED` (normal) &rarr; `OPEN` (blocking) &rarr; `HALF_OPEN` (probe) &rarr; `CLOSED`

```python
from cognitia.resilience import CircuitBreaker, CircuitState

cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=30.0)

# Before calling an MCP server
if cb.allow_request():
    try:
        result = await call_mcp_server()
        cb.record_success()  # HALF_OPEN -> CLOSED, resets failure count
    except Exception:
        cb.record_failure()  # After 3 consecutive failures -> OPEN

# Check state
assert cb.state == CircuitState.CLOSED
```

**Behavior by state:**

| State | `allow_request()` | On success | On failure |
|-------|-------------------|------------|------------|
| `CLOSED` | `True` | Reset failures | Increment; if &ge; threshold &rarr; `OPEN` |
| `OPEN` | `False` (until cooldown expires, then &rarr; `HALF_OPEN`) | — | — |
| `HALF_OPEN` | `True` (one probe) | &rarr; `CLOSED` | &rarr; `OPEN` |

### CircuitBreakerRegistry

Manages per-server breakers with shared configuration:

```python
from cognitia.resilience import CircuitBreakerRegistry

registry = CircuitBreakerRegistry(failure_threshold=3, cooldown_seconds=60.0)

# Get-or-create breaker for a specific MCP server
breaker = registry.get("finuslugi-mcp")

if breaker.allow_request():
    try:
        result = await call_server("finuslugi-mcp")
        breaker.record_success()
    except Exception:
        breaker.record_failure()
```

---

## Session Management

### InMemorySessionManager

Manages concurrent agent sessions with TTL eviction and per-session locking:

```python
from cognitia.session import InMemorySessionManager, SessionKey, SessionState

manager = InMemorySessionManager(ttl_seconds=900.0)  # 15 min TTL

# Register a session
key = SessionKey(user_id="user_1", topic_id="topic_1")
state = SessionState(
    key=key,
    runtime=my_runtime,        # AgentRuntime instance
    runtime_config=my_config,
    system_prompt="You are a helpful assistant",
    role_id="coach",
    active_skill_ids=["finuslugi"],
)
manager.register(state)

# Retrieve session (returns None if TTL expired)
state = manager.get(key)

# Run a turn (acquires per-session asyncio.Lock)
async for event in manager.run_turn(
    key,
    messages=messages,
    system_prompt=system_prompt,
    active_tools=tools,
):
    print(event.type, event.data)

# Legacy streaming API (adapter path)
async for event in manager.stream_reply(key, "Hello"):
    print(event.type, event.text)

# Update role mid-session
manager.update_role(key, role_id="credit_advisor", skill_ids=["credit-mcp"])

# Cleanup
await manager.close(key)       # Close single session
await manager.close_all()      # Close all sessions
```

**Key features:**

- **TTL eviction**: sessions expire after `ttl_seconds` of inactivity
- **Per-session locking**: `asyncio.Lock` ensures sequential turn processing per session
- **Dual runtime path**: supports both new `AgentRuntime.run()` and legacy `adapter.stream_reply()`
- **Delegation tracking**: `delegated_from`, `delegation_turn_count` for orchestrator role handoffs

### SessionRehydrator

Restore session state after process restart from persistent storage:

```python
from cognitia.session import DefaultSessionRehydrator

rehydrator = DefaultSessionRehydrator(
    messages=message_store,     # MessageStore protocol
    summaries=summary_store,    # SummaryStore protocol
    goals=goal_store,           # GoalStore protocol
    sessions=session_store,     # SessionStateStore protocol
    phases=phase_store,         # PhaseStore protocol
    last_n_messages=10,         # How many messages to reload
)

payload = await rehydrator.build_rehydration_payload(turn_context)
```

**Rehydration order** (per architecture &sect;8.4):

1. **Session state** from DB &mdash; `role_id`, `active_skill_ids`, `prompt_hash`
2. **Rolling summary** &mdash; compressed conversation history
3. **Last N messages** &mdash; recent messages for the current topic
4. **Active goal** &mdash; current user goal
5. **Phase state** &mdash; current conversation phase

**Returned payload:**

```python
{
    "role_id": "coach",
    "active_skill_ids": ["finuslugi"],
    "prompt_hash": "a1b2c3d4e5f67890",
    "summary": "User discussed savings options...",
    "last_messages": [...],
    "goal": {"text": "Open a deposit", ...},
    "phase_state": {"phase": "recommendation", ...},
}
```

!!! tip "ISP compliance"
    The rehydrator depends on 5 small protocols (&le;5 methods each) rather than a monolithic memory provider, following the Interface Segregation Principle.

---

## Policy

### ToolPolicy (Default-Deny)

Controls which tools an agent can invoke. Default-deny with explicit allowlists:

```python
from cognitia.policy.tool_policy import DefaultToolPolicy, ToolPolicyInput

policy = DefaultToolPolicy(
    extra_denied={"dangerous_tool"},           # Additional deny-list
    allowed_system_tools={"WebSearch"},         # Override default deny for specific tools
)

state = ToolPolicyInput(
    tool_name="mcp__finuslugi__get_deposits",
    input_data={"currency": "RUB"},
    active_skill_ids=["finuslugi"],
    allowed_local_tools={"mcp__app_tools__calculator"},
)

result = policy.can_use_tool("mcp__finuslugi__get_deposits", {}, state)
# -> PermissionAllow(updated_input={...})

result = policy.can_use_tool("Bash", {}, state)
# -> PermissionDeny(message="Tool 'Bash' is denied by security policy")
```

**Decision logic (in order):**

| Step | Check | Result |
|------|-------|--------|
| 1 | Tool in `ALWAYS_DENIED` | `PermissionDeny` |
| 2 | Tool in `allowed_local_tools` | `PermissionAllow` |
| 3 | Tool in `allowed_system_tools` | `PermissionAllow` |
| 4 | `mcp__*` tool with active skill | `PermissionAllow` |
| 5 | `mcp__*` tool with inactive skill | `PermissionDeny` |
| 6 | Everything else | `PermissionDeny` |

**Always-denied tools** (both PascalCase and snake_case variants):
`Bash`, `Read`, `Write`, `Edit`, `MultiEdit`, `Glob`, `Grep`, `LS`, `TodoRead`, `TodoWrite`, `WebFetch`, `WebSearch`

### ToolBudget (Per-Turn Limits)

Limits tool calls per turn to control cost and latency:

```python
from cognitia.policy.tool_budget import ToolBudget

budget = ToolBudget(
    max_tool_calls=8,        # Total calls per turn
    max_mcp_calls=6,         # MCP-specific limit
    timeout_per_call_ms=30_000,  # 30s timeout per MCP call
)

# Before each tool call
if budget.can_call(is_mcp=True):
    budget.record_call(is_mcp=True)
    result = await call_tool()

# Check limits
budget.total_calls   # Current total count
budget.mcp_calls     # Current MCP count
budget.is_exhausted()  # True if max_tool_calls reached

# Reset at turn boundary
budget.reset()
```

### ToolSelector (Context-Budget-Aware Selection)

Selects which tools to include in the context window when 40+ tools would consume 5000-7000 tokens:

```python
from cognitia.policy.tool_selector import ToolSelector, ToolBudgetConfig, ToolGroup

config = ToolBudgetConfig(
    max_tools=30,
    group_priority=[
        ToolGroup.ALWAYS,    # thinking, todo — always included
        ToolGroup.MCP,       # Active role's MCP tools
        ToolGroup.MEMORY,    # memory_* tools
        ToolGroup.PLANNING,  # plan_* tools
        ToolGroup.SANDBOX,   # bash, read, write, edit
        ToolGroup.WEB,       # web_fetch, web_search
    ],
    group_limits={ToolGroup.WEB: 2},  # Per-group cap (optional)
)

selector = ToolSelector(config=config)
selector.add_group(ToolGroup.ALWAYS, always_tools)
selector.add_group(ToolGroup.MCP, mcp_tools)
selector.add_group(ToolGroup.MEMORY, memory_tools)

selected = selector.select()  # Returns up to max_tools, by priority order
```

**Priority groups** (lower value = higher priority):

| Group | Priority | Contains |
|-------|----------|----------|
| `ALWAYS` | 0 | `thinking`, `todo` — always included |
| `MCP` | 1 | MCP tools for the active role |
| `MEMORY` | 2 | `memory_*` tools |
| `PLANNING` | 3 | `plan_*` tools |
| `SANDBOX` | 4 | `bash`, `read`, `write`, `edit` |
| `WEB` | 5 | `web_fetch`, `web_search` |

---

## Context Builder

### DefaultContextBuilder

Assembles the system prompt from layered context packs with token budget management and hot-reload:

```python
from cognitia.context import DefaultContextBuilder, ContextInput, ContextBudget

builder = DefaultContextBuilder(prompts_dir="./prompts")

inp = ContextInput(
    user_id="u1",
    topic_id="t1",
    role_id="coach",
    user_text="Help me save money",
    active_skill_ids=["finuslugi"],
    budget=ContextBudget(total_tokens=8000),
)

built = await builder.build(
    inp,
    goal_text="Help user open a deposit",
    phase_text="Recommendation phase",
    skills=loaded_skills,
    user_profile=profile,
    recall_facts={"prev_topic": "User prefers short-term deposits"},
    summary="User discussed savings options in previous session",
    last_messages=recent_messages,
)

print(built.system_prompt)    # Assembled prompt
print(built.prompt_hash)      # SHA256 hash (16 chars)
print(built.truncated_packs)  # Which packs were cut by budget
print(built.tool_budget)      # Remaining token budget for tools
```

### ContextBudget (Priority-Based Overflow)

Controls token allocation per context pack:

```python
from cognitia.context import ContextBudget

budget = ContextBudget(
    total_tokens=8000,          # Total budget
    guardrails_reserved=1500,   # P0: always reserved
    goal_max=1000,              # P1: goal text cap
    tools_max=2000,             # P2: skill instructions cap
    messages_max=2000,          # P2.5: recent messages cap
    memory_max=1500,            # P3: memory recall cap
    profile_max=1000,           # P4: user profile cap
    summary_max=1000,           # P5: summary cap
)
```

**Assembly order and overflow behavior:**

| Priority | Pack | Overflow action |
|----------|------|-----------------|
| P0 | Guardrails (identity + rules) | **Never dropped** |
| P0.5 | Role instruction | **Never dropped** |
| P1 | Goal text | Truncated to `goal_max` |
| P1.5 | Phase state | Dropped if no budget |
| P2 | Skill instructions (tool hints) | Truncated to `tools_max` |
| P2.5 | Last messages (rehydration) | Truncated to `messages_max`; error messages filtered |
| P3 | Memory recall (cross-topic facts) | Truncated to `memory_max` |
| P4 | User profile | Truncated to `profile_max` |
| P5 | Summary | **Dropped first** when budget exceeded |

**Hot-reload:** prompt files (`identity.md`, `guardrails.md`, `roles/*.md`) are automatically reloaded when modified on disk. The builder checks file `mtime` before each `build()` call.

**Prompt hash:** every built prompt gets a deterministic SHA256 hash (16 chars) for cache invalidation and observability.

---

## Role Routing

### KeywordRoleRouter

Automatic role switching based on user message keywords:

```python
from cognitia.routing import KeywordRoleRouter

router = KeywordRoleRouter(
    default_role="coach",
    keyword_map={
        "deposit_advisor": ["deposit", "savings account", "interest rate"],
        "credit_advisor": ["credit", "loan", "mortgage", "refinance"],
    },
)

router.resolve("I want to open a savings account")  # "deposit_advisor"
router.resolve("Hello")                              # "coach" (default)
router.resolve("...", explicit_role="coach")          # "coach" (explicit wins)
```

**Resolution priority:**

1. **Explicit role** (`explicit_role` parameter) &mdash; always wins (e.g., from `/role` command)
2. **Keyword match** &mdash; case-insensitive substring search in user text
3. **Default role** &mdash; fallback when no keywords match

### YAML configuration

```yaml
# prompts/role_router.yaml
default_role: coach
roles:
  deposit_advisor:
    keywords: [deposit, savings, interest rate]
  credit_advisor:
    keywords: [credit, loan, refinance]
```

```python
from cognitia.config import load_role_router_config

config = load_role_router_config("./prompts/role_router.yaml")
router = KeywordRoleRouter(
    default_role=config.default_role,
    keyword_map=config.keyword_map,
)
```

---

## Observability

Structured JSON logging via structlog:

```python
from cognitia.observability import AgentLogger, configure_logging

# Configure once at startup
configure_logging(level="info", fmt="json")

logger = AgentLogger(component="my_app")

# Structured events
logger.session_created(user_id="u1", topic_id="t1", role_id="coach")
logger.turn_start(user_id="u1", topic_id="t1")
logger.tool_call(tool_name="get_deposits", latency_ms=450)
logger.tool_policy_event(tool_name="Bash", allowed=False, reason="ALWAYS_DENIED")
logger.turn_complete(user_id="u1", topic_id="t1", role_id="coach", prompt_hash="abc123")
```

Output format:
```json
{"ts": "2026-03-13T12:00:00Z", "level": "info", "event_type": "tool_call", "tool_name": "get_deposits", "latency_ms": 450}
```

---

## Model Registry

Multi-provider model resolution with aliases:

```python
from cognitia.runtime import ModelRegistry, get_registry

registry = get_registry()

# Resolve aliases
registry.resolve("sonnet")  # "claude-sonnet-4-20250514"
registry.resolve("gpt-4o")  # "gpt-4o"
registry.resolve("gemini")  # "gemini-2.5-pro"

# Get provider
registry.get_provider("claude-sonnet-4-20250514")  # "anthropic"
registry.get_provider("gpt-4o")                     # "openai"
```

Models are defined in `cognitia/runtime/models.yaml` and support Anthropic, OpenAI, Google, and DeepSeek.

### Resolution Priority

1. **Exact alias** -- `"sonnet"` matches the alias list in `models.yaml`
2. **Exact full name** -- `"gpt-4o"` matches the full model ID
3. **Prefix match** -- `"claude-sonnet"` matches `"claude-sonnet-4-20250514"`
4. **Default model** -- fallback to `default_model` from `models.yaml` (currently `claude-sonnet-4-20250514`)

### Full Alias Table

| Alias | Full Model ID | Provider |
| ----- | ------------- | -------- |
| `sonnet`, `sonnet-4`, `claude-sonnet` | claude-sonnet-4-20250514 | anthropic |
| `opus`, `opus-4`, `claude-opus` | claude-opus-4-20250514 | anthropic |
| `haiku`, `haiku-3`, `claude-haiku` | claude-haiku-3-20250307 | anthropic |
| `4o`, `gpt4o` | gpt-4o | openai |
| `4o-mini`, `gpt4o-mini`, `mini` | gpt-4o-mini | openai |
| `o3-reasoning` | o3 | openai |
| `o3m` | o3-mini | openai |
| `gemini-pro`, `gemini` | gemini-2.5-pro | google |
| `gemini-flash`, `flash` | gemini-2.5-flash | google |
| `deepseek`, `ds-chat` | deepseek-chat | deepseek |
| `deepseek-r1`, `ds-r1`, `r1` | deepseek-reasoner | deepseek |

### Registry API

```python
from cognitia.runtime.model_registry import get_registry, reset_registry

registry = get_registry()  # singleton, loads models.yaml once

# Introspection
registry.list_models()                # all model IDs (sorted)
registry.list_models("openai")        # models for a specific provider
registry.list_aliases()               # dict: alias -> full model ID
registry.list_providers()             # ["anthropic", "deepseek", "google", "openai"]
registry.get_description("sonnet")    # model description from YAML

# Custom config path (useful for tests)
custom = get_registry(config_path=Path("my_models.yaml"))
reset_registry()  # clear singleton (for tests)
```

The registry does not support adding aliases at runtime. To add custom models or aliases, edit `models.yaml` directly.

---

## Cancellation

### CancellationToken

Cooperative cancellation for async agent runtime loops. Thread-safe.

```python
from cognitia.runtime.cancellation import CancellationToken

token = CancellationToken()

# Register cleanup callbacks (invoked on cancel)
token.on_cancel(lambda: print("Cancelled, cleaning up"))

# Check state from the runtime loop
if token.is_cancelled:
    return  # exit gracefully

# Signal cancellation (idempotent, safe to call multiple times)
token.cancel()
```

### Behavior

- `cancel()` is idempotent -- calling it multiple times is safe; callbacks fire only on the first call.
- Callbacks registered after `cancel()` has been called are invoked immediately.
- Callback exceptions are caught and logged (never propagate).
- Thread-safe: `cancel()` and `on_cancel()` can be called from any thread.

### Integration with Agent Streaming

Pass a `CancellationToken` to stop a running agent mid-stream:

```python
import asyncio
from cognitia.runtime.cancellation import CancellationToken

token = CancellationToken()

# Cancel after 10 seconds from another task
asyncio.get_event_loop().call_later(10.0, token.cancel)

async for event in agent.stream("Long running task", cancel_token=token):
    if token.is_cancelled:
        break
    print(event)
```

Runtime loops check `token.is_cancelled` between iterations and exit cleanly when cancellation is requested, allowing in-progress LLM calls to finish before stopping.

---

## Commands

Register custom slash commands:

```python
from cognitia.commands import CommandRegistry

registry = CommandRegistry()

registry.register(
    name="help",
    handler=my_help_handler,
    aliases=["h", "?"],
    description="Show help",
)

# Dispatch
result = await registry.dispatch("/help", context)
```
