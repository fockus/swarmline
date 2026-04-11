# CLI Agent Runtime

The CLI Agent Runtime runs external command-line agents as subprocesses and parses their NDJSON output into Swarmline's `RuntimeEvent` stream. This enables integration with any CLI-based agent (Claude Code, custom scripts, third-party tools) without tight coupling.

## Overview

```
┌─────────────────┐    stdin     ┌──────────────────┐    stdout    ┌──────────────┐
│ CliAgentRuntime  │ ──────────► │  External CLI     │ ──────────► │ NdjsonParser │
│                  │   (prompt)  │  (e.g. claude)    │   (NDJSON)  │              │
└─────────────────┘             └──────────────────┘             └──────┬───────┘
                                                                        │
                                                                RuntimeEvent stream
```

The runtime:

1. Spawns the CLI process with configured command and environment
2. Sends `system_prompt` and conversation history via stdin
3. Reads NDJSON lines from stdout
4. Parses each line into a `RuntimeEvent` using a pluggable parser
5. Handles timeouts, output size limits, and process errors

For a full matrix of provider credentials and env-passing patterns across all runtimes,
see [Credentials & Provider Setup](credentials.md). For `cli` specifically, the key point
is that Swarmline passes credentials through to the wrapped command via shell env or
`CliConfig.env`.

## CliConfig

Configuration for the CLI subprocess:

```python
from swarmline.runtime.cli.types import CliConfig

config = CliConfig(
    command=["claude", "--print", "--verbose", "--output-format", "stream-json", "-"],
    output_format="stream-json",
    timeout_seconds=300.0,
    max_output_bytes=4_000_000,
    env={"ANTHROPIC_API_KEY": "sk-..."},
)
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `command` | `list[str]` | required | CLI command and arguments |
| `output_format` | `str` | `"stream-json"` | Expected output format |
| `timeout_seconds` | `float` | `300.0` | Max execution time before SIGTERM |
| `max_output_bytes` | `int` | `4_000_000` | Max stdout bytes before truncation |
| `env` | `dict[str, str]` | `{}` | Extra environment variables (merged with `os.environ`) |

`CliConfig` is a frozen dataclass -- create a new instance to change values.

## NDJSON Parsers

Parsers convert raw NDJSON lines from the subprocess into `RuntimeEvent` objects. The parser is selected automatically based on the command name, or can be injected explicitly.

### NdjsonParser Protocol

```python
from swarmline.runtime.cli.parser import NdjsonParser

class NdjsonParser(Protocol):
    def parse_line(self, line: str) -> RuntimeEvent | None:
        """Parse one NDJSON line. Returns None for unparseable lines."""
        ...
```

### ClaudeNdjsonParser

Parses Claude Code `--verbose --output-format stream-json` format:

```python
from swarmline.runtime.cli.parser import ClaudeNdjsonParser

parser = ClaudeNdjsonParser()
```

Event mapping:

| Claude Event | RuntimeEvent |
|-------------|-------------|
| `{"type": "assistant", "message": {"content": [{"type": "text", "text": "..."}]}}` | `assistant_delta` |
| `{"type": "assistant", "message": {"content": [{"type": "tool_use", ...}]}}` | `tool_call_started` |
| `{"type": "result", "result": "..."}` | `final` |
| Invalid JSON or unknown type | `None` (skipped) |

### GenericNdjsonParser

Fallback parser for non-Claude CLI tools. Wraps any valid JSON object as a `status` event:

```python
from swarmline.runtime.cli.parser import GenericNdjsonParser

parser = GenericNdjsonParser()
event = parser.parse_line('{"step": "processing", "progress": 0.5}')
# RuntimeEvent(type="status", data={"step": "processing", "progress": 0.5})
```

Invalid JSON lines return `None` and are silently skipped.

## CliAgentRuntime

The main runtime class. Implements the `AgentRuntime` protocol and supports async context manager.

### Initialization

```python
from swarmline.runtime.cli.runtime import CliAgentRuntime
from swarmline.runtime.cli.types import CliConfig
from swarmline.runtime.types import RuntimeConfig

runtime = CliAgentRuntime(
    config=RuntimeConfig(runtime_name="cli", model="sonnet"),
    cli_config=CliConfig(
        command=["claude", "--print", "--verbose", "--output-format", "stream-json", "-"]
    ),
)
```

Parser auto-selection:

- Command basename is `"claude"` -- uses `ClaudeNdjsonParser`
- Any other command -- uses `GenericNdjsonParser`
- Explicit `parser=` argument overrides auto-selection

### Running

The `run()` method is an async generator yielding `RuntimeEvent` objects:

```python
from swarmline.runtime.types import Message, RuntimeConfig

messages = [Message(role="user", content="Explain async/await in Python")]

async for event in runtime.run(
    messages=messages,
    system_prompt="You are a Python tutor.",
    active_tools=[],
):
    if event.type == "assistant_delta":
        print(event.data["text"], end="", flush=True)
    elif event.type == "error":
        print(f"Error: {event.data}")
    elif event.is_final:
        print("\n--- Done ---")
