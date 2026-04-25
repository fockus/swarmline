# Runtimes

Swarmline supports six public Agent API runtimes. All implement the same `AgentRuntime` protocol, so you can switch between them without changing business logic.

`headless` is not a public Agent API runtime. It is an internal MCP/code-agent mode used by `swarmline-mcp` and `swarmline mcp-serve`.

For API keys, provider environment variables, and `base_url` patterns, see the canonical reference:

- [Credentials & Provider Setup](credentials.md)

## Comparison

| Runtime | Best for | LLM/provider path | Tools and MCP | Install/runtime dependency |
| ------- | -------- | ----------------- | ------------- | -------------------------- |
| `thin` | Fast default, direct API calls, provider override | Anthropic, OpenAI-compatible, Google, DeepSeek | Local tools + Swarmline MCP bridge | `swarmline[thin]` |
| `claude_sdk` | Claude Code/Agent SDK parity | Claude SDK subprocess | Native MCP, native permissions, native subagents | `swarmline[claude]` |
| `deepagents` | LangGraph/DeepAgents workflows | DeepAgents provider packages | Local tools, graph semantics, Swarmline MCP bridge | `swarmline[deepagents]` |
| `cli` | Process-isolated CLI agents | Whatever the wrapped CLI supports | Parser-dependent; PI RPC preset available | `swarmline[cli]` |
| `openai_agents` | OpenAI Agents SDK applications | OpenAI Agents SDK | Local `@tool` bridge; unsupported MCP config fails fast | `swarmline[openai-agents]` |
| `pi_sdk` | PI coding-agent SDK integration | PI model registry/providers | Local `@tool` bridge; PI built-in tools are opt-in | Node + `@mariozechner/pi-coding-agent` |

## Portable Matrix (current coverage)

- The offline portable baseline is confirmed by the integration matrix for `claude_sdk` and `deepagents`:
  - `Agent.query()`
  - `Agent.stream()`
  - `Conversation.say()`
- `deepagents` native built-ins and store/resume surface are covered by separate offline graph tests, outside the portable matrix.
- `thin` remains a `light` tier runtime and is not a target for full parity with `claude_sdk` / `deepagents`.
- `cli` is a light-tier subprocess runtime for external CLI agents; MCP/subagents parity is not guaranteed.
- `pi_sdk` is the preferred PI integration when you want typed SDK events and local Swarmline tools.
- `runtime="cli"` with `CliConfig.pi()` is the process-isolated PI fallback using `pi --mode rpc`.
- Provider-specific risks confirmed by live smoke tests:
  - `Gemini + DeepAgents built-ins` on tool-heavy prompts remains an unstable provider-specific path. For minimal migration cost, use `feature_mode="portable"`.

## Claude SDK Runtime

Wraps the Claude Agent SDK subprocess. Provides native support for MCP, tools, and subagents.

```python
from swarmline.runtime import RuntimeConfig

config = RuntimeConfig(runtime_name="claude_sdk", model="claude-sonnet-4-20250514")
```

### Claude SDK -- when to use

- You need full integration with the Claude ecosystem
- You need native MCP servers
- You need subagents via the Task tool

### Claude SDK -- how it works

- The SDK manages a subprocess; Swarmline normalizes events into `RuntimeEvent`
- `permission_mode` is configurable; default is `bypassPermissions`
- `allowed_system_tools` whitelist enables native Read/Write for sandbox operations

### Claude SDK -- capabilities

Tier: **full**. Supports: `mcp`, `resume`, `interrupt`.

## ThinRuntime

Swarmline's own lightweight agent loop. Direct API calls without subprocess overhead.

```python
from swarmline.runtime import RuntimeConfig

config = RuntimeConfig(runtime_name="thin", model="claude-sonnet-4-20250514")
```

### ThinRuntime -- when to use

- You need maximum control over agent behavior
- You need multi-provider API access without additional provider packages
- Simple projects that do not require MCP

### ThinRuntime -- modes

ThinRuntime automatically selects a mode based on keyword heuristics, or you can set `mode_hint` explicitly:

- `conversational` -- single LLM call, no tool use
- `react` -- ReAct loop (LLM call -> tool calls -> results -> next iteration)
- `planner` -- plan-then-execute (generate plan JSON -> execute steps -> assemble final answer)

### ThinRuntime -- how it works

