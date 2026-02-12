# Capabilities

Cognitia предоставляет 6 независимых capability. Каждая включается отдельным toggle — подключай только нужное.

## Статус готовности

| Capability | Статус | Комментарий |
|-----------|--------|-------------|
| Sandbox | ready | Local/Docker/E2B c timeout, denied commands, path isolation |
| Web | partial | HTTPX provider реализует базовый fetch/search MVP |
| Todo | ready | InMemory/Filesystem/Database (Postgres + SQLite) |
| Memory Bank | ready | Filesystem + Database backend, auto-load `MEMORY.md` |
| Planning | staged | Workflow стабилен, persistence пока только InMemory PlanStore |
| Thinking | ready | standalone tool без внешних зависимостей |

## Обзор

| Capability | Toggle | Tools | Extras |
|-----------|--------|-------|--------|
| **Sandbox** | `sandbox_provider=` | bash, read, write, edit, multi_edit, ls, glob, grep | — |
| **Web** | `web_provider=` | web_fetch, web_search | `cognitia[web]` |
| **Todo** | `todo_provider=` | todo_read, todo_write | — |
| **Memory Bank** | `memory_bank_provider=` | memory_read, memory_write, memory_append, memory_list, memory_delete | — |
| **Planning** | `plan_manager=` | plan_create, plan_status, plan_execute | — |
| **Thinking** | `thinking_enabled=True` | thinking | — |

---

## Sandbox — изоляция файлов и кода

Агент читает/пишет файлы и выполняет команды только внутри изолированного workspace.
Каждый пользователь + топик = отдельный namespace.

### Провайдеры

| Провайдер | Когда использовать | Extras |
|-----------|-------------------|--------|
| `LocalSandboxProvider` | Разработка, тесты | — |
| `E2BSandboxProvider` | Продакшен (облако) | `cognitia[e2b]` |
| `DockerSandboxProvider` | Продакшен (self-hosted) | `cognitia[docker]` |

### Использование

```python
from cognitia.tools.sandbox_local import LocalSandboxProvider
from cognitia.tools.types import SandboxConfig

sandbox = LocalSandboxProvider(SandboxConfig(
    root_path="/data/sandbox",
    user_id="user-42",
    topic_id="project-7",
    max_file_size_bytes=10 * 1024 * 1024,  # 10 MB
    timeout_seconds=30,
    denied_commands=frozenset({"rm", "sudo", "kill"}),
))
```

### Безопасность

- Path traversal (`../`) блокируется через `Path.is_relative_to()`
- Абсолютные пути запрещены
- Denied commands: настраиваемый список запрещённых команд
- Timeout: команда убивается через `timeout_seconds`
- Size limit: файлы больше `max_file_size_bytes` отклоняются

---

## Todo — чек-листы и task tracking

Агент ведёт структурированный список задач. Работает **без sandbox** — отдельная capability.

### Провайдеры

| Провайдер | Хранение | Когда |
|-----------|----------|-------|
| `InMemoryTodoProvider` | Память процесса | Dev, session-scoped |
| `FilesystemTodoProvider` | JSON-файл | Простые проекты |
| `DatabaseTodoProvider` | Postgres/SQLite | Продакшен |

### Использование

```python
from cognitia.todo.inmemory_provider import InMemoryTodoProvider

todo = InMemoryTodoProvider(user_id="user-1", topic_id="task-1", max_todos=100)
```

### API для агента

- `todo_read(status_filter?)` — прочитать задачи (опционально по статусу)
- `todo_write(todos)` — записать задачи (bulk replace)

Статусы: `pending`, `in_progress`, `completed`, `cancelled`.

---

## Memory Bank — долгосрочная память

Агент сохраняет знания между сессиями: решения, предпочтения, уроки.
Структура — файловая с подпапками (2 уровня).

### Структура

```
{root}/{user_id}/{topic_id}/memory/
├── MEMORY.md                    # Индекс (загружается в prompt)
├── progress.md                  # Прогресс
├── lessons.md                   # Уроки
├── plans/                       # Подпапка
│   └── 2026-02-12_feature.md
├── reports/
│   └── 2026-02-12_session.md
└── notes/
    └── 2026-02-12_15-30_topic.md
```

### Провайдеры

