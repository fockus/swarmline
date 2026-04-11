# Agent Graph System

Swarmline's Agent Graph System models **hierarchical multi-agent organizations** as directed graphs. Each agent occupies a node with a role, capabilities, and position in a chain of command. A root agent decomposes goals into subtasks, delegates them down the hierarchy, and collects results -- all with governance guardrails, DAG-based task scheduling, and inter-agent messaging.

## Overview

The Agent Graph System is built around six primitives:

| Primitive | Purpose | Protocol |
|-----------|---------|----------|
| **Agent Graph** | Hierarchical tree of agent nodes | `AgentGraphStore`, `AgentGraphQuery` |
| **Task Board** | Hierarchical tasks with atomic checkout and DAG deps | `GraphTaskBoard`, `GraphTaskScheduler`, `GraphTaskBlocker` |
| **Orchestrator** | Execution engine: goal decomposition, delegation, retry | `GraphOrchestrator`, `GraphTaskWaiter` |
| **Communication** | Direct, broadcast, and escalation messaging | `GraphCommunication` |
| **Governance** | Capability-based permissions and global limits | `AgentCapabilities`, `GraphGovernanceConfig` |
| **Graph Tools** | Agent-callable tools: hire, delegate, escalate | `create_graph_tools` factory |

Each primitive has a `@runtime_checkable` protocol in `swarmline.protocols` and one or more implementations in `swarmline.multi_agent`.

**When to use:** You need a structured multi-agent system with reporting lines, permission controls, and task hierarchies -- rather than flat agent-as-tool invocation. Typical use cases: autonomous software teams, research organizations, multi-step workflows with approval gates.

## Quick Start

Build a minimal two-agent graph and run a task:

```python
from swarmline.multi_agent import InMemoryAgentGraph, InMemoryGraphTaskBoard
from swarmline.multi_agent.graph_builder import GraphBuilder
from swarmline.multi_agent.graph_orchestrator import DefaultGraphOrchestrator
from swarmline.multi_agent.graph_types import AgentCapabilities

# 1. Create storage backends
graph = InMemoryAgentGraph()
task_board = InMemoryGraphTaskBoard()

# 2. Build the agent hierarchy
builder = GraphBuilder(graph)
builder.add_root(
    "lead", "Tech Lead", "lead",
    system_prompt="You decompose tasks and delegate to engineers.",
    capabilities=AgentCapabilities(can_hire=True, can_delegate=True),
)
builder.add_child(
    "eng1", "lead", "Engineer", "engineer",
    system_prompt="You write Python code.",
    allowed_tools=("file_write", "run_tests"),
)
snapshot = await builder.build()

# 3. Define the agent runner (your LLM call)
async def run_agent(agent_id: str, task_id: str, goal: str, system_prompt: str) -> str:
    # Call your LLM here with the system_prompt and goal
    return f"Result from {agent_id}: done"

# 4. Start the orchestrator
orchestrator = DefaultGraphOrchestrator(
    graph=graph,
    task_board=task_board,
    agent_runner=run_agent,
    max_concurrent=5,
    max_retries=2,
)
run_id = await orchestrator.start("Build a REST API for user management")

# 5. Wait for the root task and get results
status = await orchestrator.get_status(run_id)
result = await orchestrator.wait_for_task(status.root_task_id, timeout=120.0)
```

## AgentNode

`AgentNode` is a frozen dataclass representing an agent in the graph:

```python
from swarmline.multi_agent.graph_types import AgentNode, AgentCapabilities

node = AgentNode(
    id="eng1",
    name="Backend Engineer",
    role="engineer",
    system_prompt="You are a backend engineer. Write clean Python code.",
    parent_id="lead",
    allowed_tools=("file_write", "run_tests", "git_commit"),
    skills=("python", "fastapi"),
    mcp_servers=("filesystem", "git"),
    capabilities=AgentCapabilities(
        can_hire=False,
        can_delegate=True,
        max_children=3,
    ),
    runtime_config={"model": "sonnet", "temperature": 0.2},
    budget_limit_usd=5.0,
    metadata={"team": "backend"},
)
```

