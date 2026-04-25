# Why Swarmline?

## The Problem

Building production AI agents requires more than an LLM API call. A real agent needs memory, tools, observability, sessions, provider flexibility, and a runtime story that does not lock the application to one vendor.

Most frameworks either force you into one ecosystem or provide a thin wrapper that leaves production concerns to the app.

## Swarmline's Approach

Swarmline is a modular, protocol-driven framework built on Clean Architecture. The public path stays small:

```python
from swarmline import Agent, AgentConfig

agent = Agent(AgentConfig(system_prompt="You are helpful.", runtime="thin"))
result = await agent.query("Hello")
```

The same facade can later move to another runtime without changing business code:

```python
AgentConfig(runtime="thin")
AgentConfig(runtime="claude_sdk")
AgentConfig(runtime="deepagents")
AgentConfig(runtime="cli")
AgentConfig(runtime="openai_agents")
AgentConfig(runtime="pi_sdk")
```

`headless` is different: it is an internal MCP/code-agent mode for `swarmline-mcp`, not a runtime developers choose for normal `Agent` applications.

## What Makes It Different

| Principle | How Swarmline applies it |
| --------- | ------------------------ |
| Protocol-first | Core ports are small `typing.Protocol` interfaces |
| Runtime-agnostic | Six public runtimes share one `AgentRuntime` contract |
| Secure by default | Tool access is default-deny; host execution is opt-in |
| Production memory | InMemory, SQLite, and PostgreSQL providers share the same protocols |
| FastAPI-like DX | Simple defaults first, typed options when you need power |

## Runtime Strategy

Swarmline treats runtimes as interchangeable execution engines:

- `thin` for the built-in multi-provider loop
- `claude_sdk` for Claude Agent SDK parity
- `deepagents` for LangGraph/DeepAgents workflows
- `cli` for subprocess-based code agents
- `openai_agents` for OpenAI Agents SDK
- `pi_sdk` for PI via `@mariozechner/pi-coding-agent`

PI has two paths:

- `runtime="pi_sdk"` is the preferred typed SDK integration.
- `runtime="cli"` with `CliConfig.pi()` is the process-isolated RPC fallback.

## When to Use Swarmline

Good fit:

- You are building a production AI agent that needs memory, tools, observability, and sessions.
- You want to swap providers or runtimes without rewriting application code.
- You need multi-agent graphs, task boards, governance, or long-term knowledge.
- You want framework ergonomics without giving up runtime control.

Not the best fit:

- You only need one direct LLM API call.
- You want a frontend/UI framework.
- You are intentionally locked into one upstream SDK and do not need portability.
