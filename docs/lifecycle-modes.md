# Lifecycle Modes

Agent lifecycle modes control how an agent lives and dies within the system.

## Overview

```python
from cognitia.multi_agent.graph_types import LifecycleMode
```

`LifecycleMode` is a `str` enum with three values:

## Comparison

| Mode | Who terminates | When to use | Analogy |
|------|---------------|-------------|---------|
| `EPHEMERAL` | Self (after goal completion) | One-shot tasks, fire-and-forget | Lambda function |
| `SUPERVISED` (default) | Creator decides | Most agent workflows, iterative tasks | Employee on contract |
| `PERSISTENT` | Only orchestrator/user | Long-lived services, continuous monitoring | Full-time employee |

## EPHEMERAL

Agent self-terminates after completing its first task. Best for one-shot operations where you don't need ongoing interaction.

```python
handle = await adapter.spawn_agent(
    "summarizer", "Summarize this document",
    lifecycle=LifecycleMode.EPHEMERAL,
)
result = await adapter.send_task(handle, "Summarize: ...")
# Agent is automatically cleaned up after responding
status = await adapter.get_status(handle)  # "completed"
```

## SUPERVISED (default)

Creator controls the agent's lifetime. The agent stays alive between tasks until explicitly stopped. This is the default mode.

```python
handle = await adapter.spawn_agent(
    "developer", "Build the auth system",
    lifecycle=LifecycleMode.SUPERVISED,
)
# Multi-turn interaction
r1 = await adapter.send_task(handle, "Design the schema")
r2 = await adapter.send_task(handle, "Write the migration")
r3 = await adapter.send_task(handle, "Add validation tests")

# Explicitly stop when done
await adapter.stop_agent(handle)
```

## PERSISTENT

Agent stays alive across goals. Only the orchestrator or user can remove it. Used with `PersistentGraphOrchestrator` for long-running organizational structures.

```python
from cognitia.multi_agent.persistent_graph import PersistentGraphOrchestrator

orchestrator = PersistentGraphOrchestrator(graph=graph, task_board=board, agent_runner=runner)

# Agents in the graph persist across multiple goals
await orchestrator.submit_goal("Build user auth")
await orchestrator.submit_goal("Add payment integration")
# Same agents process both goals sequentially
```

## Lifecycle and HostAdapter

When using `HostAdapter.send_task()`:
- **EPHEMERAL**: after `send_task` returns, the agent session is deleted and status becomes `COMPLETED`
- **SUPERVISED**: after `send_task` returns, the agent goes back to `IDLE` status
- **PERSISTENT**: same as SUPERVISED at the adapter level; persistence logic is handled by `PersistentGraphOrchestrator`
