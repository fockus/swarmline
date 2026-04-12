# Graph Agents & Knowledge Bank — Architecture Report

**Date:** 2026-03-29
**Version:** v1.1.0 (post-audit)
**Status:** Production-ready, fully tested (3728 tests)

---

## Part 1: Graph Agents — Hierarchical Multi-Agent System

### Обзор

Система Graph Agents позволяет строить иерархические организации агентов (org chart), где каждый агент имеет роль, инструменты, навыки, MCP-серверы и governance-ограничения. Агенты выполняют задачи параллельно, делегируют подзадачи, эскалируют проблемы вверх по цепочке команд.

### Как создать агента в графе

При создании агента задаётся 6 аспектов:

```python
from swarmline.multi_agent.graph_builder import GraphBuilder
from swarmline.multi_agent.graph_types import AgentCapabilities

graph = (
    GraphBuilder()
    .add_root(
        id="ceo",
        name="CEO",
        role="executive",
        # 1. Роль — через system_prompt
        system_prompt="You are the CEO. Decompose goals into strategic phases.",
        # 2. Полномочия — через allowed_tools (наследуются потомками)
        allowed_tools=("web_search", "create_report"),
        # 3. Компетенции — через skills (в system prompt)
        skills=("strategy", "leadership"),
        # 4. MCP серверы — внешние инструменты (наследуются)
        mcp_servers=("filesystem", "github"),
        # 5. Governance — что агент может делать
        capabilities=AgentCapabilities(
            can_hire=True,         # может создавать подчинённых
            can_delegate=True,     # может делегировать задачи
            max_children=5,        # макс 5 прямых подчинённых
            can_use_subagents=True,  # может запускать runtime subagents
            can_use_team_mode=False, # team mode отключён
        ),
        # 6. Бюджет и runtime
        budget_limit_usd=10.0,
        runtime_config={"model": "opus"},
    )
    .add_child(
        id="eng1",
        parent_id="ceo",
        name="Engineer 1",
        role="engineer",
        system_prompt="You are a backend engineer. Write clean code.",
        allowed_tools=("code_exec", "unit_test"),
        skills=("python", "sql", "api_design"),
        capabilities=AgentCapabilities(can_hire=False, can_delegate=True),
    )
)
```

### Наследование

Tools, skills и MCP servers **наследуются от ancestors**:
- Engineer 1 видит свои tools (`code_exec`, `unit_test`) + родительские (`web_search`, `create_report`)
- Аналогично для skills и mcp_servers
- Дедупликация: child's own tools идут первыми, parent's добавляются если не дублируют

### System Prompt (автогенерация)

`GraphContextBuilder.render_system_prompt()` собирает структурированный промпт:

```
## Your Identity
You are Engineer 1, role: engineer.

## Chain of Command
CEO > Engineer 1

## Your Team
Peers: Engineer 2, Designer 1
Reports to you: (none)

## Available Tools
code_exec, unit_test, web_search, create_report

## Skills
python, sql, api_design, strategy, leadership

## MCP Servers
filesystem, github

## Your Permissions
- Can hire subordinates: No
- Can delegate tasks: Yes
- Can use subagents: No

## Your Instructions
You are a backend engineer. Write clean code.
```

### Runner — как агент выполняется

Orchestrator поддерживает два типа runner:

**Legacy (backward-compat):**
```python
async def my_runner(agent_id: str, task_id: str, goal: str, system_prompt: str) -> str:
    # Получает 4 строки
    return "Result text"
```

**Context-Aware (новый):**
```python
from swarmline.multi_agent.graph_execution_context import AgentExecutionContext

async def my_runner(ctx: AgentExecutionContext) -> str:
    # Получает полный контекст
    print(ctx.agent_id)       # "eng1"
    print(ctx.tools)          # ("code_exec", "unit_test", "web_search", "create_report")
    print(ctx.skills)         # ("python", "sql", "api_design", "strategy", "leadership")
    print(ctx.mcp_servers)    # ("filesystem", "github")
    print(ctx.runtime_config) # {"model": "opus"}
    print(ctx.budget_limit_usd)  # 10.0
    return "Result text"
```

Тип runner определяется автоматически через `inspect.signature()`.

### Задачи и цели (иерархия)

`GraphTaskItem` поддерживает произвольную вложенность:

```
orchestrator.start("Build web app")           # root task (цель)
  └── delegate("Design API", agent="eng1")    # подзадача
        └── delegate("Write tests", agent="tester")  # под-подзадача
              └── ...  (N уровней)
```

- `parent_task_id` — ссылка на родительскую задачу
- `goal_id` — ссылка на root goal
- `dependencies` — DAG-зависимости между задачами
- `_propagate_completion()` — автоматическое завершение parent когда все children DONE
- `get_goal_ancestry()` — цепочка от root goal до текущей задачи

Агенты могут создавать свои подзадачи через `graph_delegate_task` tool.

### Governance — ограничения и разрешения

**Per-agent (`AgentCapabilities`):**