### AgentNode Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | `str` | required | Unique node identifier |
| `name` | `str` | required | Human-readable name |
| `role` | `str` | required | Agent role (e.g. "engineer", "designer") |
| `system_prompt` | `str` | `""` | Instructions for the agent |
| `parent_id` | `str \| None` | `None` | Parent node ID (`None` = root) |
| `allowed_tools` | `tuple[str, ...]` | `()` | Tools this agent can use |
| `skills` | `tuple[str, ...]` | `()` | Skill identifiers |
| `mcp_servers` | `tuple[str, ...]` | `()` | MCP server names available to agent |
| `capabilities` | `AgentCapabilities` | defaults | Permission flags |
| `runtime_config` | `dict \| None` | `None` | Runtime config (`None` = inherit from parent) |
| `budget_limit_usd` | `float \| None` | `None` | Spending cap |
| `status` | `AgentStatus` | `IDLE` | Lifecycle status: `IDLE`, `RUNNING`, `STOPPED` |
| `metadata` | `dict` | `{}` | Arbitrary key-value data |

### AgentCapabilities

Per-agent permission flags configured on creation:

```python
from swarmline.multi_agent.graph_types import AgentCapabilities

caps = AgentCapabilities(
    can_hire=True,           # can create new agent nodes
    can_delegate=True,       # can delegate tasks to children
    max_children=5,          # max direct reports (None = unlimited)
    can_use_subagents=True,  # can spawn subagents outside the graph
    allowed_subagent_ids=("researcher-1",),  # restrict to specific subagents
    can_use_team_mode=False, # can use team coordination mode
)
```

## GraphBuilder

The `GraphBuilder` provides a fluent API for constructing agent hierarchies. It supports programmatic construction, dict-based configuration, and YAML files.

### Fluent API

```python
from swarmline.multi_agent.graph_builder import GraphBuilder
from swarmline.multi_agent.graph_types import AgentCapabilities

builder = GraphBuilder(store)

# Chain calls fluently
snapshot = await (
    builder
    .add_root("ceo", "CEO", "executive",
              system_prompt="You lead the organization.",
              capabilities=AgentCapabilities(can_hire=True, can_delegate=True))
    .add_child("cto", "ceo", "CTO", "tech_lead",
               capabilities=AgentCapabilities(can_hire=True, can_delegate=True))
    .add_child("eng1", "cto", "Engineer 1", "engineer",
               allowed_tools=("file_write",))
    .add_child("eng2", "cto", "Engineer 2", "engineer",
               allowed_tools=("file_write",))
    .add_child("designer", "ceo", "Designer", "designer",
               skills=("figma",), mcp_servers=("figma-console",))
    .build()
)
# snapshot.root_id == "ceo"
# snapshot.nodes has 5 nodes
# snapshot.edges has 4 REPORTS_TO edges
```

### From Dict

Build a graph from a nested dictionary structure:

```python
config = {
    "id": "ceo", "name": "CEO", "role": "executive",
    "system_prompt": "You lead the organization.",
    "capabilities": {"can_hire": True, "can_delegate": True},
    "children": [
        {
            "id": "cto", "name": "CTO", "role": "tech_lead",
            "children": [
                {"id": "eng1", "name": "Engineer", "role": "engineer",
                 "allowed_tools": ["file_write", "run_tests"]},
            ],
        },
    ],
}

snapshot = await GraphBuilder.from_dict(config, store)
```

### From YAML

```python
snapshot = await GraphBuilder.from_yaml("org.yaml", store)
```

Example `org.yaml`:

```yaml
id: ceo
name: CEO
role: executive
system_prompt: You lead the organization.
capabilities:
  can_hire: true
  can_delegate: true
children:
  - id: cto
    name: CTO
    role: tech_lead
    children:
      - id: eng1
        name: Engineer
        role: engineer
        allowed_tools: [file_write, run_tests]
```

### GraphBuilder API

