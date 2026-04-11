# Capabilities

Swarmline provides 6 independent capabilities. Each is enabled with a separate toggle -- include only what you need.

## Readiness Status

| Capability | Status | Notes |
| ---------- | ------ | ----- |
| Sandbox | ready | Local/Docker/E2B with timeout, denied commands, path isolation; host execution is opt-in |
| Web | partial | HTTPX provider implements basic fetch/search MVP |
| Todo | ready | InMemory/Filesystem/Database (Postgres + SQLite) |
| Memory Bank | ready | Filesystem + Database backend, auto-loads `MEMORY.md` |
| Planning | staged | Workflow is stable, persistence is InMemory PlanStore only |
| Thinking | ready | Standalone tool with no external dependencies |

## Overview

| Capability | Toggle | Tools | Extras |
| ---------- | ------ | ----- | ------ |
| **Sandbox** | `sandbox_provider=` | bash, read, write, edit, multi_edit, ls, glob, grep | -- |
| **Web** | `web_provider=` | web_fetch, web_search | `swarmline[web]` |
| **Todo** | `todo_provider=` | todo_read, todo_write | -- |
| **Memory Bank** | `memory_bank_provider=` | memory_read, memory_write, memory_append, memory_list, memory_delete | -- |
| **Planning** | `plan_manager=` | plan_create, plan_status, plan_execute | -- |
| **Thinking** | `thinking_enabled=True` | thinking | -- |

---

## Sandbox -- File and Code Isolation

The agent reads/writes files within an isolated workspace. Local host command execution is not enabled by default; opt in only for trusted operators.
Each user + topic combination gets a separate namespace: `{root_path}/{user_id}/{topic_id}/workspace/`.

### Sandbox Providers

| Provider | Use case | Extras |
| -------- | -------- | ------ |
| `LocalSandboxProvider` | Development, testing; host execution opt-in | -- |
| `E2BSandboxProvider` | Production (cloud) | `swarmline[e2b]` |
| `DockerSandboxProvider` | Production (self-hosted) | `swarmline[docker]` |

### Sandbox Usage

```python
from swarmline.tools.sandbox_local import LocalSandboxProvider
from swarmline.tools.types import SandboxConfig

sandbox = LocalSandboxProvider(SandboxConfig(
    root_path="/data/sandbox",
    user_id="user-42",
    topic_id="project-7",
    max_file_size_bytes=10 * 1024 * 1024,  # 10 MB
    timeout_seconds=30,
    denied_commands=frozenset({"rm", "sudo", "kill"}),
))
```

### Security

- Path traversal (`../`) is blocked via `Path.is_relative_to()`
- Absolute paths are rejected
- Host execution is disabled by default (`allow_host_execution=False`)
- Denied commands: configurable blocklist of prohibited shell commands
- Timeout: commands are killed after `timeout_seconds`
- Size limit: files exceeding `max_file_size_bytes` are rejected

---

## Todo -- Checklists and Task Tracking

The agent maintains a structured task list. Operates **independently of Sandbox** -- it is a separate capability.

### Todo Providers

| Provider | Storage | Use case |
| -------- | ------- | -------- |
| `InMemoryTodoProvider` | Process memory | Development, session-scoped |
| `FilesystemTodoProvider` | JSON file | Simple projects |
| `DatabaseTodoProvider` | Postgres/SQLite | Production |

### Todo Usage

```python
from swarmline.todo.inmemory_provider import InMemoryTodoProvider

todo = InMemoryTodoProvider(user_id="user-1", topic_id="task-1", max_todos=100)
```

### Agent API

- `todo_read(status_filter?)` -- read tasks (optionally filtered by status)
- `todo_write(todos)` -- write tasks (bulk replace)

Statuses: `pending`, `in_progress`, `completed`, `cancelled`.

---

## Memory Bank -- Long-Term Memory

The agent persists knowledge across sessions: decisions, preferences, lessons learned.
Structure is file-based with subfolders (2 levels deep).

### Directory Structure

```text
{root}/{user_id}/{topic_id}/memory/
├── MEMORY.md                    # Index (loaded into prompt)
├── progress.md                  # Progress log
├── lessons.md                   # Lessons learned
├── plans/                       # Subfolder
│   └── 2026-02-12_feature.md
├── reports/
│   └── 2026-02-12_session.md
└── notes/
    └── 2026-02-12_15-30_topic.md
```

### Memory Bank Providers

