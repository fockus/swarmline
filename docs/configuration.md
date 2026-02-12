# Configuration

## CognitiaStack — единая точка сборки

`CognitiaStack.create()` собирает все компоненты библиотеки в один объект.
Каждая capability — отдельный toggle.

```python
from cognitia.bootstrap.stack import CognitiaStack

stack = CognitiaStack.create(
    # === Обязательные ===
    prompts_dir=Path("prompts"),
    skills_dir=Path("skills"),
    project_root=Path("."),

    # === Runtime ===
    runtime_config=RuntimeConfig(runtime_name="thin", model="claude-sonnet-4-20250514"),

    # === Capability toggles ===
    sandbox_provider=sandbox,             # SandboxProvider | None
    web_provider=web,                     # WebProvider | None
    todo_provider=todo,                   # TodoProvider | None
    memory_bank_provider=memory,          # MemoryBankProvider | None
    plan_manager=plan_mgr,               # PlanManager | None
    thinking_enabled=True,               # bool

    # === Security ===
    allowed_system_tools={"bash", "read", "write"},  # whitelist
    tool_budget_config=ToolBudgetConfig(max_tools=25),

    # === Routing ===
    escalate_roles={"strategy_planner"},
    local_tool_resolver=my_resolver,
)
```

### Что получаем

```python
stack.capability_specs      # dict[str, ToolSpec] — все capability tools
stack.capability_executors  # dict[str, Callable] — executors для tools
stack.tool_policy           # DefaultToolPolicy с whitelist
stack.context_builder       # DefaultContextBuilder с P_MEMORY support
stack.runtime_factory       # RuntimeFactory
stack.skill_registry        # SkillRegistry (MCP skills)
stack.role_router           # KeywordRoleRouter
```

---

## RuntimeConfig

```python
from cognitia.runtime.types import RuntimeConfig

config = RuntimeConfig(
    runtime_name="thin",                        # claude_sdk | thin | deepagents
    model="claude-sonnet-4-20250514",           # или alias: "sonnet", "opus", "haiku"
    base_url=None,                              # для совместимых API (Together, Groq)
    max_iterations=25,                          # лимит ReAct iterations
    max_tool_calls=50,                          # лимит tool calls per turn
)
```

### Модели и alias'ы

| Alias | Модель | Провайдер |
|-------|--------|-----------|
| `sonnet` | claude-sonnet-4-20250514 | Anthropic |
| `opus` | claude-opus-4-20250514 | Anthropic |
| `haiku` | claude-haiku-3-20250307 | Anthropic |
| `gpt-4o` | gpt-4o | OpenAI |
| `gemini` | gemini-2.5-pro | Google |

---

## ToolPolicy — контроль доступа

```python
from cognitia.policy import DefaultToolPolicy

policy = DefaultToolPolicy(
    allowed_system_tools={"bash", "read", "write"},  # whitelist
    extra_denied={"dangerous_tool"},                  # доп. запрет
)
```

### Логика проверки

1. Tool в `ALWAYS_DENIED` и **не** в whitelist → **deny**
2. Tool в `allowed_local_tools` → **allow**
3. Tool начинается с `mcp__` и MCP-сервер активен → **allow**
4. Иначе → **deny**

### ALWAYS_DENIED_TOOLS

```
Bash/bash, Read/read, Write/write, Edit/edit, MultiEdit/multi_edit,
Glob/glob, Grep/grep, LS/ls, TodoRead/todo_read, TodoWrite/todo_write,
WebFetch/web_fetch, WebSearch/web_search
```

Оба варианта именования (PascalCase SDK + snake_case builtin) покрыты.

---

## ToolBudgetConfig — бюджет инструментов

```python
from cognitia.policy.tool_selector import ToolBudgetConfig, ToolGroup

config = ToolBudgetConfig(
    max_tools=25,                       # общий лимит
    group_priority=[                    # порядок заполнения
        ToolGroup.ALWAYS,               # thinking, todo
        ToolGroup.MCP,                  # бизнес-инструменты
        ToolGroup.MEMORY,               # memory bank
        ToolGroup.PLANNING,             # plan_create/status/execute
        ToolGroup.SANDBOX,              # bash, read, write, ...
        ToolGroup.WEB,                  # web_fetch, web_search
    ],
    group_limits={                      # per-group лимиты
        ToolGroup.MCP: 12,
        ToolGroup.SANDBOX: 4,
    },
)
```

---

## MemoryBankConfig

```python
from cognitia.memory_bank.types import MemoryBankConfig

config = MemoryBankConfig(
    enabled=True,
    backend="filesystem",               # filesystem | database
    root_path=Path("/data/memory"),
    max_file_size_bytes=100 * 1024,     # 100 KB per file
    max_total_size_bytes=1024 * 1024,   # 1 MB total
    max_entries=200,                     # макс. количество файлов
    max_depth=2,                        # root/subfolder/file
    auto_load_on_turn=True,             # MEMORY.md → system prompt
    auto_load_max_lines=200,
    default_folders=["plans", "reports", "notes"],
    prompt_path=None,                   # None = встроенный default
)
```

---

## TodoConfig

```python
from cognitia.todo.types import TodoConfig

config = TodoConfig(
    enabled=True,
    backend="memory",                   # memory | filesystem | database
    root_path=Path("/data/todos"),      # для filesystem
    max_todos=100,
    auto_cleanup_completed=False,
)
```

---

## SandboxConfig

```python
from cognitia.tools.types import SandboxConfig

config = SandboxConfig(
    root_path="/data/sandbox",
    user_id="user-42",
    topic_id="project-7",
    max_file_size_bytes=10 * 1024 * 1024,
    timeout_seconds=30,
    allowed_extensions=frozenset({".py", ".txt", ".md", ".json"}),
    denied_commands=frozenset({"rm", "sudo", "kill", "chmod"}),
)
```

---

## Environment Variables

| Variable | Описание | Default |
|----------|----------|---------|
| `ANTHROPIC_API_KEY` | API ключ Anthropic | — |
| `ANTHROPIC_MODEL` | Модель (alias или полное имя) | `claude-sonnet-4-20250514` |
| `COGNITIA_RUNTIME` | Runtime (`claude_sdk`, `thin`, `deepagents`) | `claude_sdk` |
| `E2B_API_KEY` | API ключ E2B (для cloud sandbox) | — |
| `DATABASE_URL` | Connection string PostgreSQL | — |
