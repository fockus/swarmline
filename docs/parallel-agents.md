# Parallel agents

Swarmline 1.5.0 adds first-class support for spawning subagents that run **in
parallel and in isolation** from the parent agent.

This page covers:

1. The `spawn_agent` builtin tool — how the model delegates work to a child agent.
2. `SubagentToolConfig` — concurrency, depth, and timeout knobs.
3. Worktree isolation — running subagents in dedicated git worktrees.
4. Background subagents and the `monitor_agent` tool.

If you just need a quick mental model: spawn = `fork()`, monitor = `wait()`,
worktree isolation = `chroot for git`.

## Enabling subagent tools

Subagent tools are off by default. Pass a `SubagentToolConfig` to enable them:

```python
from swarmline.agent import Agent, AgentConfig
from swarmline.runtime.thin.subagent_tool import SubagentToolConfig

agent = Agent(AgentConfig(
    system_prompt="You are an orchestrator. Delegate work via spawn_agent.",
    runtime="thin",
    subagent_config=SubagentToolConfig(),
))

# Once enabled, the model has access to two builtin tools:
#   - spawn_agent(task, system_prompt?, tools?, isolation?, run_in_background?)
#   - monitor_agent(agent_id)
```

`SubagentToolConfig` has these knobs:

| Field | Default | Purpose |
|-------|---------|---------|
| `max_concurrent` | `4` | Max simultaneously-running subagents per parent. |
| `max_worktrees` | `5` | Max simultaneously-existing worktrees. Hard cap. |
| `max_depth` | `3` | Recursion guard — child of child of child = depth 3. |
| `timeout_seconds` | `300.0` | Per-subagent wall-clock timeout. |
| `base_path` | `None` | Where worktrees are created. Defaults to a tempdir. |
| `background_timeout` | `None` | Override timeout for background spawns. |
| `sandbox_config` | `None` | If set, subagent runs inside the configured sandbox. |

## `spawn_agent` — basic foreground delegation

The model calls `spawn_agent` with a `task` and optionally a custom `system_prompt`,
a tool subset, an isolation mode, and a background flag:

```jsonc
// What the LLM emits as a tool call
{
  "name": "spawn_agent",
  "arguments": {
    "task": "Find every README in src/ and summarize the top-level intent",
    "system_prompt": "You are a focused code reader.",
    "tools": ["read_file", "glob"]
  }
}
```

The tool returns the subagent's final output as JSON:

```json
{
  "status": "completed",
  "agent_id": "agent-abc123",
  "output": "Found 4 READMEs. Summary: ..."
}
```

If something goes wrong, the executor never raises — it returns:

```json
{
  "status": "error",
  "agent_id": "agent-abc123",
  "error": "Timeout after 300s"
}
```

## Tool inheritance

By default, the subagent inherits **all** of the parent's tools. The LLM can
narrow that by passing `tools=[...]`:

- Reduces the prompt size for the child (fewer tool descriptions to attend to).
- Acts as a soft sandbox — the child cannot call tools outside the allowlist.

Hard sandboxing is what `isolation` and `sandbox_config` are for.

## Worktree isolation (Phase 17)

Setting `isolation="worktree"` runs the subagent in a **dedicated git worktree
on a temporary branch**. Useful when the subagent edits files: changes are
contained, and an empty worktree is auto-cleaned at the end.

```jsonc
{
  "name": "spawn_agent",
  "arguments": {
    "task": "Refactor src/calc.py to remove the duplicate validation block",
    "isolation": "worktree"
  }
}
```

Lifecycle:

1. Parent's `git status` is left untouched.
2. A new worktree is created at `<base_path>/swarmline-agent-<uuid>/` on a
   fresh branch named after the agent ID.
3. The subagent runs there. Its `cwd` is the worktree path.
4. On completion:
   - If the worktree has changes → returned in the result; cleanup is the
     parent's responsibility (or a follow-up tool call).
   - If the worktree is clean → branch and worktree are deleted automatically.

The hard cap on simultaneous worktrees is `max_worktrees` (default `5`). The
spawn fails fast with a clean error if the cap would be exceeded — no leak.

## Background subagents

For fan-out patterns where the parent should keep working while children
crunch in parallel:

```jsonc
{
  "name": "spawn_agent",
  "arguments": {
    "task": "Deep-research the latest CVEs in our dependency tree",
    "run_in_background": true
  }
}
```

The tool returns immediately:

```json
{
  "status": "running",
  "agent_id": "agent-bg-7f2e"
}
```

The parent then keeps working. To check progress or collect the output, the
LLM calls `monitor_agent`:

```jsonc
{
  "name": "monitor_agent",
  "arguments": {"agent_id": "agent-bg-7f2e"}
}
```

Possible responses:

```json
{"status": "running", "agent_id": "agent-bg-7f2e"}

{"status": "completed", "agent_id": "agent-bg-7f2e", "output": "..."}

{"status": "error", "agent_id": "agent-bg-7f2e", "error": "..."}
```

When a background subagent finishes, the runtime also emits a
`RuntimeEvent.background_complete` event on the main event stream. UIs can
subscribe to this to render progress without polling.

## Patterns

### Fan-out fan-in research

```text
Parent agent prompt:
  "Research these 3 topics in parallel: <a>, <b>, <c>. Summarize."

Model calls:
  spawn_agent(task="research <a>", run_in_background=true) → agent-1
  spawn_agent(task="research <b>", run_in_background=true) → agent-2
  spawn_agent(task="research <c>", run_in_background=true) → agent-3

  monitor_agent(agent-1) → completed, "<output-a>"
  monitor_agent(agent-2) → completed, "<output-b>"
  monitor_agent(agent-3) → completed, "<output-c>"

Parent emits final summary combining all three.
```

### Safe code refactor

```text
Parent agent prompt:
  "Try refactoring X two different ways and report which is cleaner."

Model calls:
  spawn_agent(task="refactor X using approach 1", isolation="worktree") → output A
  spawn_agent(task="refactor X using approach 2", isolation="worktree") → output B

Both attempts run in dedicated worktrees, so neither pollutes the parent's
working tree. Parent compares diffs and chooses one (or merges manually).
```

## Recursion limits

`max_depth=3` means an agent can spawn a child that can spawn a grandchild
that can spawn a great-grandchild — but no further. The fourth level fails
fast with `error: "max recursion depth (3) exceeded"`.

Increase only if you have a real tree-of-thoughts use case; the practical
default keeps stack depth predictable and budgets bounded.

## Observability

Spawned subagents inherit the parent's:

- `EventBus` — every LLM call, tool call, and error inside the subagent
  surfaces on the same bus, with the subagent's `agent_id` in `metadata`.
- `Tracer` — spans nest correctly under the parent's spawn span.
- `JsonlTelemetrySink` — records all subagent events to the same JSONL file
  with `agent_id` set.

Filter by `agent_id` to reconstruct any subagent's transcript independently.

## See also

- `docs/agent-pack.md` — packaging an agent so it can be spawned by name.
- `docs/observability.md` — tracing and JSONL telemetry, including
  background-complete events.
- `src/swarmline/runtime/thin/subagent_tool.py` — source of truth for the
  spec, executor, and worktree lifecycle.