| Provider                       | Backend         | Extras                                     |
| ------------------------------ | --------------- | ------------------------------------------ |
| `FilesystemMemoryBankProvider` | Files           | --                                         |
| `DatabaseMemoryBankProvider`   | Postgres/SQLite | `swarmline[postgres]` or `swarmline[sqlite]` |

### Configuration

```python
from swarmline.memory_bank.types import MemoryBankConfig

config = MemoryBankConfig(
    enabled=True,
    backend="filesystem",
    root_path=Path("/data/memory"),
    max_file_size_bytes=100 * 1024,      # 100 KB per file
    max_entries=200,                      # max files
    max_depth=2,                          # root/subfolder/file
    auto_load_on_turn=True,              # load MEMORY.md into prompt
    auto_load_max_lines=200,
    default_folders=["plans", "reports", "notes"],
)
```

### Auto-Load

When `auto_load_on_turn=True`, the contents of `MEMORY.md` (first N lines) are automatically injected into the system prompt via `ContextBuilder`. This ensures the agent always "remembers" key context from previous sessions.

### DDL for Database Backend

The library exports DDL statements for use in your application's migrations:

```python
from swarmline.memory_bank.schema import get_memory_bank_ddl

# For Postgres
stmts = get_memory_bank_ddl(dialect="postgres")

# For SQLite
stmts = get_memory_bank_ddl(dialect="sqlite")
```

---

## Planning -- Step-by-Step Task Execution

The agent creates plans for complex tasks, executes them step by step, and tracks progress.

### Workflow

1. The agent determines a task is complex and calls `plan_create(goal="...")`
2. The LLM generates a plan (list of steps)
3. The plan is approved (automatically or by the user)
4. Steps are executed sequentially, each with access to tools
5. If a step fails -- execution stops or the plan is regenerated

### Programmatic Control

```python
from swarmline.orchestration.manager import PlanManager
from swarmline.orchestration.thin_planner import ThinPlannerMode
from swarmline.orchestration.plan_store import InMemoryPlanStore

store = InMemoryPlanStore()
planner = ThinPlannerMode(llm=llm_client, plan_store=store)
manager = PlanManager(planner=planner, plan_store=store)

# From application code
plan = await manager.create_plan("Portfolio analysis", user_id="u1", topic_id="t1")
approved = await manager.approve_plan(plan.id, by="system")

async for step in manager.execute_plan(plan.id):
    print(f"[{step.status}] {step.description}: {step.result}")
```

---

## Thinking -- Structured Reasoning

Chain-of-Thought + ReAct: the agent records its reasoning and planned next steps before taking action.

```python
# Agent calls:
thinking(thought="Need to find deposits with yield >15%",
         next_steps=["Fetch deposit list", "Filter by rate"])
```

Thinking is a standalone tool with no external dependencies. Recommended to always enable.

---

## Web -- Internet Access

```python
from swarmline.tools.web_httpx import HttpxWebProvider

web = HttpxWebProvider(timeout=30)
# Agent receives: web_fetch(url), web_search(query)
```

The `HttpxWebProvider` supports pluggable sub-providers:

- **Fetch**: defaults to httpx GET + trafilatura/regex text extraction. Optionally delegates to a `WebFetchProvider` (e.g., Jina, Crawl4AI).
- **Search**: delegates to a `WebSearchProvider` (DuckDuckGo, Tavily, SearXNG, Brave). Returns empty results if no search provider is configured.

---

## Tool Budget -- Smart Tool Management

When multiple capabilities and MCP skills are active, the total number of tools can reach 40+.
This consumes 5,000-7,000 tokens on schema alone and can confuse the model.

`ToolSelector` picks tools by priority within a configurable budget:

```python
from swarmline.policy.tool_selector import ToolBudgetConfig, ToolGroup

config = ToolBudgetConfig(
    max_tools=20,
    group_priority=[
        ToolGroup.ALWAYS,     # thinking, todo (always included)
        ToolGroup.MCP,        # business tools
        ToolGroup.MEMORY,     # memory bank
        ToolGroup.PLANNING,   # planning
        ToolGroup.SANDBOX,    # file operations
        ToolGroup.WEB,        # web search
    ],
    group_limits={
        ToolGroup.MCP: 12,
        ToolGroup.SANDBOX: 3,
    },
)
```

Priority order: ALWAYS > MCP > MEMORY > PLANNING > SANDBOX > WEB.
When the budget is exhausted, lower-priority groups are trimmed.

`tool_budget_config` is applied during wiring:

- At `SwarmlineStack.create()` for capability tools;
- In `SessionFactory` for the final `active_tools` set before runtime execution.
