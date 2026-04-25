# `openai_agents` runtime

The `openai_agents` runtime is a thin wrapper around the official
[OpenAI Agents SDK](https://github.com/openai/openai-agents-python) — it
implements Swarmline's `AgentRuntime` contract by delegating to
`Runner.run_streamed()` and converting Agents-SDK stream events to
`RuntimeEvent`.

Use it when you want:

- The OpenAI Agents SDK's tool-handling and streaming behaviour.
- First-class Codex MCP integration (planning + code edits in one loop).
- Access to OpenAI's models with their native function-calling.

## Installation

```bash
pip install "swarmline[openai-agents]"
```

This pulls in `openai-agents` (the SDK).

## Quick start

```python
from swarmline.agent import Agent, AgentConfig

agent = Agent(AgentConfig(
    system_prompt="You are a focused engineering assistant.",
    runtime="openai_agents",
    model="gpt-4.1",
))

reply = await agent.query("Write a Python script that prints prime numbers up to 100.")
print(reply.text)
```

Streaming, tool calls, hooks, and structured output all work the same way as
with `runtime="thin"` — the wrapper is in charge of mapping events.

## Configuration

`OpenAIAgentsConfig` lives in `swarmline.runtime.openai_agents.types` and lets
you customise the underlying Agent and optionally attach Codex as an MCP server:

```python
from swarmline.agent import Agent, AgentConfig
from swarmline.runtime.openai_agents.types import OpenAIAgentsConfig

agents_config = OpenAIAgentsConfig(
    model="gpt-4.1",                       # default model the SDK uses
    codex_enabled=True,                    # attach Codex MCP server (planning + code edits)
    codex_sandbox="network-off",           # Codex sandbox profile
    codex_approval_policy="suggest",       # how Codex requests approval for risky calls
    max_turns=20,                          # OpenAI Agents SDK turn cap
    env={"OPENAI_API_KEY": "sk-..."},      # injected into the SDK runtime
)

agent = Agent(AgentConfig(
    system_prompt="...",
    runtime="openai_agents",
    runtime_options=agents_config,   # passed through to OpenAIAgentsRuntime
    model="gpt-4.1",
))
```

When `codex_enabled=True`, the runtime registers Codex as an MCP server inside
the OpenAI Agent, so the LLM can call its planning and code-execution tools
alongside any tools you define in `AgentConfig.tools`. The `codex_sandbox` and
`codex_approval_policy` fields are passed through to Codex unchanged.

## Capabilities

The runtime registers under `RuntimeRegistry["openai_agents"]` with these
capability flags (queryable via `swarmline.runtime.factory.runtime_capabilities()`):

| Capability                | Value     |
|---------------------------|-----------|
| `runtime_name`            | `openai_agents` |
| `tier`                    | `premium` |
| `streaming`               | yes       |
| `tool_calling`            | yes       |
| `parallel_tool_calling`   | yes       |
| `hooks`                   | yes (mapped via Swarmline `HookRegistry`) |
| `structured_output`       | yes (Pydantic models supported) |
| `multimodal`              | yes (via `ContentBlock`) |

## Provider keys

The Agents SDK reads `OPENAI_API_KEY` from the environment (or whatever the SDK
documents). Swarmline does not hold its own per-runtime key — set the env var
once and any OpenAI-backed runtime picks it up.

## Tool bridging

User-defined `@tool`-decorated callables are converted to OpenAI Agents SDK
tools via `swarmline.runtime.openai_agents.tool_bridge.toolspecs_to_agent_tools()`.
Each tool's JSON Schema (auto-inferred from type hints + docstring) becomes the
SDK's tool schema verbatim, and the executor wires the agent-side handler back
to the original Python function.

```python
from swarmline.agent.tool import tool

@tool
def lookup_user(user_id: str) -> dict:
    """Fetch a user record by ID."""
    return db.get(user_id)

agent = Agent(AgentConfig(
    system_prompt="...",
    runtime="openai_agents",
    tools=(lookup_user,),
))
```

The LLM sees a normal OpenAI tool definition; the executor translates the
SDK's tool-call event back into a Python call to `lookup_user`.

## Streaming

`OpenAIAgentsRuntime.run()` yields `RuntimeEvent`s for:

- `assistant_delta` — partial text from `Runner.run_streamed()`.
- `tool_call` / `tool_result` — individual tool invocations.
- `thinking_delta` — when the model emits explicit reasoning blocks.
- `final` — accumulated text + `TurnMetrics` (token counts, cost if known).
- `error` — `RuntimeErrorData` mapped from any SDK exception.

## Differences from `runtime="thin"`

| Concern                | `thin`              | `openai_agents`        |
|------------------------|---------------------|------------------------|
| Provider matrix        | Anthropic, OpenAI, Google, DeepSeek | OpenAI only |
| Tool dispatch          | Swarmline `ToolExecutor` | OpenAI Agents SDK `RunSession` |
| Hook support           | full (Pre/Post/Stop/UserPromptSubmit) | mapped to SDK events |
| Native parallel tools  | yes (Phase 5)       | yes (SDK feature)       |
| Subagent (`spawn_agent`) | yes               | yes (works via tool registration) |
| Codex MCP              | available via `mcp_servers={...}` | first-class via `enable_codex=True` |
| Cost tracking          | `pricing.json`      | inherited from `pricing.json` |

If you don't need Codex or the OpenAI Agents SDK specifically, prefer the
default `runtime="thin"` for portability across providers.

## Limitations

- The runtime depends on the OpenAI Agents SDK; if it's not installed,
  initialising the runtime emits a `dependency_missing` `RuntimeEvent.error`
  instead of running.
- Cancellation goes through the SDK's run object — long-running tools that
  ignore SDK cancellation will not stop until they return.

## See also

- `src/swarmline/runtime/openai_agents/runtime.py` — adapter source.
- `src/swarmline/runtime/openai_agents/tool_bridge.py` — tool conversion.
- `src/swarmline/runtime/openai_agents/event_mapper.py` — event mapping.
- `docs/runtimes.md` — runtime selection table.
- `CHANGELOG.md` `[1.5.0]` "New runtime adapters" entry.