| Method | Signature | Description |
|--------|-----------|-------------|
| `add_root` | `(id, name, role, **kwargs) -> GraphBuilder` | Add the root node |
| `add_child` | `(id, parent_id, name, role, **kwargs) -> GraphBuilder` | Add a child node |
| `build` | `() -> GraphSnapshot` | Flush nodes to store, return snapshot |
| `from_dict` | `(config, store) -> GraphSnapshot` | Class method: build from nested dict |
| `from_yaml` | `(path, store) -> GraphSnapshot` | Class method: build from YAML file |

## Governance

Governance enforces **global limits** and **per-agent permissions** before graph mutations.

### GraphGovernanceConfig

Global limits for the entire graph:

```python
from swarmline.multi_agent.graph_governance import GraphGovernanceConfig

governance = GraphGovernanceConfig(
    max_agents=50,                # maximum total nodes in the graph
    max_depth=5,                  # maximum hierarchy depth
    default_capabilities=AgentCapabilities(),
    allow_dynamic_hiring=True,    # can agents create new nodes at runtime?
    allow_dynamic_delegation=True,  # can agents delegate tasks at runtime?
)
```

### Governance Checks

Two enforcement functions validate operations before they execute:

```python
from swarmline.multi_agent.graph_governance import (
    check_hire_allowed,
    check_delegate_allowed,
    GovernanceError,
)

# Check if a parent agent can hire a new child
error = await check_hire_allowed(governance, parent_node, graph)
if error:
    print(f"Denied: {error}")
    # e.g. "Agent 'Engineer' does not have can_hire permission"
    # e.g. "Max graph depth (5) would be exceeded"
    # e.g. "Max agents (50) would be exceeded"

# Check if an agent can delegate tasks
error = check_delegate_allowed(governance, agent_node)
if error:
    print(f"Denied: {error}")
    # e.g. "Dynamic delegation is globally disabled"
```

**Checks performed by `check_hire_allowed`:**

1. Global `allow_dynamic_hiring` is enabled
2. Parent agent has `can_hire=True` in capabilities
3. Parent has not reached `max_children` limit
4. Adding a child would not exceed `max_depth`
5. Total agent count would not exceed `max_agents`

## Task Board

The `GraphTaskBoard` manages hierarchical tasks with parent-child relationships, atomic checkout, DAG dependencies, and automatic progress propagation.

### GraphTaskItem

A task in the hierarchical board:

```python
from swarmline.multi_agent.graph_task_types import GraphTaskItem
from swarmline.multi_agent.task_types import TaskStatus, TaskPriority

task = GraphTaskItem(
    id="task-001",
    title="Implement user authentication",
    description="Add JWT-based auth with refresh tokens",
    priority=TaskPriority.HIGH,
    assignee_agent_id="eng1",
    parent_task_id="task-root",
    dependencies=("task-db-setup", "task-models"),  # DAG edges
    dod_criteria=("Unit tests pass", "Integration test with DB"),
    estimated_effort="M",  # XS/S/M/L/XL
    stage="development",
)
```

### GraphTaskItem Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | `str` | required | Unique task identifier |
| `title` | `str` | required | Task title |
| `description` | `str` | `""` | Detailed description |
| `status` | `TaskStatus` | `TODO` | `TODO`, `IN_PROGRESS`, `DONE`, `CANCELLED`, `BLOCKED` |
| `priority` | `TaskPriority` | `MEDIUM` | `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |
| `assignee_agent_id` | `str \| None` | `None` | Assigned agent |
| `parent_task_id` | `str \| None` | `None` | Parent task for hierarchy |
| `dependencies` | `tuple[str, ...]` | `()` | Task IDs that must be DONE first |
| `dod_criteria` | `tuple[str, ...]` | `()` | Definition of Done checklist |
| `checkout_agent_id` | `str \| None` | `None` | Atomic lock -- agent currently working |
| `progress` | `float` | `0.0` | 0.0 to 1.0, auto-propagated from children |
| `blocked_reason` | `str` | `""` | Why the task is blocked |
| `stage` | `str` | `""` | Custom workflow stage name |

### Task Lifecycle

```python
from swarmline.multi_agent import InMemoryGraphTaskBoard
from swarmline.multi_agent.graph_task_types import GraphTaskItem

