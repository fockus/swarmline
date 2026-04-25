# `pi_sdk` runtime

The `pi_sdk` runtime is a thin Python wrapper that launches a Node.js subprocess
("the bridge") which embeds Mario Zechner's
[`@mariozechner/pi-coding-agent`](https://github.com/mariozechner/pi-coding-agent)
SDK. The Python side owns the Swarmline contracts; the Node side owns the
actual model loop.

Use it when you want:

- Pi's coding-agent loop and tool semantics, but inside a Swarmline pipeline.
- A clean way to mix Pi's planning model with the rest of the Swarmline ecosystem
  (memory, observability, hooks, JSONL telemetry).

## Installation

You need:

- **Node.js ≥ 20.6** on `PATH`.
- The Node package `@mariozechner/pi-coding-agent` available to the bridge.
  The bridge resolves it relative to its own directory, so installing the
  package globally or in the bridge's `node_modules` is enough.
- The Python optional extras:

  ```bash
  pip install "swarmline[pi-sdk]"
  ```

The Node bridge ships inside the `swarmline` distribution under
`runtime/pi_sdk/bridge/`. The runtime spawns it via `node`.

## Quick start

```python
from swarmline.agent import Agent, AgentConfig

agent = Agent(AgentConfig(
    system_prompt="You are a focused coding assistant.",
    runtime="pi_sdk",
    model="claude-sonnet-4",   # any model Pi supports
))

reply = await agent.query("Refactor calc.py to extract validation into a helper.")
print(reply.text)
```

If `node` is not installed or not on `PATH`, the runtime emits a
`dependency_missing` error event with a clear message — it does not crash.

## Configuration

`PiSdkOptions` lives in `swarmline.runtime.pi_sdk.types`:

```python
from swarmline.agent import Agent, AgentConfig
from swarmline.runtime.pi_sdk.types import PiSdkOptions

pi_options = PiSdkOptions(
    toolset="coding",                       # "none" | "readonly" | "coding"
    coding_profile=None,                    # name of a bundled Pi coding profile, optional
    cwd="/abs/path/to/project",             # workdir for the bridge subprocess
    agent_dir=None,                         # override Pi agent dir
    auth_file=None,                         # path to Pi auth json, optional
    session_mode="memory",                  # "memory" | "persisted"
    bridge_command=(),                      # override the node command, default uses bundled bridge
    package_name="@mariozechner/pi-coding-agent",
    provider=None,                          # let Pi pick from its own config
    model_id=None,                          # let Pi pick
    thinking_level=None,                    # e.g. "low" | "medium" | "high" if supported
    timeout_seconds=300.0,                  # per-turn wall-clock cap
)

agent = Agent(AgentConfig(
    system_prompt="...",
    runtime="pi_sdk",
    runtime_options=pi_options,
    model="claude-sonnet-4",
))
```

If you don't pass `runtime_options`, the runtime derives sensible defaults
from the `RuntimeConfig` (model name, env vars, base_url) — most users
shouldn't need to touch `PiSdkOptions` at all.

## How the bridge works

1. `PiSdkRuntime.run()` builds a JSON request describing the turn (`messages`,
   `system_prompt`, `tools`, `config`).
2. It launches `node <bridge.js>` as a subprocess via
   `asyncio.create_subprocess_exec()`.
3. The bridge reads the request from stdin, calls Pi's SDK, and emits one
   newline-delimited JSON event per line on stdout.
4. The Python side parses each line through `event_mapper.map_pi_bridge_event()`
   and yields a `RuntimeEvent`.

Every event the bridge emits — assistant delta, tool call, tool result, error,
final — has a 1:1 mapping to a Swarmline `RuntimeEvent`, so pipelines, hooks,
and observability work exactly as with `runtime="thin"`.

## Capabilities

| Capability                | Value     |
|---------------------------|-----------|
| `runtime_name`            | `pi_sdk`  |
| `tier`                    | `premium` |
| `streaming`               | yes       |
| `tool_calling`            | yes       |
| `parallel_tool_calling`   | inherited from Pi |
| `hooks`                   | yes (mapped on the Python side) |
| `structured_output`       | yes (Pydantic via post-validate) |
| `multimodal`              | yes (Pi handles `content_blocks`) |

## Tool bridging

`@tool`-decorated callables are serialized to the bridge as JSON Schema. The
Node bridge registers them with Pi's tool runner; when Pi calls one, the
bridge emits a `tool_call` event, the Python runtime executes the callable
locally, and the bridge receives the `tool_result` event back over a
follow-up message.

```python
from swarmline.agent.tool import tool

@tool
def query_db(table: str, where: str) -> list[dict]:
    """Run a select against the database."""
    return repository.query(table, where)

agent = Agent(AgentConfig(
    system_prompt="...",
    runtime="pi_sdk",
    tools=(query_db,),
))
```

This means **tool execution is always local** to the Python process. The Node
bridge is dumb on tools — it just relays calls and results. Sandbox policies,
async semantics, and security checks all run in Python, so nothing changes
relative to the `thin` runtime.

## Cancellation

`AgentRuntime.cancel()` sets a flag that the next event loop iteration honours,
and additionally sends `SIGTERM` to the Node subprocess. If the bridge is in
the middle of a tool call that ignores cancellation, you may see a few more
events arrive before the process actually exits. The runtime always cleans up
the subprocess in a `finally` block.

## Differences from `runtime="thin"`

| Concern                 | `thin`              | `pi_sdk`               |
|-------------------------|---------------------|------------------------|
| LLM client              | direct Python call  | Node subprocess via Pi |
| Provider matrix         | Anthropic / OpenAI / Google / DeepSeek | whatever Pi supports |
| Latency overhead        | none                | ~50-100ms subprocess startup per turn |
| Process model           | in-process          | one Node subprocess per turn |
| Hooks                   | first-class         | mapped from bridge events |
| Cost tracking           | `pricing.json`      | inherited                |

For most projects, `runtime="thin"` is faster and simpler. Reach for `pi_sdk`
when you specifically want Pi's loop semantics or you're already running Pi as
a coding agent and want to integrate it into Swarmline.

## Troubleshooting

| Symptom                                            | Cause / fix                                  |
|----------------------------------------------------|----------------------------------------------|
| `dependency_missing: Node.js is required for runtime='pi_sdk'` | Install Node.js ≥ 20.6 and ensure `node` is on `PATH`. |
| `runtime_crash: Failed to launch PI SDK bridge: ...` | Inspect the message; usually `node_modules` lookup failure for `@mariozechner/pi-coding-agent`. |
| Bridge appears hung / no events                    | Check the subprocess stderr (it surfaces in the runtime log). Increase `timeout_seconds` if the model is genuinely slow. |
| Tool call returns immediately with `{"status":"error"}` | The tool's executor raised. The Python-side error message is in the result. |

## See also

- `src/swarmline/runtime/pi_sdk/runtime.py` — adapter source.
- `src/swarmline/runtime/pi_sdk/event_mapper.py` — event mapping.
- `src/swarmline/runtime/pi_sdk/types.py` — `PiSdkOptions`.
- `docs/runtimes.md` — runtime selection table.
- `CHANGELOG.md` `[1.5.0]` "New runtime adapters" entry.