- `swarmline[thin]` extra includes Anthropic, OpenAI-compatible, and Google SDK paths
- Built-in MCP client (STDIO transport)
- `ToolExecutor` handles local/builtin tool invocation
- Streaming via `async for event in runtime.run(...)`
- Supports custom `llm_call`, `local_tools`, `mcp_servers`, and `sandbox` injection
- Configurable budgets: `max_iterations`, `max_tool_calls`, `max_model_retries`

### ThinRuntime -- capabilities

Tier: **light**. Supports: `mcp`, `provider_override`.

## DeepAgents Runtime

Integration via native DeepAgents graph path with a portable facade on top.

```python
from swarmline.runtime import RuntimeConfig

config = RuntimeConfig(runtime_name="deepagents", model="claude-sonnet-4-20250514")
```

### DeepAgents -- when to use

- You need DeepAgents/LangGraph graphs, built-ins, and store-backed sessions
- Multi-agent workflows
- You need a full-tier runtime but the Claude-specific SDK path is not an option

### DeepAgents -- feature modes

The `feature_mode` parameter controls the balance between portability and native features:

- `"portable"` -- offline-tested parity baseline for `query/stream/conversation`
- `"hybrid"` -- portable core + native built-ins/store seams
- `"native_first"` -- native built-ins and graph semantics as the primary path

### DeepAgents -- how it works

- Baseline extra `swarmline[deepagents]` covers the runtime + Anthropic-ready provider path
- OpenAI and Google provider paths require separate bridge packages
- Native metadata and resume surface are exposed to the application explicitly
- Native built-ins require an explicit `native_config["backend"]`

### DeepAgents -- capabilities

Tier: **full**. Supports: `resume`, `native_subagents`, `builtin_todo`, `provider_override`.

## CLI Runtime

Subprocess-based runtime for external CLI agents. Runs an external process, feeds it prompt via stdin, and parses NDJSON output from stdout into a `RuntimeEvent` stream.

```python
from swarmline.runtime import RuntimeConfig
from swarmline.runtime.cli import CliConfig

cli_config = CliConfig(
    command=["claude", "--print", "--verbose", "--output-format", "stream-json", "-"],
    output_format="stream-json",
    timeout_seconds=300.0,
)

config = RuntimeConfig(runtime_name="cli")
```

### CLI -- when to use

- Wrapping an external CLI agent (e.g., Claude CLI) as a Swarmline runtime
- You need a lightweight subprocess bridge without full SDK integration

### CLI -- how it works

- Launches the configured command as a subprocess
- Serializes system prompt and conversation history into stdin
- Parses NDJSON output lines using pluggable parsers (`ClaudeNdjsonParser`, `GenericNdjsonParser`)
- Auto-detects Claude CLI commands and normalizes flags for NDJSON contract

### CLI -- capabilities

Tier: **light**. No additional capability flags.

## OpenAI Agents Runtime

Wraps the OpenAI Agents SDK behind the Swarmline `AgentRuntime` contract.

```python
from swarmline import Agent, AgentConfig, tool

@tool
async def calc(x: int) -> str:
    return str(x + 1)

agent = Agent(AgentConfig(
    system_prompt="You are a helpful assistant.",
    runtime="openai_agents",
    tools=(calc.__tool_definition__,),
))
```

Local `@tool` handlers are bridged into OpenAI function tools. `mcp_servers` currently fails fast with a clear error instead of being ignored; use `thin` or `deepagents` for Swarmline MCP bridge support, or OpenAI Agents native MCP configuration when wiring that SDK directly.

### OpenAI Agents -- capabilities

Tier: **full**. Supports: `mcp`, `provider_override`.

## PI SDK Runtime

`pi_sdk` embeds PI through a packaged Node bridge that imports `@mariozechner/pi-coding-agent`. This is the preferred PI path because Swarmline receives typed SDK events and can execute local `@tool` handlers through a callback.

```python
from swarmline import Agent, AgentConfig, tool
from swarmline.runtime.pi_sdk import PiSdkOptions

@tool
async def calc(x: int) -> str:
    return str(x + 1)

agent = Agent(AgentConfig(
    system_prompt="You are a helpful assistant.",
    runtime="pi_sdk",
    tools=(calc.__tool_definition__,),
    runtime_options=PiSdkOptions(toolset="none"),
))
```

Security default: PI built-in coding tools are disabled by default. Enable them explicitly:

```python
PiSdkOptions(toolset="readonly")  # read/grep/find/ls style tools
PiSdkOptions(toolset="coding")    # read/bash/edit/write style coding tools
```