```

The stdin payload is structured in two sections:

```text
System instructions:
<raw system_prompt>

Conversation:
user: ...
assistant: ...
```

If `system_prompt` is empty, only the `Conversation:` section is sent.

### Error Handling

The runtime emits `RuntimeEvent.error()` for these cases:

| Condition | Error Kind | Recoverable |
|-----------|-----------|-------------|
| Timeout exceeded | `mcp_timeout` | No |
| Output exceeds `max_output_bytes` | `budget_exceeded` | -- |
| Non-zero exit code | `runtime_crash` | -- |
| Exit code 0 without terminal NDJSON event | `bad_model_output` | -- |
| Unexpected exception | `runtime_crash` | -- |

If the subprocess exits cleanly but the selected parser never yields a `final` event,
`CliAgentRuntime` now fails fast with `bad_model_output` instead of ending the stream
silently. This keeps the `AgentRuntime` contract intact for higher-level callers such
as `Agent.query()` and `Conversation.say()`.

### Cancellation and Cleanup

```python
# Cancel the running subprocess (sends SIGTERM)
runtime.cancel()

# Clean up resources (waits for process, kills if needed)
await runtime.cleanup()
```

Using async context manager (recommended):

```python
async with CliAgentRuntime(config, cli_config) as runtime:
    async for event in runtime.run(
        messages=messages,
        system_prompt="...",
        active_tools=[],
    ):
        print(event)
# cleanup called automatically on exit
```

## Integration with RuntimeRegistry

Register `CliAgentRuntime` as a named runtime so it can be selected via `runtime="cli"`:

```python
from swarmline.runtime.registry import RuntimeRegistry
from swarmline.runtime.cli.runtime import CliAgentRuntime
from swarmline.runtime.cli.types import CliConfig
from swarmline.runtime.types import RuntimeConfig

def create_cli_runtime(config: RuntimeConfig) -> CliAgentRuntime:
    return CliAgentRuntime(
        config=config,
        cli_config=CliConfig(
            command=["claude", "--print", "--verbose", "--output-format", "stream-json", "-"]
        ),
    )

registry = RuntimeRegistry()
registry.register("cli", create_cli_runtime)

# Now usable via config
runtime = registry.get("cli")(RuntimeConfig(runtime_name="cli", model="sonnet"))
```

## Example: Running Claude Code as Subprocess

A complete example running Claude Code CLI as a sub-agent:

```python
import asyncio
from swarmline.runtime.cli.runtime import CliAgentRuntime
from swarmline.runtime.cli.types import CliConfig
from swarmline.runtime.types import Message, RuntimeConfig


async def main() -> None:
    cli_config = CliConfig(
        command=["claude", "--print", "--verbose", "--output-format", "stream-json", "-"],
        timeout_seconds=120.0,
        max_output_bytes=2_000_000,
    )

    async with CliAgentRuntime(
        config=RuntimeConfig(runtime_name="cli", model="sonnet"),
        cli_config=cli_config,
    ) as runtime:
        messages = [Message(role="user", content="What files are in the current directory?")]

        async for event in runtime.run(
            messages=messages,
            system_prompt="You are a helpful coding assistant.",
            active_tools=[],
        ):
            if event.type == "assistant_delta":
                print(event.data.get("text", ""), end="", flush=True)
            elif event.type == "tool_call_started":
                print(f"\n[Tool: {event.data.get('name', 'unknown')}]")
            elif event.type == "error":
                print(f"\nError: {event.data}")
            elif event.is_final:
                print("\n--- Complete ---")


if __name__ == "__main__":
    asyncio.run(main())
```

## Custom Parser

Implement the `NdjsonParser` protocol for custom CLI tools:

```python
from swarmline.runtime.cli.parser import NdjsonParser
from swarmline.runtime.types import RuntimeEvent

import json

class MyToolParser:
    """Parser for a custom CLI tool's JSON output."""

    def parse_line(self, line: str) -> RuntimeEvent | None:
        if not line.strip():
            return None

        try:
            data = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return None

        msg_type = data.get("msg_type")

        if msg_type == "chunk":
            return RuntimeEvent.assistant_delta(data.get("text", ""))
        if msg_type == "done":
            return RuntimeEvent.final(text=data.get("final_text", ""))

        return None

# Use with CliAgentRuntime
runtime = CliAgentRuntime(
    config=RuntimeConfig(runtime_name="cli", model="custom"),
    cli_config=CliConfig(command=["my-tool", "--json"]),
    parser=MyToolParser(),
)

# Verify protocol compliance
assert isinstance(MyToolParser(), NdjsonParser)
```

## Next Steps

- [Multi-Agent Coordination](multi-agent.md) -- agent-as-tool, task queues, agent registry
- [Runtimes](runtimes.md) -- all available runtime backends
- [Runtime Registry](runtime-registry.md) -- registering custom runtimes
- [Architecture](architecture.md) -- Clean Architecture layers and protocols
