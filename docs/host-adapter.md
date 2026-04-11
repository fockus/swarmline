# HostAdapter Protocol

Universal facade for spawning and managing AI agents across different runtimes.

## Overview

`HostAdapter` is a `@runtime_checkable Protocol` with 4 methods (ISP-compliant). It provides a unified API for agent lifecycle management regardless of the underlying provider — Claude Agent SDK, OpenAI/Codex, or any future runtime.

## API

```python
from swarmline.protocols.host_adapter import HostAdapter, AgentHandle, AgentAuthority, AgentHandleStatus
```

### `spawn_agent(role, goal, **kwargs) -> AgentHandle`

Spawn a new agent with the given role and goal.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `role` | `str` | required | Agent role (e.g., "developer", "reviewer") |
| `goal` | `str` | required | High-level goal for the agent |
| `system_prompt` | `str` | `""` | Custom system prompt (auto-generated if empty) |
| `model` | `str \| None` | `None` | Model override (resolved via ModelRegistry) |
| `tools` | `tuple[str, ...]` | `()` | Tool names available to the agent |
| `skills` | `tuple[str, ...]` | `()` | Skill names to load |
| `hooks` | `tuple[str, ...]` | `()` | Hook names to attach |
| `lifecycle` | `LifecycleMode` | `SUPERVISED` | Agent lifecycle mode |
| `authority` | `AgentAuthority \| None` | `None` | Authority config for sub-agent spawning |
| `timeout` | `float \| None` | `None` | Timeout in seconds |

Returns an `AgentHandle` — an opaque, frozen dataclass with `id`, `role`, `lifecycle`, and `metadata`.

### `send_task(handle, task) -> str`

Send a task to an existing agent. Returns the agent's response text.

### `stop_agent(handle) -> None`

Stop and clean up an agent. Releases all associated resources.

### `get_status(handle) -> str`

Get the current status of an agent. Returns an `AgentHandleStatus` constant:
- `IDLE` — spawned, waiting for tasks
- `RUNNING` — currently processing a task
- `COMPLETED` — finished (ephemeral agents after task completion)
- `FAILED` — encountered an error
- `STOPPED` — explicitly stopped via `stop_agent()`

## Implementations

### AgentSDKAdapter (Claude)

Uses Claude Agent SDK (`claude-agent-sdk` package). Best for Claude-native workflows with MCP support.

```python
from swarmline.runtime.agent_sdk_adapter import AgentSDKAdapter

adapter = AgentSDKAdapter(default_model="opus")
```

- Lazy-imports `claude_code_sdk` to avoid hard dependency
- Resolves model names via `ModelRegistry` (`"opus"` -> `"claude-opus-4-20250514"`)
- Install: `pip install swarmline[claude]`

### CodexAdapter (OpenAI/Codex)

Uses OpenAI SDK for Codex/GPT agents. Best for OpenAI-native workflows.

```python
from swarmline.runtime.codex_adapter import CodexAdapter

adapter = CodexAdapter(default_model="codex", api_key="sk-...")
```

- Lazy-imports `openai` to avoid hard dependency
- Resolves model names via `ModelRegistry` (`"codex"` -> `"codex-mini"`)
- Supports multi-turn conversation history
- Install: `pip install swarmline[openai-agents]`

## Usage Example

```python
import asyncio
from swarmline.runtime.agent_sdk_adapter import AgentSDKAdapter

async def main():
    adapter = AgentSDKAdapter(default_model="opus")

    # Spawn an agent
    handle = await adapter.spawn_agent("developer", "Implement OAuth2")

    # Send a task
    result = await adapter.send_task(handle, "Write the auth middleware")
    print(result)

    # Check status
    status = await adapter.get_status(handle)
    print(f"Status: {status}")  # "idle"

    # Clean up
    await adapter.stop_agent(handle)

asyncio.run(main())
```

## Protocol Conformance

Both adapters pass `isinstance(adapter, HostAdapter)` thanks to `@runtime_checkable`. No inheritance required — structural subtyping via Python Protocols.

```python
from swarmline.protocols.host_adapter import HostAdapter

assert isinstance(AgentSDKAdapter(), HostAdapter)  # True
assert isinstance(CodexAdapter(), HostAdapter)      # True
```