| Провайдер | Backend | Extras |
|-----------|---------|--------|
| `FilesystemMemoryBankProvider` | Файлы | — |
| `DatabaseMemoryBankProvider` | Postgres/SQLite | `cognitia[postgres]` или `cognitia[sqlite]` |

### Конфигурация

```python
from cognitia.memory_bank.types import MemoryBankConfig

config = MemoryBankConfig(
    enabled=True,
    backend="filesystem",
    root_path=Path("/data/memory"),
    max_file_size_bytes=100 * 1024,      # 100 KB per file
    max_entries=200,                      # макс. файлов
    max_depth=2,                          # root/subfolder/file
    auto_load_on_turn=True,              # загружать MEMORY.md в prompt
    auto_load_max_lines=200,
    default_folders=["plans", "reports", "notes"],
)
```

### Auto-load

Если `auto_load_on_turn=True`, содержимое `MEMORY.md` (первые N строк) автоматически инжектируется в system prompt через `ContextBuilder` — агент всегда «помнит» ключевой контекст.

### DDL для Database backend

Библиотека экспортирует DDL, приложение использует в своих миграциях:

```python
from cognitia.memory_bank.schema import get_memory_bank_ddl

# Для Postgres
stmts = get_memory_bank_ddl(dialect="postgres")

# Для SQLite
stmts = get_memory_bank_ddl(dialect="sqlite")
```

---

## Planning — пошаговое выполнение задач

Агент создаёт план для сложных задач, выполняет по шагам, отслеживает прогресс.

### Workflow

1. Агент решает что задача сложная → вызывает `plan_create(goal="...")`
2. LLM генерирует план (список шагов)
3. План одобряется (автоматически или пользователем)
4. Шаги выполняются последовательно, каждый с доступом к tools
5. Если шаг провалился — остановка или replan

### Программное управление

```python
from cognitia.orchestration.manager import PlanManager
from cognitia.orchestration.thin_planner import ThinPlannerMode
from cognitia.orchestration.plan_store import InMemoryPlanStore

store = InMemoryPlanStore()
planner = ThinPlannerMode(llm=llm_client, plan_store=store)
manager = PlanManager(planner=planner, plan_store=store)

# Из бизнес-кода
plan = await manager.create_plan("Анализ портфеля", user_id="u1", topic_id="t1")
approved = await manager.approve_plan(plan.id, by="system")

async for step in manager.execute_plan(plan.id):
    print(f"[{step.status}] {step.description}: {step.result}")
```

---

## Thinking — структурированное рассуждение

Chain-of-Thought + ReAct: агент записывает ход мыслей и следующие шаги перед действием.

```
Агент вызывает: thinking(thought="Нужно найти вклады с доходностью >15%", 
                         next_steps=["Запросить список вкладов", "Отфильтровать по ставке"])
```

Thinking — standalone tool без зависимостей. Рекомендуется всегда включать.

---

## Web — доступ в интернет

```python
from cognitia.tools.web_httpx import HttpxWebProvider

web = HttpxWebProvider(timeout=30)
# Агент получает: web_fetch(url), web_search(query)
```

---

## Tool Budget — умное управление инструментами

Когда подключено много capability + MCP skills, общее количество инструментов может достигать 40+.
Это занимает 5000-7000 токенов и путает модель.

`ToolSelector` отбирает инструменты по приоритету в рамках бюджета:

```python
from cognitia.policy.tool_selector import ToolBudgetConfig, ToolGroup

config = ToolBudgetConfig(
    max_tools=20,
    group_priority=[
        ToolGroup.ALWAYS,     # thinking, todo (всегда)
        ToolGroup.MCP,        # бизнес-инструменты
        ToolGroup.MEMORY,     # memory bank
        ToolGroup.PLANNING,   # планирование
        ToolGroup.SANDBOX,    # файловые операции
        ToolGroup.WEB,        # веб-поиск
    ],
    group_limits={
        ToolGroup.MCP: 12,
        ToolGroup.SANDBOX: 3,
    },
)
```

Приоритет: ALWAYS → MCP → MEMORY → PLANNING → SANDBOX → WEB.
Если бюджет исчерпан — низкоприоритетные группы обрезаются.

`tool_budget_config` применяется в wiring:
- на этапе `CognitiaStack.create()` для capability-инструментов;
- в `SessionFactory` для итогового `active_tools` перед запуском runtime.