board = InMemoryGraphTaskBoard()

# Create a task
await board.create_task(GraphTaskItem(id="t1", title="Build API"))

# Atomic checkout -- only one agent can claim a task
claimed = await board.checkout_task("t1", "eng1")
# claimed is the updated task with status=IN_PROGRESS, or None if already claimed

# Complete -- auto-propagates progress to parent
await board.complete_task("t1")

# List with filters
from swarmline.multi_agent.task_types import TaskStatus
tasks = await board.list_tasks(status=TaskStatus.TODO, assignee_agent_id="eng1")
```

### DAG Dependencies

Tasks can declare dependencies that must be `DONE` before the task becomes ready:

```python
# Task "deploy" depends on "build" and "test"
await board.create_task(GraphTaskItem(id="build", title="Build"))
await board.create_task(GraphTaskItem(id="test", title="Test"))
await board.create_task(GraphTaskItem(
    id="deploy", title="Deploy",
    dependencies=("build", "test"),
))

# Query ready tasks (all deps DONE, status TODO, not checked out)
ready = await board.get_ready_tasks()
# "deploy" will NOT appear until "build" and "test" are DONE

# See what blocks a task
blockers = await board.get_blocked_by("deploy")
# Returns the GraphTaskItem objects for "build" and "test" if not DONE
```

### Blocking and Unblocking

Explicitly block a task with a mandatory reason:

```python
# Block a task -- releases checkout, sets status to BLOCKED
await board.block_task("t1", reason="Waiting for API credentials")

# Unblock -- returns task to TODO status
await board.unblock_task("t1")
```

### Progress Propagation

When a child task is completed, the parent's progress is automatically recalculated as the average of its children's progress. If all children are `DONE`, the parent is also marked `DONE` -- recursively up the tree.

### WorkflowConfig

Map custom workflow stages to core `TaskStatus` values:

```python
from swarmline.multi_agent.graph_task_types import WorkflowConfig, WorkflowStage
from swarmline.multi_agent.task_types import TaskStatus

workflow = WorkflowConfig(
    name="software-development",
    stages=(
        WorkflowStage(name="backlog", maps_to=TaskStatus.TODO, order=0),
        WorkflowStage(name="development", maps_to=TaskStatus.IN_PROGRESS, order=1),
        WorkflowStage(name="code-review", maps_to=TaskStatus.IN_PROGRESS, order=2),
        WorkflowStage(name="testing", maps_to=TaskStatus.IN_PROGRESS, order=3),
        WorkflowStage(name="deployed", maps_to=TaskStatus.DONE, order=4),
    ),
)

# Lookup
stage = workflow.stage_for("code-review")
# stage.maps_to == TaskStatus.IN_PROGRESS

# Get all stages for a status
in_progress = workflow.stages_for_status(TaskStatus.IN_PROGRESS)
# Returns development, code-review, testing
```

### Task Comments

Attach audit-trail comments to tasks:

```python
from swarmline.multi_agent.graph_task_types import TaskComment

await board.add_comment(TaskComment(
    id="c1", task_id="t1", author_agent_id="eng1",
    content="Started implementation. Using FastAPI.",
))

comments = await board.get_comments("t1")
# All comments on this specific task

thread = await board.get_thread("t1")
# All comments on t1 AND its subtasks (recursive)
```

## Communication

Inter-agent messaging with three channel types: direct, broadcast, and escalation.

### Channel Types

| Channel | Description | Scope |
|---------|-------------|-------|
| `DIRECT` | Point-to-point message | One sender, one recipient |
| `BROADCAST` | Downward announcement | From agent to entire subtree |
| `ESCALATION` | Upward issue report | From agent to all ancestors |

### InMemoryGraphCommunication

```python
from swarmline.multi_agent.graph_communication import InMemoryGraphCommunication
from swarmline.multi_agent.graph_comm_types import GraphMessage, ChannelType