| Поле | Default | Описание |
|------|---------|----------|
| `can_hire` | `False` | Может создавать подчинённых в графе |
| `can_delegate` | `True` | Может делегировать задачи |
| `max_children` | `None` (unlimited) | Макс прямых подчинённых |
| `can_use_subagents` | `False` | Может запускать runtime subagents (вне графа) |
| `allowed_subagent_ids` | `()` (all) | Конкретные subagent IDs |
| `can_use_team_mode` | `False` | Claude Code team mode |

**Global (`GraphGovernanceConfig`):**

| Поле | Default | Описание |
|------|---------|----------|
| `max_agents` | `50` | Макс агентов в графе |
| `max_depth` | `5` | Макс глубина иерархии |
| `allow_dynamic_hiring` | `True` | Глобальный kill-switch для найма |
| `allow_dynamic_delegation` | `True` | Глобальный kill-switch для делегирования |
| `default_capabilities` | `AgentCapabilities()` | Defaults для новых агентов |

**Enforcement:** `hire_agent` tool проверяет: can_hire → max_children → max_depth → max_agents. Governance = hard limits, approval_gate = soft policy.

### Graph Tools (runtime)

Агенты могут использовать 3 tool для управления графом:
- `graph_hire_agent` — создать подчинённого (с governance checks)
- `graph_delegate_task` — делегировать задачу
- `graph_escalate` — эскалировать проблему вверх по chain of command

### Storage backends

| Backend | Модуль | Использование |
|---------|--------|---------------|
| InMemory | `graph_store.py` | Dev/тесты |
| SQLite | `graph_store_sqlite.py` | Lightweight persistence |
| PostgreSQL | `graph_store_postgres.py` | Production |

---

## Part 2: Knowledge Bank — Universal Project Memory

### Обзор

Knowledge Bank — domain-agnostic система структурированного хранения знаний. Вдохновлена /mb skill, но без привязки к code development. Работает с любым доменом: research, business, education, engineering.

### Типы записей

