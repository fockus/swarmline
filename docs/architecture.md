# Architecture

## Принципы

Cognitia строится на Clean Architecture и SOLID:

- **Protocol-driven**: все контракты — `typing.Protocol` с `@runtime_checkable`. Не абстрактные классы.
- **ISP**: каждый Protocol содержит не более 5 методов.
- **DIP**: потребители зависят от Protocol, не от конкретных реализаций.
- **Immutable types**: все domain-объекты — frozen dataclass. Мутация через создание нового экземпляра.
- **No domain leak**: библиотека не знает о бизнес-приложении. Grep `freedom_agent` по src — 0 совпадений.

## Слои

```
┌─────────────────────────────────────────────────┐
│  Бизнес-приложение (freedom_agent, your_app)    │
│  Знает о cognitia. Реализует конкретных бизнес- │
│  провайдеров, промпты, роли.                    │
├─────────────────────────────────────────────────┤
│  cognitia (библиотека)                          │
│  ┌────────────┐ ┌──────────┐ ┌───────────────┐  │
│  │  bootstrap  │ │ context  │ │   runtime     │  │
│  │  (stack)    │ │ (builder)│ │ (claude/thin/ │  │
│  │             │ │          │ │  deepagents)  │  │
│  ├────────────┤ ├──────────┤ ├───────────────┤  │
│  │  policy    │ │ session  │ │   tools       │  │
│  │ (deny/allow│ │ (manager,│ │ (sandbox,     │  │
│  │  selector) │ │  rehydr.)│ │  builtin,web) │  │
│  ├────────────┤ ├──────────┤ ├───────────────┤  │
│  │  memory    │ │  skills  │ │   todo        │  │
│  │ (inmemory, │ │ (registry│ │ (inmemory,    │  │
│  │  postgres) │ │  loader) │ │  fs, db)      │  │
│  ├────────────┤ ├──────────┤ ├───────────────┤  │
│  │ memory_bank│ │  routing │ │ orchestration │  │
│  │ (fs, db)   │ │ (keyword)│ │ (plan, sub,   │  │
│  │            │ │          │ │  team, msg)   │  │
│  └────────────┘ └──────────┘ └───────────────┘  │
├─────────────────────────────────────────────────┤
│  Внешние зависимости (LLM API, DB, MCP)         │
└─────────────────────────────────────────────────┘
```

## Пакеты

| Пакет | Назначение | Зависимости |
|-------|-----------|-------------|
| `bootstrap` | Facade: `CognitiaStack.create()`, capabilities wiring | core |
| `context` | Сборка system prompt с token budget | core |
| `session` | SessionManager, Rehydrator (управление историей) | memory |
| `memory` | Хранилище сообщений, фактов, целей (InMemory, Postgres) | core |
| `memory_bank` | Долгосрочная файловая память (FS, DB) | core |
| `todo` | Чек-листы / task tracking (InMemory, FS, DB) | core |
| `tools` | Sandbox-изоляция, builtin tools, web, thinking | core |
| `orchestration` | Planning, subagents, team mode, message bus | core |
| `policy` | ToolPolicy (deny/allow), ToolSelector (budget) | core |
| `routing` | KeywordRoleRouter (автопереключение ролей) | core |
| `skills` | SkillRegistry, YamlSkillLoader (MCP skills) | core |
| `runtime` | AgentRuntime (Claude SDK, ThinRuntime, DeepAgents) | extras |
| `resilience` | Circuit breaker для внешних вызовов | core |
| `observability` | Structured JSON logging | structlog |
| `hooks` | Lifecycle hooks (pre/post turn) | core |
| `commands` | CommandRegistry (slash-команды) | core |

## Protocol Map

```
MessageStore ─────┐
FactStore ────────┤
GoalStore ────────┤── memory providers (InMemory, Postgres, SQLite)
SummaryStore ─────┤
SessionStateStore ┘

MemoryBankProvider ── memory_bank providers (FS, DB)

TodoProvider ──────── todo providers (InMemory, FS, DB)

SandboxProvider ───── sandbox providers (Local, E2B, Docker)

WebProvider ────────── web providers (Httpx)

AgentRuntime ──────── runtime (ClaudeCode, Thin, DeepAgents)

PlanStore ─────────── plan stores (InMemory)
PlannerMode ───────── planners (Thin, DeepAgents)

SubagentOrchestrator ── subagent orchestrators (Thin, DeepAgents, Claude)
TeamOrchestrator ────── team orchestrators (DeepAgents, Claude)
```