comm = InMemoryGraphCommunication(graph_query=graph)

# Direct message between agents
await comm.send_direct(GraphMessage(
    id="msg-1",
    from_agent_id="lead",
    to_agent_id="eng1",
    content="Please prioritize the auth module.",
    task_id="task-001",
))

# Broadcast to all descendants
await comm.broadcast_subtree(
    "lead", "Sprint goal updated: focus on security.",
    task_id="task-root",
)

# Escalate to all ancestors in chain of command
await comm.escalate(
    "eng1", "Blocked: missing API credentials.",
    task_id="task-001",
)

# Read inbox
messages = await comm.get_inbox("eng1")

# Get all messages for a task
thread = await comm.get_thread("task-001")
```

### GraphMessage Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | `str` | required | Unique message ID |
| `from_agent_id` | `str` | required | Sender agent ID |
| `to_agent_id` | `str \| None` | `None` | Recipient (None for broadcast) |
| `channel` | `ChannelType` | `DIRECT` | `DIRECT`, `BROADCAST`, `ESCALATION` |
| `content` | `str` | `""` | Message body |
| `task_id` | `str \| None` | `None` | Related task for threading |
| `metadata` | `dict` | `{}` | Arbitrary key-value data |

All communication methods optionally emit events via `EventBus` if one is provided during construction.

## Context Builder

The `GraphContextBuilder` enriches each agent's system prompt with its position in the graph, chain of command, team, available tools, skills, MCP servers, and goal ancestry. Context is built automatically by the orchestrator before each agent execution.

### AgentExecutionContext

The structured context passed to the agent runner:

```python
from swarmline.multi_agent.graph_execution_context import AgentExecutionContext

# Built automatically by the orchestrator, but can be constructed manually:
ctx = AgentExecutionContext(
    agent_id="eng1",
    task_id="task-001",
    goal="Implement JWT authentication",
    system_prompt="## Your Identity\nYou are Engineer 1, role: engineer.\n...",
    tools=("file_write", "run_tests"),
    skills=("python", "fastapi"),
    mcp_servers=("filesystem",),
    runtime_config={"model": "sonnet"},
    budget_limit_usd=5.0,
)
```

### Context Propagation

Tools, skills, and MCP servers are **inherited from ancestors**: an agent receives its own plus all ancestors' tools/skills/MCP servers (deduplicated). Runtime config uses **nearest-ancestor inheritance**: the first non-`None` config walking up the chain is used.

```python
from swarmline.multi_agent.graph_context import GraphContextBuilder

ctx_builder = GraphContextBuilder(
    graph_query=graph,
    task_board=task_board,
    token_budget=4000,  # truncates shared knowledge to fit
)

# Build a full context snapshot
snapshot = await ctx_builder.build_context("eng1", task_id="task-001")
# snapshot.chain_of_command == ("CEO", "CTO", "Engineer 1")
# snapshot.sibling_agents == ("Engineer 2",)
# snapshot.available_tools == ("file_write", "run_tests", ...)  # own + inherited

# Render as a system prompt
prompt = ctx_builder.render_system_prompt(snapshot)
# Includes: Identity, Chain of Command, Goal Ancestry, Team, Tools, Skills,
# MCP Servers, Permissions, Instructions
```

### Context-Aware Runner

The orchestrator auto-detects whether your runner accepts the full `AgentExecutionContext` or the legacy 4-argument signature:

```python
# Context-aware runner (recommended) -- 1 required parameter
async def run_agent(ctx: AgentExecutionContext) -> str:
    # ctx.system_prompt includes graph position, team, permissions
    # ctx.tools, ctx.skills, ctx.mcp_servers are ready to use
    # ctx.runtime_config has the resolved model/temperature
    return await call_llm(
        system_prompt=ctx.system_prompt,
        user_message=ctx.goal,
        model=ctx.runtime_config.get("model", "sonnet"),
    )