| Kind | Назначение | Пример |
|------|-----------|--------|
| `status` | Текущая фаза, метрики, roadmap | STATUS.md |
| `plan` | Текущий фокус и приоритеты | plan.md |
| `checklist` | Трекинг задач (✅/⬜) | checklist.md |
| `research` | Гипотезы, findings, эксперименты | RESEARCH.md |
| `backlog` | Идеи, ADR, отложенное | BACKLOG.md |
| `progress` | Append-only лог выполнения | progress.md |
| `lesson` | Learned patterns/antipatterns | lessons.md |
| `note` | Короткие knowledge notes (5-15 строк) | notes/*.md |
| `report` | Полные аналитические отчёты | reports/*.md |
| `experiment` | Structured experiments | experiments/*.md |

### YAML Frontmatter

Каждый документ может иметь metadata:

```yaml
---
kind: note
tags: [architecture, patterns]
importance: high
created: 2026-03-29
updated: 2026-03-29
related: [plans/feature-x.md]
---

Content body here...
```

`parse_frontmatter(text) → (DocumentMeta, body)` и `render_frontmatter(meta, body) → text`.

### Protocols (ISP, ≤5 methods)

```python
KnowledgeStore:      save, load, delete, list_entries, exists
KnowledgeSearcher:   search, search_by_tags, rebuild_index, get_index
ProgressLog:         append, get_recent, get_all
ChecklistManager:    add_item, toggle_item, get_items, clear_done
VerificationStrategy: verify, suggest_criteria
```

### Multi-Backend Architecture

```
KnowledgeStore  ←  wraps  →  MemoryBankProvider (5-method Protocol)
                                    ↑
                    ┌───────────────┼──────────────────┐
                    │               │                  │
          FilesystemMBP     DatabaseMBP        CustomProvider
          (local path)      (SQLite/Postgres)   (S3, GCS, etc.)
```

**Filesystem** — файлы на диске (relative/absolute path):
```python
from swarmline.memory_bank.fs_provider import FilesystemMemoryBankProvider
from swarmline.memory_bank.types import MemoryBankConfig

config = MemoryBankConfig(root_path="/data/knowledge")
provider = FilesystemMemoryBankProvider(config, user_id="u1", topic_id="project-x")
```

**Database** — SQLite/Postgres через SQLAlchemy:
```python
from swarmline.memory_bank.db_provider import DatabaseMemoryBankProvider

provider = DatabaseMemoryBankProvider(session_factory, user_id="u1", topic_id="project-x")
```

**Custom** — любой backend реализующий `MemoryBankProvider` Protocol (5 methods).

### Использование

```python
from swarmline.memory_bank.knowledge_store import DefaultKnowledgeStore
from swarmline.memory_bank.knowledge_search import DefaultKnowledgeSearcher
from swarmline.memory_bank.knowledge_types import DocumentMeta, KnowledgeEntry

# Создать store поверх любого provider
store = DefaultKnowledgeStore(provider)
searcher = DefaultKnowledgeSearcher(provider)

# Сохранить запись
entry = KnowledgeEntry(
    path="notes/2026-03-29_architecture.md",
    meta=DocumentMeta(kind="note", tags=("architecture", "patterns"), importance="high"),
    content="Key insight: use composition over inheritance for backends.",
)
await store.save(entry)  # auto-updates index.json

# Поиск
results = await searcher.search("architecture patterns")
results = await searcher.search_by_tags(["architecture"])

# Checklist
from swarmline.memory_bank.knowledge_checklist import DefaultChecklistManager
from swarmline.memory_bank.knowledge_types import ChecklistItem

checklist = DefaultChecklistManager(provider)
await checklist.add_item(ChecklistItem(text="Implement API"))
await checklist.toggle_item("Implement")  # → done=True

# Progress log
from swarmline.memory_bank.knowledge_progress import DefaultProgressLog

log = DefaultProgressLog(provider)
await log.append("Completed architecture review")
recent = await log.get_recent(5)
```

### Agent Tools

3 инструмента для агентов:
```python
from swarmline.memory_bank.tools import create_knowledge_tools

specs, executors = create_knowledge_tools(store, searcher)
# knowledge_search — поиск по тексту
# knowledge_save_note — сохранить заметку с тегами
# knowledge_get_context — snapshot состояния банка
```

### Consolidation (Episodes → Knowledge)

```python
from swarmline.memory_bank.knowledge_consolidation import KnowledgeConsolidator

consolidator = KnowledgeConsolidator()
entries = consolidator.consolidate(episodes, min_episodes=3)
# Группирует episodes по тегам → создаёт knowledge notes
```

### Index Protocol

`index.json` автоматически обновляется при `save()`/`delete()`:

```json
{
  "version": 1,
  "updated": "2026-03-29T15:30:00",
  "entries": [
    {
      "path": "notes/2026-03-29_architecture.md",
      "kind": "note",
      "tags": ["architecture", "patterns"],
      "importance": "high",
      "summary": "Key insight: use composition..."
    }
  ]
}
```

---

## Файловая структура

### Graph Agents
```
src/swarmline/multi_agent/
├── graph_types.py              # AgentNode, AgentCapabilities, GraphEdge
├── graph_execution_context.py  # AgentExecutionContext (tools/skills/MCP)
├── graph_governance.py         # GraphGovernanceConfig, check_hire/delegate
├── graph_context.py            # GraphContextBuilder (system prompt)
├── graph_orchestrator.py       # DefaultGraphOrchestrator (dual-dispatch runner)
├── graph_builder.py            # GraphBuilder DSL
├── graph_tools.py              # hire_agent, delegate_task, escalate
├── graph_task_board*.py        # Hierarchical task management (InMemory/SQLite/Postgres)
├── graph_store*.py             # Agent graph storage (InMemory/SQLite/Postgres)
└── graph_communication*.py     # Inter-agent messaging (InMemory/SQLite/Postgres/Redis/NATS)
```

### Knowledge Bank
```
src/swarmline/memory_bank/
├── knowledge_types.py          # 9 domain types + DocumentKind
├── knowledge_protocols.py      # 5 ISP protocols (Store/Search/Progress/Checklist/Verify)
├── knowledge_inmemory.py       # InMemory implementations
├── knowledge_store.py          # DefaultKnowledgeStore (wraps MemoryBankProvider)
├── knowledge_search.py         # DefaultKnowledgeSearcher (word-overlap + tags)
├── knowledge_checklist.py      # DefaultChecklistManager (markdown parse/serialize)
├── knowledge_progress.py       # DefaultProgressLog (append-only)
├── knowledge_consolidation.py  # Episodes → Knowledge notes
├── frontmatter.py              # YAML frontmatter parser/serializer
├── tools.py                    # create_knowledge_tools() — 3 agent tools
├── protocols.py                # MemoryBankProvider (5-method Protocol)
├── fs_provider.py              # Filesystem backend
├── db_provider.py              # Database backend (SQLite/Postgres)
└── types.py                    # MemoryBankConfig, MemoryEntry
```

---

## Тестовое покрытие

| Модуль | Тесты | Покрытие |
|--------|-------|----------|
| Graph types + execution context | 12 | types, frozen, backward compat |
| Graph context builder | 27 | skills/MCP inheritance, prompt rendering |
| Graph orchestrator | 53+ | start, delegate, retry, dual dispatch |
| Graph governance | 28 | capabilities, limits, enforcement |
| Graph builder | 13 | MCP, capabilities, from_dict |
| Knowledge types | 25 | all 9 types, frozen |
| Knowledge frontmatter | 16 | parse, render, roundtrip |
| Knowledge protocols | 33 | protocol compliance, InMemory |
| Knowledge storage | 58 | filesystem + mock backends |
| Knowledge consolidation | 9 | episodes → notes |
| Knowledge tools | 8 | search, save_note, get_context |
| **Total new** | **~282** | |