Install PI separately:

```bash
npm install -g @mariozechner/pi-coding-agent
```

### PI CLI preset

Use the CLI path when you want process isolation or already operate PI as a CLI:

```python
from swarmline import Agent, AgentConfig
from swarmline.runtime.cli import CliConfig

agent = Agent(AgentConfig(
    system_prompt="You are a helpful assistant.",
    runtime="cli",
    runtime_options=CliConfig.pi(),
))
```

`CliConfig.pi()` runs `pi --mode rpc --no-session` and parses PI RPC JSONL events with `PiRpcParser`.

### PI SDK -- capabilities

Tier: **full**. Supports: `resume`, `interrupt`, `provider_override`.

## Switching Runtimes

Runtime selection is configuration-driven -- business code stays the same:

```python
from swarmline.runtime import RuntimeConfig

# Development: ThinRuntime (fast, no subprocess)
config = RuntimeConfig(runtime_name="thin")

# Production: Claude SDK (full integration)
config = RuntimeConfig(runtime_name="claude_sdk")

# Experiments: DeepAgents (LangGraph)
config = RuntimeConfig(runtime_name="deepagents")

# CLI subprocess runtime
config = RuntimeConfig(runtime_name="cli")

# OpenAI Agents SDK
config = RuntimeConfig(runtime_name="openai_agents")

# PI SDK through Node bridge
config = RuntimeConfig(runtime_name="pi_sdk")
```

Resolution priority: `runtime_override` > `RuntimeConfig.runtime_name` > `SWARMLINE_RUNTIME` env var > default (`claude_sdk`).

## AgentRuntime Protocol

```python
from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class AgentRuntime(Protocol):
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

    async def __aenter__(self) -> AgentRuntime: ...

    async def __aexit__(self, *exc: Any) -> None: ...
```

Key design principle: the runtime **does not own state**. It receives `messages` each turn and returns `new_messages` in the final event. `SessionManager` is the source of truth for conversation history.

## RuntimeEvent Types

| Type | Data | When emitted |
| ---- | ---- | ------------ |
| `assistant_delta` | `{"text": "..."}` | Streaming text fragment |
| `status` | `{"text": "..."}` | Status update (thinking, tool call in progress) |
| `tool_call_started` | `{"name": "...", "correlation_id": "...", "args": {...}}` | Tool call begins |
| `tool_call_finished` | `{"name": "...", "correlation_id": "...", "ok": bool, "result_summary": "..."}` | Tool call completes |
| `approval_required` | `{"action_name": "...", "args": {...}, "allowed_decisions": [...], "interrupt_id": "..."}` | Human approval needed |
| `user_input_requested` | `{"prompt": "...", "interrupt_id": "..."}` | Runtime requests human input |
| `native_notice` | `{"text": "...", "metadata": {...}}` | Runtime-specific semantics notice |
| `final` | `{"text": "...", "new_messages": [...], "metrics": {...}}` | Turn complete |
| `error` | `{"kind": "...", "message": "...", "recoverable": bool}` | Error occurred |

## Capability Negotiation

You can declare required capabilities at configuration time. If the selected runtime does not support them, a `ValueError` is raised immediately:

```python
from swarmline.runtime import RuntimeConfig, CapabilityRequirements

config = RuntimeConfig(
    runtime_name="thin",
    required_capabilities=CapabilityRequirements(
        tier="full",
        flags=("mcp", "resume"),
    ),
)
# Raises ValueError: Runtime 'thin' does not support required capabilities: tier:full, resume
```

Available capability flags: `mcp`, `resume`, `interrupt`, `native_permissions`, `user_input`, `native_subagents`, `builtin_memory`, `builtin_todo`, `builtin_compaction`, `hitl`, `project_instructions`, `provider_override`.

## Custom Runtimes

Register a custom runtime via `RuntimeRegistry`:

```python
from swarmline.runtime import RuntimeRegistry, get_default_registry, RuntimeCapabilities

def my_factory(config, **kwargs):
    return MyCustomRuntime(config)

registry = get_default_registry()
registry.register(
    "my_runtime",
    factory_fn=my_factory,
    capabilities=RuntimeCapabilities(
        runtime_name="my_runtime",
        tier="light",
        supports_mcp=True,
    ),
)
```

Third-party runtimes can also be registered via entry points (group `swarmline.runtimes`).