# Legacy runner -- 4 positional parameters (still supported)
async def run_agent_legacy(
    agent_id: str, task_id: str, goal: str, system_prompt: str,
) -> str:
    return await call_llm(system_prompt=system_prompt, user_message=goal)
```

## Graph Tools

The `create_graph_tools` factory produces tool definitions that agents can invoke to dynamically modify the organization graph, delegate work, or escalate issues.

```python
from swarmline.multi_agent.graph_tools import create_graph_tools

tools = create_graph_tools(
    graph=graph,
    task_board=task_board,
    orchestrator=orchestrator,
    governance=governance,       # optional: enforce global limits
    approval_gate=approval_gate, # optional: human-in-the-loop
    communication=comm,          # optional: escalation messaging
)
# Returns list of 3 ToolDefinition objects
```

### graph_hire_agent

Dynamically create a new agent node under an existing parent:

```python
# Called by an agent as a tool:
# graph_hire_agent(
#     name="Security Auditor",
#     role="auditor",
#     parent_id="cto",
#     system_prompt="You audit code for security vulnerabilities.",
#     allowed_tools="file_read,security_scan",
# )
```

Governance checks before hiring:
- Parent has `can_hire=True`
- `max_children` not exceeded
- `max_depth` not exceeded
- `max_agents` not exceeded
- Approval gate passes (if configured)

### graph_delegate_task

Delegate a task to a specific agent via the orchestrator:

```python
# Called by an agent as a tool:
# graph_delegate_task(
#     agent_id="eng1",
#     goal="Write unit tests for the auth module",
#     parent_task_id="task-001",
#     caller_agent_id="lead",
#     stage="testing",
# )
```

Creates a new `GraphTaskItem` and launches async execution through the orchestrator.

### graph_escalate

Escalate an issue up the chain of command:

```python
# Called by an agent as a tool:
# graph_escalate(
#     from_agent_id="eng1",
#     message="Cannot proceed: database connection is down.",
#     task_id="task-001",
# )
```

Sends escalation messages to all ancestors in the chain of command via `GraphCommunication`.

## Storage Backends

### InMemoryAgentGraph

Zero-dependency, thread-safe via `asyncio.Lock`. Implements both `AgentGraphStore` and `AgentGraphQuery`:

```python
from swarmline.multi_agent import InMemoryAgentGraph

graph = InMemoryAgentGraph()
await graph.add_node(root_node)
await graph.add_node(child_node)

# Query
root = await graph.get_root()
children = await graph.get_children("ceo")
chain = await graph.get_chain_of_command("eng1")   # [eng1, cto, ceo]
subtree = await graph.get_subtree("cto")            # cto + all descendants
engineers = await graph.find_by_role("engineer")

# Mutation
await graph.update_node("eng1", status=AgentStatus.RUNNING)
await graph.remove_node("eng1")  # cascades to subtree

# Snapshot
snapshot = await graph.snapshot()
# GraphSnapshot(nodes=(...), edges=(...), root_id="ceo")
```

### SqliteAgentGraph

File-based persistence using SQLite with recursive CTEs for efficient tree traversal. Uses `asyncio.to_thread()` for non-blocking I/O:

```python
from swarmline.multi_agent.graph_store_sqlite import SqliteAgentGraph

# File-based (persists across restarts)
graph = SqliteAgentGraph(db_path="agents.db")

# In-memory (for tests)
graph = SqliteAgentGraph(db_path=":memory:")

# API is identical to InMemoryAgentGraph
await graph.add_node(root_node)
chain = await graph.get_chain_of_command("eng1")
```

The SQLite backend uses `PRAGMA journal_mode=WAL` for concurrent read performance and recursive CTEs for `get_chain_of_command` and `get_subtree` queries.

### InMemoryGraphTaskBoard

Implements `GraphTaskBoard`, `GraphTaskScheduler`, `GraphTaskBlocker`, and `TaskCommentStore`:

```python
from swarmline.multi_agent import InMemoryGraphTaskBoard

board = InMemoryGraphTaskBoard()
```

## Orchestrator

The `DefaultGraphOrchestrator` ties all components together into an execution engine:

```python
from swarmline.multi_agent.graph_orchestrator import DefaultGraphOrchestrator

