# Multi-Agent Coordination

Cognitia provides building blocks for multi-agent systems: **agent-as-tool** invocation, **task queues** for work distribution, and an **agent registry** for lifecycle management. All components follow the protocol-first approach with swappable implementations.

> **Introduced in v1.2.0**: For hierarchical multi-agent organizations with governance, delegation, and inter-agent communication, see the [Agent Graph System](graph-agents.md).

## Overview

Multi-agent coordination in Cognitia is built around three primitives:

| Primitive | Purpose | Protocol |
|-----------|---------|----------|
| **Agent-as-Tool** | Run one agent as a tool callable by another | `AgentTool` |
| **Task Queue** | Distribute work items between agents | `TaskQueue` |
| **Agent Registry** | Track agent lifecycle and metadata | `AgentRegistry` |

For more advanced scenarios introduced in v1.2.0:

| Primitive | Purpose | Documentation |
|-----------|---------|---------------|
| **Agent Graph** | Hierarchical org charts with governance | [Graph Agents](graph-agents.md) |
| **Graph Task Board** | DAG tasks with progress tracking | [Graph Agents](graph-agents.md#task-board) |
| **Graph Communication** | Inter-agent messaging | [Graph Agents](graph-agents.md#communication) |
| **Knowledge Bank** | Shared structured knowledge | [Knowledge Bank](knowledge-bank.md) |
| **Pipeline Engine** | Multi-phase execution | [Pipeline](pipeline.md) |

Each primitive has a protocol in `cognitia.protocols.multi_agent` and one or more implementations in `cognitia.multi_agent`.

## Agent-as-Tool

The agent-as-tool pattern lets an orchestrating agent call a sub-agent as if it were a regular tool. The sub-agent runs to completion, and the orchestrator receives its output as a tool result.

### Creating a Tool Spec

Use `create_agent_tool_spec` to define a tool that represents a sub-agent:

```python
from cognitia.multi_agent import create_agent_tool_spec

spec = create_agent_tool_spec(
    name="researcher",
    description="Research a topic and return a summary",
)
# spec is a ToolSpec with a single required "query" parameter
```

The returned `ToolSpec` has a JSON Schema with one required string parameter `query` -- the prompt sent to the sub-agent.

### Executing the Sub-Agent

Use `execute_agent_tool` to run a sub-agent runtime and collect the final result:

```python
from cognitia.multi_agent import execute_agent_tool

result = await execute_agent_tool(
    run_fn=sub_agent_runtime.run,
    query="Summarize recent advances in quantum computing",
    system_prompt="You are a research assistant. Be concise.",
    timeout_seconds=120.0,
)

if result.success:
    print(result.output)
else:
    print(f"Failed: {result.error}")
```

Parameters:

- `run_fn` -- async generator with signature `(messages, system_prompt, active_tools) -> AsyncIterator[RuntimeEvent]`
- `query` -- the user message sent to the sub-agent
- `system_prompt` -- system prompt for the sub-agent (default: `"You are a helpful assistant."`)
- `timeout_seconds` -- maximum execution time (default: `60.0`)

### AgentToolResult

The result is a frozen dataclass with these fields:

```python
from cognitia.multi_agent import AgentToolResult

# Fields:
#   success: bool           -- True if completed without error
#   output: str             -- final text from the sub-agent
#   error: str | None       -- error message if failed
#   agent_id: str           -- identifier of the agent (default: "")
#   tokens_used: int        -- token consumption (default: 0)
#   cost_usd: float         -- cost in USD (default: 0.0)
```

### Full Example

```python
from cognitia import Agent, AgentConfig
from cognitia.multi_agent import create_agent_tool_spec, execute_agent_tool

# 1. Create the sub-agent
sub_agent = Agent(AgentConfig(
    system_prompt="You are a code reviewer. Review code for bugs and style issues.",
    runtime="thin",
    model="sonnet",
))

# 2. Create a tool spec for the orchestrator
reviewer_tool = create_agent_tool_spec(
    name="code_reviewer",
    description="Review code for bugs and style issues",
)

# 3. In the orchestrator's tool handler, execute the sub-agent
async def handle_tool_call(tool_name: str, args: dict) -> str:
    if tool_name == "code_reviewer":
        result = await execute_agent_tool(
            run_fn=sub_agent._runtime.run,
            query=args["query"],
            system_prompt="You are a code reviewer.",
            timeout_seconds=90.0,
        )
        return result.output if result.success else f"Error: {result.error}"
    return "Unknown tool"
```

## Task Queue

The task queue distributes work items between agents. Tasks have priority-based scheduling and lifecycle tracking.

### Domain Types

```python
from cognitia.multi_agent import TaskItem, TaskStatus, TaskPriority, TaskFilter

# Create a task
task = TaskItem(
    id="task-001",
    title="Analyze sales data",
    description="Generate Q4 report from sales.csv",
    priority=TaskPriority.HIGH,
    assignee_agent_id="analyst-1",
)

# Filter tasks
pending = TaskFilter(status=TaskStatus.TODO)
my_tasks = TaskFilter(assignee_agent_id="analyst-1")
urgent = TaskFilter(priority=TaskPriority.CRITICAL)
```

**TaskStatus** values: `TODO`, `IN_PROGRESS`, `DONE`, `CANCELLED`.

**TaskPriority** values: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`.

### InMemoryTaskQueue

Zero-dependency, thread-safe via `asyncio.Lock`:

```python
from cognitia.multi_agent import InMemoryTaskQueue, TaskItem, TaskPriority

queue = InMemoryTaskQueue()

# Add tasks
await queue.put(TaskItem(id="t1", title="Research", priority=TaskPriority.HIGH))
await queue.put(TaskItem(id="t2", title="Write report", priority=TaskPriority.MEDIUM))

# Claim highest-priority unassigned task
task = await queue.get()
# task.id == "t1" and task.status == TaskStatus.IN_PROGRESS

# Claim a task pre-assigned to a specific agent
assigned = await queue.get(TaskFilter(assignee_agent_id="analyst-1"))

# Mark complete
await queue.complete("t1")  # returns True

# List all tasks
all_tasks = await queue.list_tasks()

# List filtered
from cognitia.multi_agent import TaskFilter, TaskStatus
pending = await queue.list_tasks(TaskFilter(status=TaskStatus.TODO))
```

### SqliteTaskQueue

File-based persistence using SQLite. Uses `asyncio.to_thread()` for non-blocking I/O:

```python
from cognitia.multi_agent import SqliteTaskQueue, TaskItem, TaskPriority

queue = SqliteTaskQueue(db_path="tasks.db")

await queue.put(TaskItem(id="t1", title="Process data", priority=TaskPriority.HIGH))
task = await queue.get()

# Clean up when done
queue.close()
```

The API is identical to `InMemoryTaskQueue`. The SQLite backend persists tasks across restarts.

### Task Queue API

All implementations expose these 5 methods (ISP-compliant):

| Method | Signature | Description |
|--------|-----------|-------------|
| `put` | `(item: TaskItem) -> None` | Add a task to the queue |
| `get` | `(filters?) -> TaskItem \| None` | Claim highest-priority matching TODO task |
| `complete` | `(task_id: str) -> bool` | Mark task as DONE |
| `cancel` | `(task_id: str) -> bool` | Mark task as CANCELLED |
| `list_tasks` | `(filters?) -> list[TaskItem]` | List tasks matching filters |

`get()` only claims tasks with status `TODO`. Without `assignee_agent_id`, it only returns unassigned tasks. With `TaskFilter(assignee_agent_id="...")`, it only returns tasks pre-assigned to that agent. A claimed task is persisted as `IN_PROGRESS`. Tasks in `DONE` or `CANCELLED` status are terminal and cannot be completed or cancelled again.

## Agent Registry

The agent registry tracks registered agents, their roles, statuses, and metadata.

### Domain Types

```python
from cognitia.multi_agent import AgentRecord, AgentStatus, AgentFilter

# Register an agent
record = AgentRecord(
    id="researcher-1",
    name="Research Agent",
    role="researcher",
    runtime_name="thin",
    runtime_config={"model": "sonnet"},
    budget_limit_usd=5.0,
)

# Filter agents
idle_researchers = AgentFilter(role="researcher", status=AgentStatus.IDLE)
```

**AgentStatus** values: `IDLE`, `RUNNING`, `STOPPED`.

**AgentRecord** fields:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | `str` | required | Unique agent identifier |
| `name` | `str` | required | Human-readable name |
| `role` | `str` | required | Agent role (e.g. "researcher", "coder") |
| `parent_id` | `str \| None` | `None` | Parent agent ID for hierarchies |
| `runtime_name` | `str` | `"thin"` | Runtime to use |
| `runtime_config` | `dict` | `{}` | Runtime-specific config |
| `status` | `AgentStatus` | `IDLE` | Current lifecycle status |
| `budget_limit_usd` | `float \| None` | `None` | Spending cap |
| `metadata` | `dict` | `{}` | Arbitrary key-value data |

### InMemoryAgentRegistry

Thread-safe in-memory implementation:

```python
from cognitia.multi_agent import InMemoryAgentRegistry, AgentRecord, AgentStatus, AgentFilter

registry = InMemoryAgentRegistry()

# Register agents
await registry.register(AgentRecord(
    id="coder-1", name="Coder", role="coder",
))
await registry.register(AgentRecord(
    id="reviewer-1", name="Reviewer", role="reviewer",
))

# Look up by ID
agent = await registry.get("coder-1")

# List all agents with a specific role
coders = await registry.list_agents(AgentFilter(role="coder"))

# Update lifecycle status
await registry.update_status("coder-1", AgentStatus.RUNNING)

# Remove an agent
await registry.remove("reviewer-1")
```

!!! warning "Duplicate IDs"
    `register()` raises `ValueError` if an agent with the same `id` is already registered.

### Agent Registry API

All implementations expose these 5 methods (ISP-compliant):

| Method | Signature | Description |
|--------|-----------|-------------|
| `register` | `(record: AgentRecord) -> None` | Register a new agent |
| `get` | `(agent_id: str) -> AgentRecord \| None` | Get agent by ID |
| `list_agents` | `(filters?) -> list[AgentRecord]` | List agents matching filters |
| `update_status` | `(agent_id, status) -> bool` | Update agent status |
| `remove` | `(agent_id: str) -> bool` | Remove agent from registry |

## Protocols

All multi-agent components are defined as `@runtime_checkable` protocols in `cognitia.protocols.multi_agent`:

```python
from cognitia.protocols.multi_agent import AgentTool, TaskQueue, AgentRegistry
```

### AgentTool Protocol

Single-method protocol for exposing an agent as a tool:

```python
@runtime_checkable
class AgentTool(Protocol):
    def as_tool(self, name: str, description: str) -> ToolSpec: ...
```

### TaskQueue Protocol

Five async methods for task lifecycle:

```python
@runtime_checkable
class TaskQueue(Protocol):
    async def put(self, item: TaskItem) -> None: ...
    async def get(self, filters: TaskFilter | None = None) -> TaskItem | None: ...
    async def complete(self, task_id: str) -> bool: ...
    async def cancel(self, task_id: str) -> bool: ...
    async def list_tasks(self, filters: TaskFilter | None = None) -> list[TaskItem]: ...
```

### AgentRegistry Protocol

Five async methods for agent lifecycle management:

```python
@runtime_checkable
class AgentRegistry(Protocol):
    async def register(self, record: AgentRecord) -> None: ...
    async def get(self, agent_id: str) -> AgentRecord | None: ...
    async def list_agents(self, filters: AgentFilter | None = None) -> list[AgentRecord]: ...
    async def update_status(self, agent_id: str, status: AgentStatus) -> bool: ...
    async def remove(self, agent_id: str) -> bool: ...
```

## Custom Implementations

To create a custom implementation, implement the corresponding protocol. Use `isinstance()` checks at runtime thanks to `@runtime_checkable`:

```python
from cognitia.protocols.multi_agent import TaskQueue
from cognitia.multi_agent import TaskItem, TaskFilter

class RedisTaskQueue:
    """Redis-backed task queue."""

    def __init__(self, redis_url: str) -> None:
        self._url = redis_url
        # Initialize Redis connection

    async def put(self, item: TaskItem) -> None:
        # Store task in Redis sorted set by priority
        ...

    async def get(self, filters: TaskFilter | None = None) -> TaskItem | None:
        # Atomically claim highest-priority matching TODO task
        ...

    async def complete(self, task_id: str) -> bool:
        # Move task to completed set
        ...

    async def cancel(self, task_id: str) -> bool:
        # Move task to cancelled set
        ...

    async def list_tasks(self, filters: TaskFilter | None = None) -> list[TaskItem]:
        # Query tasks matching filters
        ...

# Verify protocol compliance
assert isinstance(RedisTaskQueue("redis://localhost"), TaskQueue)
```

The same pattern applies for `AgentRegistry` -- implement all 5 methods with matching signatures.

## Next Steps

- [CLI Runtime](cli-runtime.md) -- run external CLI agents as subprocesses
- [Orchestration](orchestration.md) -- planning mode, subagents, team coordination
- [Runtimes](runtimes.md) -- available runtime backends
- [Architecture](architecture.md) -- Clean Architecture layers and protocol design
