# Persistent Graph & Goal Queue

Long-lived agent organizations that process goals sequentially.

## Overview

`PersistentGraphOrchestrator` extends the standard graph orchestrator with:
- **Persistent agent structure** — agents in `PERSISTENT` mode stay alive across goals
- **Goal queue** — FIFO queue for submitting and processing goals sequentially
- **Auto-processing** — goals are automatically picked up and executed

## PersistentGraphOrchestrator

```python
from cognitia.multi_agent.persistent_graph import PersistentGraphOrchestrator
```

### Constructor

```python
orchestrator = PersistentGraphOrchestrator(
    graph=graph,           # AgentGraphStore instance
    task_board=task_board,  # TaskBoard instance
    agent_runner=runner,    # Function to run agents
    event_bus=bus,          # Optional EventBus for goal lifecycle events
    max_concurrent=5,       # Max concurrent agent executions
    auto_process=True,      # Auto-start processing on goal submit
)
```

### Key Methods

| Method | Description |
|--------|-------------|
| `submit_goal(goal, metadata=None) -> str` | Submit a goal to the queue, returns `goal_id` |
| `get_goal_queue() -> list[GoalEntry]` | All goals (pending + completed) |
| `get_pending_goals() -> list[GoalEntry]` | Only pending goals |
| `add_agent(node) -> None` | Add an agent to the persistent structure |
| `remove_agent(agent_id) -> None` | Remove an agent |

## GoalQueue

In-memory FIFO queue with status tracking.

```python
from cognitia.multi_agent.goal_queue import GoalQueue, GoalEntry, GoalStatus
```

### GoalStatus

| Status | Description |
|--------|-------------|
| `QUEUED` | Submitted, waiting to be processed |
| `RUNNING` | Currently being processed |
| `COMPLETED` | Successfully processed |
| `FAILED` | Processing failed |

### GoalEntry

Frozen dataclass with fields: `id`, `goal`, `status`, `submitted_at`, `completed_at`, `run_id`, `metadata`.

## Example: Persistent Organization

```python
import asyncio
from cognitia.multi_agent.graph_builder import GraphBuilder
from cognitia.multi_agent.graph_types import AgentCapabilities, LifecycleMode
from cognitia.multi_agent.persistent_graph import PersistentGraphOrchestrator

async def main():
    # Build a persistent org structure
    graph = (
        GraphBuilder()
        .add_agent("lead", role="lead",
            lifecycle=LifecycleMode.PERSISTENT,
            capabilities=AgentCapabilities(can_hire=True, can_delegate=True))
        .add_agent("backend", role="developer",
            lifecycle=LifecycleMode.PERSISTENT)
        .add_agent("reviewer", role="reviewer",
            lifecycle=LifecycleMode.PERSISTENT)
        .set_root("lead")
        .connect("lead", "backend")
        .connect("lead", "reviewer")
        .build()
    )

    orchestrator = PersistentGraphOrchestrator(
        graph=graph,
        task_board=task_board,
        agent_runner=runner,
    )

    # Submit 3 goals — processed sequentially by the same persistent agents
    goal1 = await orchestrator.submit_goal("Build user authentication")
    goal2 = await orchestrator.submit_goal("Add payment integration")
    goal3 = await orchestrator.submit_goal("Implement notification system")

    # Check queue status
    pending = orchestrator.get_pending_goals()
    print(f"Pending goals: {len(pending)}")

asyncio.run(main())
```

## Events

When an `EventBus` is provided, the orchestrator emits:
- `persistent.goal.submitted` — when a goal is added to the queue
- Goal processing events from the underlying `DefaultGraphOrchestrator`