orchestrator = DefaultGraphOrchestrator(
    graph=graph,
    task_board=task_board,
    agent_runner=run_agent,       # your LLM call
    event_bus=event_bus,          # optional: lifecycle events
    communication=comm,           # optional: escalation on failure
    max_concurrent=5,             # semaphore-bounded parallelism
    max_retries=2,                # retry per agent before escalation
    approval_gate=approval_gate,  # optional: HITL for delegation
)
```

### Execution Flow

1. `start(goal)` -- finds the graph root, creates a root task, launches root agent
2. Root agent decomposes the goal, calls `graph_delegate_task` for subtasks
3. Each delegated task launches an agent execution (bounded by semaphore)
4. On success, results are stored and task is marked `DONE`
5. On failure after retries, the agent escalates to its parent
6. Results bubble up -- parent task auto-completes when all children are `DONE`

### Run Status

```python
from swarmline.multi_agent.graph_orchestrator_types import OrchestratorRunState

status = await orchestrator.get_status(run_id)
# status.state: PENDING | RUNNING | COMPLETED | FAILED | STOPPED
# status.executions: tuple of AgentExecution snapshots
# status.completed_count: how many agents finished successfully
# status.failed_count: how many agents failed

# Wait for a specific task
result = await orchestrator.wait_for_task("task-001", timeout=60.0)

# Stop a run (cancels pending tasks)
await orchestrator.stop(run_id)
```

## Protocols

All graph components are defined as `@runtime_checkable` protocols in `swarmline.protocols`:

### AgentGraphStore

Mutation operations on the agent graph (5 methods):

```python
from swarmline.protocols.agent_graph import AgentGraphStore

@runtime_checkable
class AgentGraphStore(Protocol):
    async def add_node(self, node: AgentNode) -> None: ...
    async def remove_node(self, node_id: str) -> bool: ...
    async def get_node(self, node_id: str) -> AgentNode | None: ...
    async def get_children(self, node_id: str) -> list[AgentNode]: ...
    async def snapshot(self) -> GraphSnapshot: ...
```

### AgentGraphQuery

Read-only traversal of the agent graph (4 methods):

```python
from swarmline.protocols.agent_graph import AgentGraphQuery

@runtime_checkable
class AgentGraphQuery(Protocol):
    async def get_chain_of_command(self, node_id: str) -> list[AgentNode]: ...
    async def get_subtree(self, node_id: str) -> list[AgentNode]: ...
    async def get_root(self) -> AgentNode | None: ...
    async def find_by_role(self, role: str) -> list[AgentNode]: ...
```

### AgentNodeUpdater

Partial update without remove+add (1 method):

```python
from swarmline.protocols.agent_graph import AgentNodeUpdater

@runtime_checkable
class AgentNodeUpdater(Protocol):
    async def update_node(self, node_id: str, **updates: Any) -> AgentNode | None: ...
```

### GraphTaskBoard

Hierarchical task management with atomic checkout (5 methods):

```python
from swarmline.protocols.graph_task import GraphTaskBoard

@runtime_checkable
class GraphTaskBoard(Protocol):
    async def create_task(self, task: GraphTaskItem) -> None: ...
    async def checkout_task(self, task_id: str, agent_id: str) -> GraphTaskItem | None: ...
    async def complete_task(self, task_id: str) -> bool: ...
    async def get_subtasks(self, task_id: str) -> list[GraphTaskItem]: ...
    async def list_tasks(self, **filters: Any) -> list[GraphTaskItem]: ...
```

### GraphTaskScheduler

DAG-aware task scheduling (2 methods):

```python
from swarmline.protocols.graph_task import GraphTaskScheduler

@runtime_checkable
class GraphTaskScheduler(Protocol):
    async def get_ready_tasks(self) -> list[GraphTaskItem]: ...
    async def get_blocked_by(self, task_id: str) -> list[GraphTaskItem]: ...
```

### GraphTaskBlocker

Block/unblock tasks (2 methods):

```python
from swarmline.protocols.graph_task import GraphTaskBlocker

@runtime_checkable
class GraphTaskBlocker(Protocol):
    async def block_task(self, task_id: str, reason: str) -> bool: ...
    async def unblock_task(self, task_id: str) -> bool: ...
```

### TaskCommentStore

Persistent comment threads on tasks (3 methods):

```python
from swarmline.protocols.graph_task import TaskCommentStore

@runtime_checkable
class TaskCommentStore(Protocol):
    async def add_comment(self, comment: TaskComment) -> None: ...
    async def get_comments(self, task_id: str) -> list[TaskComment]: ...
    async def get_thread(self, task_id: str) -> list[TaskComment]: ...
```

### GraphCommunication

Inter-agent messaging (5 methods):

```python
from swarmline.protocols.graph_comm import GraphCommunication

@runtime_checkable
class GraphCommunication(Protocol):
    async def send_direct(self, msg: GraphMessage) -> None: ...
    async def broadcast_subtree(self, from_id: str, content: str, *, task_id: str | None = None) -> None: ...
    async def escalate(self, from_id: str, content: str, *, task_id: str | None = None) -> None: ...
    async def get_inbox(self, agent_id: str) -> list[GraphMessage]: ...
    async def get_thread(self, task_id: str) -> list[GraphMessage]: ...
```

### GraphOrchestrator

Hierarchical execution engine (5 methods):

```python
from swarmline.protocols.graph_orchestrator import GraphOrchestrator

@runtime_checkable
class GraphOrchestrator(Protocol):
    async def start(self, goal: str) -> str: ...
    async def delegate(self, request: DelegationRequest) -> None: ...
    async def collect_result(self, task_id: str) -> str | None: ...
    async def get_status(self, run_id: str) -> OrchestratorRunStatus: ...
    async def stop(self, run_id: str) -> None: ...
```

### GraphTaskWaiter

Wait for task completion (1 method, separated from GraphOrchestrator for ISP compliance):

```python
from swarmline.protocols.graph_orchestrator import GraphTaskWaiter

@runtime_checkable
class GraphTaskWaiter(Protocol):
    async def wait_for_task(self, task_id: str, timeout: float | None = None) -> str | None: ...
```

## Custom Implementations

To create a custom backend (e.g. PostgreSQL, Redis), implement the corresponding protocol. Use `isinstance()` checks at runtime thanks to `@runtime_checkable`:

```python
from swarmline.protocols.agent_graph import AgentGraphStore, AgentGraphQuery
from swarmline.multi_agent.graph_types import AgentNode, GraphSnapshot

class PostgresAgentGraph:
    """PostgreSQL-backed agent graph with CTE traversal."""

    def __init__(self, pool) -> None:
        self._pool = pool

    # AgentGraphStore methods
    async def add_node(self, node: AgentNode) -> None: ...
    async def remove_node(self, node_id: str) -> bool: ...
    async def get_node(self, node_id: str) -> AgentNode | None: ...
    async def get_children(self, node_id: str) -> list[AgentNode]: ...
    async def snapshot(self) -> GraphSnapshot: ...

    # AgentGraphQuery methods
    async def get_chain_of_command(self, node_id: str) -> list[AgentNode]: ...
    async def get_subtree(self, node_id: str) -> list[AgentNode]: ...
    async def get_root(self) -> AgentNode | None: ...
    async def find_by_role(self, role: str) -> list[AgentNode]: ...

# Verify compliance
pg = PostgresAgentGraph(pool)
assert isinstance(pg, AgentGraphStore)
assert isinstance(pg, AgentGraphQuery)
```

## Next Steps

- [Multi-Agent Coordination](multi-agent.md) -- flat agent-as-tool, task queues, agent registry
- [Orchestration](orchestration.md) -- planning mode, subagents, team coordination
- [Tools and Skills](tools-and-skills.md) -- tool decorator, MCP skills
- [Architecture](architecture.md) -- Clean Architecture layers and protocol design
