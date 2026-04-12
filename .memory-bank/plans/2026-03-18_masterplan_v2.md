# Master Plan v2.0 — Swarmline Roadmap

> Создан: 2026-03-18 (обновление v1 от 2026-03-17)
> Базовая версия: 0.5.0 (multi-provider ThinRuntime + upstream middleware)
> 22 идеи + OpenAI Agents SDK интеграция
> Источники: Paperclip, OpenClaw, NanoClaw, claudecron, OpenAI Agents SDK

---

## Обзор

```
Phase 6: DX Foundation           ← structured output, tool decorator, adapter registry
Phase 7: Production Safety       ← budget, guardrails, input filters, caller policy, credential isolation
Phase 8: Persistence             ← session backends, tracing, memory scopes
Phase 9: Multi-Agent & Tasks     ← task backlog, agent hierarchy, delegation, scheduler, agent-as-tool
Phase 10: Platform               ← CLI runtime, MCP, OAuth, RTK token optimization
Phase 11: OpenAI Agents SDK      ← 4-й runtime, bridges
```

## Новые идеи (v2)

| ID | Название | Источник | Фаза |
|----|----------|----------|------|
| IDEA-017 | RTK token optimization | rtk-ai.app | 10E |
| IDEA-018 | Task Backlog System | Paperclip issues | 9B |
| IDEA-019 | Agent Hierarchy & Org Chart | Paperclip reportsTo | 9C |
| IDEA-020 | Credential Proxy | NanoClaw | 7D |
| IDEA-021 | Memory Scopes (global/agent/shared) | NanoClaw | 8C |
| IDEA-022 | CallerPolicy (identity access control) | NanoClaw sender allowlist | 7B+ |

## Граф зависимостей

```
IDEA-016 (tool decorator) ──────────────────────────────────────────┐
IDEA-011 (structured output) ──→ IDEA-008 (guardrails) ─────────────┤
IDEA-002 (adapter registry) ──→ IDEA-003 (CLI runtime) ─────────────┤
IDEA-004 (budget) ────────────→ IDEA-009 (agent-as-tool) ───────────┤
IDEA-013 (input filter) ────────────────────────────────────────────┤
IDEA-010 (session backends) ──→ IDEA-018 (task backlog) ────────────┤
IDEA-018 (task backlog) ──────→ IDEA-019 (agent hierarchy) ─────────┤
IDEA-019 (agent hierarchy) ───→ IDEA-006 (multi-agent delegation) ──┤
IDEA-009 (agent-as-tool) ────→ IDEA-006 (multi-agent delegation) ──┤
IDEA-006 (multi-agent) ──────→ IDEA-007 (scheduler) ───────────────┘
IDEA-015 (tracing) ──────────────────────────────────────────────────
IDEA-014 (MCP multi-transport) → IDEA-012 (MCP approval)
IDEA-001 (OAuth), IDEA-017 (RTK), IDEA-020 (cred proxy) — независимы
```

---

## Phase 6: DX Foundation

**Цель**: Удобство разработки — structured output, декоратор для tools, pluggable runtime.

### 6A: Structured Output via Pydantic (IDEA-011)

**Приоритет**: High | **Сложность**: Low | **~2-3 дня**

**Scope**:
1. `RuntimeConfig.output_type: type[BaseModel] | None`
2. Auto-генерация JSON Schema из Pydantic → передача в LLM
3. Post-validation через `model_validate_json()`
4. Retry при невалидном ответе (до `max_model_retries`, default 3)
5. `RuntimeEvent.final(structured_output=parsed_model)`

**DoD**:
- [ ] Contract: `OutputType` Protocol + JSON Schema generation
- [ ] Unit: validation pass/fail, retry logic, schema extraction — 10+ тестов
- [ ] Integration: Anthropic + OpenAI + Google structured output — 6+ тестов
- [ ] Все 3 runtime'а (thin, deepagents, claude_sdk) поддерживают output_type
- [ ] Coverage 95%+ для нового кода

### 6B: Tool Schema Auto-generation (IDEA-016)

**Приоритет**: Medium | **Сложность**: Low | **~1-2 дня**

**Scope**:
1. `@tool` декоратор: `def my_tool(query: str, limit: int = 10) -> str` → auto `ToolSpec`
2. Type hints → JSON Schema (str→string, int→integer, list→array, Optional→nullable)
3. Docstring (Google/NumPy) → description для параметров
4. `inspect` + `typing.get_type_hints` (без griffe)
5. Совместимость с существующим `ToolSpec` — `@tool` = сахар

**DoD**:
- [ ] Contract: `@tool` decorator → `ToolSpec`
- [ ] Unit: type mapping, docstring parsing, edge cases (Optional, Union, defaults) — 15+ тестов
- [ ] Integration: tool зарегистрирован и вызван через runtime — 3+ тестов

### 6C: Extensible Adapter Registry (IDEA-002)

**Приоритет**: High | **Сложность**: Low | **~2-3 дня**

**Scope**:
1. `RuntimeFactory.register(name, factory_fn)` / `unregister(name)`
2. Entry points (`pyproject.toml [project.entry-points."swarmline.runtimes"]`) для auto-discovery
3. Валидация: factory_fn возвращает объект, реализующий `AgentRuntime` Protocol
4. Встроенные runtime'ы регистрируются через тот же механизм (dog-fooding)
5. `RuntimeFactory.list_available()` — все зарегистрированные runtime'ы

**DoD**:
- [ ] Contract: `RuntimeRegistry` Protocol (register/unregister/get/list)
- [ ] Unit: registration, discovery, validation, override — 12+ тестов
- [ ] Integration: plugin entry point загружен и работает — 3+ тестов
- [ ] Существующие тесты НЕ ломаются (backward compatible)

---

## Phase 7: Production Safety

**Цель**: Контроль расходов, валидация, access control, изоляция секретов.

### 7A: Budget / Cost Tracking (IDEA-004)

**Приоритет**: High | **Сложность**: Medium | **~3-4 дня**

**Scope**:
1. `BudgetPolicy`: `max_input_tokens`, `max_output_tokens`, `max_cost_usd`, `action_on_exceed` (pause/error/warn)
2. `UsageTracker` — аккумулирует usage из `TurnMetrics` per-session
3. `RuntimeConfig.budget: BudgetPolicy | None`
4. Pre-call check → `RuntimeEvent.error(kind="budget_exceeded")` или warning
5. Pricing table: model → cost per 1K input/output tokens (JSON, обновляемая)
6. `UsageTracker.report()` → summary (tokens used, cost, remaining)

**DoD**:
- [ ] Contract: `BudgetPolicy` + `UsageTracker` Protocol
- [ ] Unit: tracking, limits, pricing calc, edge cases — 15+ тестов
- [ ] Integration: budget exceeded → pause/error для thin + deepagents — 4+ тестов
- [ ] Pricing table для Anthropic, OpenAI, Google моделей

### 7B: Guardrails + CallerPolicy (IDEA-008, IDEA-022)

**Приоритет**: High | **Сложность**: Medium | **~5-6 дней**

**Зависит от**: 6A (structured output — для typed guardrail results)

> **Новое в v2**: CallerPolicy из NanoClaw — identity-based access control как первая линия защиты до content guardrails.

**Scope**:
1. `Guardrail` Protocol: `async (context, input) -> GuardrailResult(passed, reason, output)`
2. `InputGuardrail` — до LLM (jailbreak, PII, off-topic detection)
3. `OutputGuardrail` — после LLM (format validation, safety, hallucination)
4. Tripwire: `tripwire_triggered=True` → `RuntimeEvent.error(kind="guardrail_tripwire")`
5. `RuntimeConfig.guardrails: list[Guardrail]`
6. Параллельный запуск (asyncio.gather), fail-fast при tripwire
7. **CallerPolicy** (IDEA-022): allowlist/denylist по caller identity (API key, user ID)
8. Builtin: `ContentLengthGuardrail`, `RegexGuardrail`, `CallerAllowlistGuardrail`

**DoD**:
- [ ] Contract: `Guardrail`, `InputGuardrail`, `OutputGuardrail`, `CallerPolicy` Protocols
- [ ] Unit: pass/fail/tripwire, parallel execution, chain, caller filtering — 18+ тестов
- [ ] Integration: guardrail блокирует вызов через thin runtime — 4+ тестов
- [ ] Пример: custom guardrail + caller allowlist в docs

### 7C: Pre-LLM Input Filter Hook (IDEA-013)

**Приоритет**: Medium | **Сложность**: Low | **~1-2 дня**

**Scope**:
1. `InputFilter` Protocol: `async (messages, system_prompt, config) -> (messages, system_prompt)`
2. `RuntimeConfig.input_filters: list[InputFilter]`
3. Выполняется после compaction, перед adapter.call()
4. Builtin: `MaxTokensFilter`, `SystemPromptInjector`

**DoD**:
- [ ] Contract: `InputFilter` Protocol
- [ ] Unit: filter chain, message trimming, system prompt injection — 10+ тестов
- [ ] Integration: filter применяется в thin runtime — 3+ тестов

### 7D: Credential Proxy (IDEA-020)

**Приоритет**: Medium | **Сложность**: Low | **~2-3 дня**

> **Источник**: NanoClaw credential-proxy.ts — секреты никогда не попадают в runtime агента.

**Scope**:
1. `CredentialInjector` Protocol: `inject(request) -> request_with_auth`
2. Runtime получает placeholder key → injector подставляет реальный перед HTTP-вызовом
3. Режимы: API key injection, OAuth token injection, custom header
4. Multi-tenant: разные агенты → разные credentials, агент не видит чужие ключи
5. `RuntimeConfig.credential_injector: CredentialInjector | None`

**DoD**:
- [ ] Contract: `CredentialInjector` Protocol
- [ ] Unit: injection, multi-tenant isolation, placeholder resolution — 10+ тестов
- [ ] Integration: agent не видит реальный API key — 3+ тестов

---

## Phase 8: Persistence & Observability

**Цель**: Сессии не теряются, всё трейсится, память многоуровневая.

### 8A: Session Backends (IDEA-010, поглощает IDEA-005)

**Приоритет**: High | **Сложность**: Medium | **~4-5 дней**

**Scope**:
1. `SessionBackend` Protocol: `save(key, state)` / `load(key)` / `delete(key)` / `list()`
2. `SqliteSessionBackend` — zero-config, для dev/single-node
3. `RedisSessionBackend` (optional `swarmline[redis]`)
4. `EncryptedSessionBackend` — overlay (AES-256-GCM)
5. Сериализация: history, rolling_summary, session_id, turn_count, metadata
6. `SessionManager(backend=...)` — inject через конструктор
7. Auto-resume: при connect() проверяет сохранённую сессию

**DoD**:
- [ ] Contract: `SessionBackend` Protocol
- [ ] Unit: save/load/delete/list для SQLite, encrypted overlay — 15+ тестов
- [ ] Integration: session resume после restart — 4+ тестов
- [ ] Redis тесты с pytest-docker или mock — 4+ тестов

### 8B: Tracing / Observability (IDEA-015)

**Приоритет**: Medium | **Сложность**: Medium | **~3-4 дня**

**Scope**:
1. `Tracer` Protocol: `start_span(name, attrs)` / `end_span()` / `add_event()`
2. Auto-instrumentation: LLM call, tool call, guardrail → span
3. `ConsoleTracer` (dev), `OpenTelemetryTracer` (production), `NoopTracer` (default)
4. `RuntimeConfig.tracer: Tracer | None`
5. Context propagation: parent span → child span (trace_id)
6. Vendor-neutral: OpenTelemetry

**DoD**:
- [ ] Contract: `Tracer` Protocol
- [ ] Unit: span lifecycle, nesting, attributes — 12+ тестов
- [ ] Integration: full agent turn с трейсингом — 4+ тестов
- [ ] ConsoleTracer выводит human-readable trace

### 8C: Memory Scopes (IDEA-021)

**Приоритет**: Medium | **Сложность**: Low | **~2-3 дня**

> **Источник**: NanoClaw three-tier memory hierarchy (global/group/session).

**Scope**:
1. `MemoryScope` enum: `global_`, `agent`, `shared`
2. `global_` — read by all agents, write by orchestrator only
3. `agent` — read/write by single agent (default, как сейчас)
4. `shared` — read/write by agent group (namespace-based)
5. Scope = prefix key в SessionBackend: `global:key`, `agent:{id}:key`, `shared:{group}:key`
6. Enforcement: agent namespace isolation — agent не может писать в чужой scope

**DoD**:
- [ ] Contract: `MemoryScope` + scoped SessionBackend wrapper
- [ ] Unit: scope enforcement, namespace isolation — 10+ тестов
- [ ] Integration: multi-agent с shared и isolated scopes — 3+ тестов

---

## Phase 9: Multi-Agent & Task System

**Цель**: Агенты работают вместе — таски, иерархия, делегирование, расписание.

### 9A: Agent-as-Tool (IDEA-009)

**Приоритет**: Medium | **Сложность**: Medium | **~3-4 дня**

**Зависит от**: 7A (budget)

**Scope**:
1. `AgentRuntime.as_tool(name, description) -> ToolSpec`
2. Tool executor: запуск sub-agent с input, возврат текстового результата
3. Изоляция: sub-agent не видит историю parent'а
4. Budget attribution: расходы sub-agent → parent budget
5. Timeout: `max_seconds` для sub-agent вызова

**DoD**:
- [ ] Contract: `as_tool()` method в `AgentRuntime` Protocol
- [ ] Unit: tool creation, execution, isolation, budget — 12+ тестов
- [ ] Integration: parent agent вызывает sub-agent через tool — 4+ тестов

### 9B: Task Backlog System (IDEA-018) — NEW

**Приоритет**: High | **Сложность**: High | **~7-10 дней**

**Зависит от**: 8A (session backends — для persistence)

> **Референс**: Paperclip issues system — полная модель задач с status machine, checkout, priority, atomic claim, session per task.

**Архитектура**:

```
TaskSystem
├── TaskStore              — CRUD + фильтры + полнотекстовый поиск
├── StatusMachine          — backlog → todo → in_progress → done/cancelled/blocked
├── CheckoutEngine         — атомарный захват задачи агентом (Paperclip pattern)
├── PriorityQueue          — critical > high > medium > low
├── TaskSession            — persistent session per task (не per agent)
└── TaskEvents             — history изменений (append-only)
```

**Модель данных (Task)**:
```python
@dataclass
class Task:
    id: str                          # uuid
    title: str
    description: str | None
    status: TaskStatus               # backlog/todo/in_progress/in_review/done/cancelled/blocked
    priority: TaskPriority           # critical/high/medium/low
    assignee_agent_id: str | None    # назначенный агент
    parent_id: str | None            # дочерние задачи (дерево)
    created_by_agent_id: str | None  # кто создал (агент может создавать задачи)
    checkout_run_id: str | None      # какой run держит checkout
    labels: list[str]
    metadata: dict
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
```

**Status Machine** (по Paperclip):
```
backlog → todo → in_progress → in_review → done
                             ↘ blocked
                             ↘ cancelled
```

Auto side-effects:
- `→ in_progress`: set `started_at`, require `assignee_agent_id`
- `→ done`: set `completed_at`
- `→ cancelled`: set `cancelled_at`
- change assignee: clear `checkout_run_id`

**Checkout (атомарный захват задачи)** — ключевой механизм:
1. `task_store.checkout(task_id, agent_id, run_id)` — атомарный UPDATE
2. Только если: status IN (todo, backlog) AND (no assignee OR same agent) AND (no checkout OR same run)
3. Stale checkout adoption: если run завершён → новый run может забрать задачу
4. `task_store.release(task_id, agent_id, run_id)` → status = todo, clear assignee
5. Conflict: 409 если задача занята другим агентом/run'ом

**Task Session** (persistent context per task):
1. Каждая задача имеет свою сессию (не привязана к агенту)
2. При переназначении задачи другому агенту — сессия сохраняется
3. Session compaction при превышении порогов (как в Paperclip)
4. Handoff markdown при ротации сессии

**Фильтры и поиск**:
```python
TaskFilters(
    status="todo,in_progress",       # comma-separated
    assignee_agent_id="agent-1",
    parent_id="task-parent",
    labels=["bug", "critical"],
    q="search query",               # полнотекстовый по title + description
    sort_by="priority",             # priority, created_at, updated_at
)
```

**API для агентов** (tools, доступные агенту):
1. `list_tasks(filters)` — список задач
2. `checkout_task(task_id)` — взять в работу
3. `update_task_status(task_id, new_status)` — сменить статус
4. `create_task(title, description, priority, parent_id)` — создать подзадачу
5. `release_task(task_id)` — вернуть в backlog
6. `add_task_comment(task_id, text)` — комментарий

**DoD**:
- [ ] Contract: `TaskStore`, `Task`, `TaskStatus`, `CheckoutEngine` Protocols
- [ ] Unit: CRUD, status transitions, priority sort — 12+ тестов
- [ ] Unit: checkout (atomic, stale adoption, conflict) — 10+ тестов
- [ ] Unit: task session (create, compaction, handoff) — 8+ тестов
- [ ] Unit: filters и поиск — 8+ тестов
- [ ] Integration: agent checkout → work → complete cycle — 4+ тестов
- [ ] Integration: concurrent checkout conflict — 3+ тестов
- [ ] SQLite и in-memory backend'ы

### 9C: Agent Hierarchy & Org Chart (IDEA-019) — NEW

**Приоритет**: High | **Сложность**: Medium-High | **~5-7 дней**

**Зависит от**: 9B (task backlog), 7A (budget)

> **Референс**: Paperclip agents.reportsTo — org chart через само-ссылку, lifecycle management, permissions, budget per agent.

**Архитектура**:

```
AgentRegistry
├── AgentConfig            — name, role, capabilities, adapter, budget, permissions
├── OrgChart               — дерево через reports_to (само-ссылка)
├── LifecycleManager       — pending → idle → running → paused → terminated
├── PermissionEngine       — can_create_agents, can_assign_tasks, etc.
└── ConfigVersioning       — snapshot before/after при каждом изменении
```

**Модель данных (AgentConfig)**:
```python
@dataclass
class AgentConfig:
    id: str                          # uuid
    name: str                        # human-readable
    role: str                        # "manager", "engineer", "reviewer"
    title: str | None                # "Lead Engineer", "CTO"
    status: AgentStatus              # idle/running/paused/terminated
    reports_to: str | None           # parent agent id (дерево)
    capabilities: str | None         # описание компетенций
    runtime_name: str                # "thin", "deepagents", "cli", "openai_agents"
    runtime_config: dict             # per-agent runtime settings
    budget_monthly_usd: float        # месячный бюджет
    spent_monthly_usd: float
    permissions: AgentPermissions    # что агент может делать
    pause_reason: str | None         # "manual", "budget", "system"
    metadata: dict
```

**Agent Lifecycle** (по Paperclip):
```
pending_approval → idle ↔ running
                    ↕         ↕
                  paused    error
                    ↓
                terminated (необратимо)
```

- `pause(agent_id, reason)` — manual / budget / system
- `resume(agent_id)` → idle
- `terminate(agent_id)` → revoke keys, cleanup

**Org Chart** (дерево через само-ссылку):
1. `reports_to` → parent agent в иерархии
2. **Cycle detection**: обход вверх по цепочке (max 50 levels)
3. `get_org_chart(root_id)` → рекурсивное дерево `{agent, reports: [...]}`
4. `get_chain_of_command(agent_id)` → список менеджеров до корня

**Permissions** (что агент может делать):
```python
@dataclass
class AgentPermissions:
    can_create_agents: bool = False      # может нанимать подчинённых
    can_assign_tasks: bool = True        # может назначать задачи
    can_create_tasks: bool = True        # может создавать задачи
    can_pause_agents: bool = False       # может ставить на паузу
    can_terminate_agents: bool = False   # может увольнять
    max_sub_agents: int = 5             # лимит подчинённых
```

**Agent Creation by Agent**:
1. Агент с `can_create_agents=True` создаёт нового агента
2. Новый агент автоматически `reports_to = creating_agent.id`
3. Если `require_approval=True` → статус `pending_approval` (ждёт подтверждения)
4. Budget нового агента ≤ budget создателя (нельзя дать больше чем имеешь)

**Config Versioning** (по Paperclip):
1. Каждое изменение ключевых полей → snapshot `before_config` / `after_config`
2. `rollback(agent_id, revision_id)` → восстановить конфигурацию
3. Аудит: кто, когда, что изменил

**Универсальность для внешних приложений**:
- `AgentRegistry` Protocol — внешнее приложение может подставить свой backend
- REST-style API: create/get/update/delete/list agents + org chart queries
- Event hooks: `on_agent_created`, `on_status_changed`, `on_task_assigned`
- Произвольные топологии: flat team, deep hierarchy, matrix (agent reports to multiple)

**DoD**:
- [ ] Contract: `AgentRegistry`, `AgentConfig`, `OrgChart`, `LifecycleManager` Protocols
- [ ] Unit: CRUD, lifecycle transitions, budget enforcement — 12+ тестов
- [ ] Unit: org chart (cycle detection, chain of command, tree build) — 10+ тестов
- [ ] Unit: permissions enforcement, agent creation by agent — 8+ тестов
- [ ] Unit: config versioning, rollback — 6+ тестов
- [ ] Integration: parent creates child → assigns task → child completes — 4+ тестов
- [ ] Integration: budget exceeded → auto-pause — 3+ тестов

### 9D: Multi-Agent Delegation (IDEA-006)

**Приоритет**: High | **Сложность**: High | **~5-7 дней**

**Зависит от**: 6C (registry), 7A (budget), 7B (guardrails), 9A (agent-as-tool), 9B (task backlog), 9C (hierarchy)

> **Усилено в v2**: делегирование теперь использует TaskStore для создания подзадач и AgentRegistry для routing по hierarchy.

**Scope**:
1. `AgentOrchestrator` — координатор нескольких runtime'ов
2. `DelegationTool` — `delegate(agent_name, task)` → создаёт Task в TaskStore + wakeup agent
3. Routing: по имени, по capability, по org chart (delegate down), round-robin
4. Task lock через CheckoutEngine (Phase 9B) — не отдельная реализация
5. Result aggregation — сбор результатов
6. Budget propagation: parent → child limits
7. `ConcurrencyGroup` — max_concurrent per group (NanoClaw pattern)

**DoD**:
- [ ] Contract: `Orchestrator` Protocol, `DelegationTool`
- [ ] Unit: routing, concurrency groups, aggregation, budget propagation — 20+ тестов
- [ ] Integration: orchestrator координирует 2 агента на разных runtime'ах — 4+ тестов
- [ ] E2E: полный delegation flow (parent → task → child → result) — 2+ тестов

### 9E: Scheduled / Heartbeat Agents (IDEA-007)

**Приоритет**: High | **Сложность**: Medium-High | **~5-7 дней**

**Зависит от**: 8A (session backends), 9B (task backlog), 10A (CLI runtime)

> **Референсы**: Paperclip heartbeat, OpenClaw cron, claudecron, NanoClaw

**Архитектура**:

```
AgentScheduler
├── TriggerEngine          — cron/interval/one-shot/event
├── WakeupQueue            — queue-then-execute (Paperclip)
├── SessionTargeting       — isolated/custom-named/main (OpenClaw)
├── CoalescingEngine       — merge concurrent wakeups (Paperclip)
├── RunHistory             — JSONL append-only
├── JitterPolicy           — deterministic per-job offset
└── ContextSinceLastRun    — conversation catch-up (NanoClaw)
```

**Triggers (4 типа)**:
1. `timer` — cron (5-field + IANA timezone) или interval (seconds)
2. `one_shot` — ISO 8601, auto-disable после fire
3. `event` — webhook/callback (HTTP POST → enqueue)
4. `on_demand` — ручной запуск

**Session targeting (3 режима)**:
1. `isolated` (default) — fresh context per run
2. `custom_named` — persistent context across runs
3. `main` — inject в существующую сессию (heartbeat mode)

**Queue & Coalescing**: queue-then-execute, maxConcurrentRuns, merge same-scope wakeups, orphan detection.

**Context since last run** (NanoClaw pattern): при пробуждении агент получает events с момента последнего запуска.

**State**: SQLite, JSONL run history, no catch-up, deterministic jitter.

**Wakeup Context**:
```python
WakeupContext(
    trigger_type="timer",
    trigger_detail="cron: 0 9 * * 1-5",
    last_run_at=datetime,
    last_run_summary=str | None,
    run_number=int,
    session_mode="isolated",
    event_payload=dict | None,
    events_since_last_run=list[Event] | None,  # NEW v2
)
```

**DoD**:
- [ ] Contract: `Scheduler`, `Trigger`, `WakeupQueue`, `SessionTarget` Protocols
- [ ] Unit: cron, interval, one-shot, jitter — 10+ тестов
- [ ] Unit: coalescing, queue lifecycle, orphan detection — 10+ тестов
- [ ] Unit: session targeting, JSONL history, context catch-up — 10+ тестов
- [ ] Integration: scheduled agent full cycle — 4+ тестов
- [ ] Integration: coalescing + event trigger — 4+ тестов

---

## Phase 10: Platform

**Цель**: CLI runtime, MCP, OAuth, token optimization.

### 10A: CLI Agent Runtime (IDEA-003)

**Приоритет**: High | **Сложность**: Medium | **~5-7 дней**

**Зависит от**: 6C (adapter registry)

> **Референс**: Paperclip runChildProcess + adapters.

**Архитектура**:

```
CliAgentRuntime implements AgentRuntime
├── ProcessManager         — spawn/cancel/reap
├── NdjsonParser           — line-by-line stream-json → RuntimeEvent
├── SessionCodec           — per-CLI session serialize/resume
├── PromptRenderer         — template → stdin payload
└── Presets                — claude/codex/gemini/deepagents/opencode/custom
```

**Core**: subprocess exec (NO shell), stdin-as-prompt, env isolation (CLAUDE_CODE_* removal), process registry, SIGTERM→SIGKILL, 4MB output cap.

**NDJSON Parser per CLI**:
- Claude Code: `type: "system/init"` → session_id, `type: "result"` → final + usage
- Codex: JSON с `previous_response_id` chaining
- DeepAgents CLI: `-n` non-interactive + `--no-stream` для buffered output
- Gemini: свой формат (TBD)

**Session Management**: SessionCodec, `--resume <sid>`, compaction (max runs/tokens/age), handoff markdown.

**Presets (6 CLI-агентов)**:
1. **Claude Code**: `claude --print - --output-format stream-json --verbose [--resume <sid>] [--model <m>] [--max-turns N]`
2. **Codex**: `codex exec --json [--model <m>]`
3. **Gemini CLI**: `gemini --json [--model <m>]`
4. **DeepAgents CLI**: `deepagents -n "<task>" -q [--no-stream] [--agent <name>] [--model <m>] [-S recommended]`
5. **OpenCode**: `opencode --json`
6. **Custom**: user-defined command + args + parser

**DoD**:
- [ ] Contract: `CliAgentRuntime`, `NdjsonParser`, `SessionCodec` Protocols
- [ ] Unit: NDJSON parsing (claude/codex/deepagents/gemini) — 12+ тестов
- [ ] Unit: process lifecycle (spawn/cancel/timeout/orphan) — 8+ тестов
- [ ] Unit: session codec, compaction, handoff — 8+ тестов
- [ ] Unit: presets validation (6 конфигов) — 6+ тестов
- [ ] Integration: subprocess mock + full flow — 4+ тестов
- [ ] Integration: session resume — 3+ тестов

### 10B: MCP Multi-Transport (IDEA-014)

**Приоритет**: Medium | **Сложность**: Medium | **~3-4 дня**

**Scope**:
1. `McpTransport` Protocol: `connect()` / `call_tool()` / `list_tools()` / `disconnect()`
2. `StdioTransport` — для локальных MCP серверов
3. `StreamableHttpTransport` — для remote (рекомендуемый для prod)
4. Per-server transport config
5. Tool list caching

**DoD**:
- [ ] Contract: `McpTransport` Protocol
- [ ] Unit: transport lifecycle, caching — 12+ тестов
- [ ] Integration: Stdio + HTTP transport — 4+ тестов

### 10C: MCP Approval Policies (IDEA-012)

**Приоритет**: Medium | **Сложность**: Low | **~1-2 дня**

**Зависит от**: 10B

**Scope**: ApprovalPolicy enum, per-tool config, HITL integration.

**DoD**:
- [ ] Unit: policy matching, event emission — 8+ тестов
- [ ] Integration: approval flow через HITL — 3+ тестов

### 10D: OAuth Subscription Auth (IDEA-001)

**Приоритет**: Medium | **Сложность**: Medium | **~3-4 дня**

**Scope**: OAuth token в RuntimeConfig, refresh, Bearer auth, CLI flow `swarmline auth login`, token storage.

**DoD**:
- [ ] Contract: `AuthProvider` Protocol
- [ ] Unit: token refresh, expiry, storage — 10+ тестов
- [ ] Integration: OAuth token для LLM вызова — 3+ тестов

### 10E: RTK Token Optimization (IDEA-017) — NEW

**Приоритет**: Low | **Сложность**: Low | **~1-2 дня**

> **Источник**: rtk-ai.app — CLI proxy, 60-90% экономия токенов на dev-операциях (git, test, build).

**Как работает RTK**: Rust-based CLI proxy, перехватывает bash-команды (git diff, pytest, npm test, etc.), фильтрует boilerplate из вывода, оставляет только сигнал. Не LLM-суммаризация — детерминированная фильтрация.

**Два режима интеграции**:
1. **Автоматический** (zero-config): RTK уже установлен как Claude Code hook → работает для ClaudeCodeRuntime без изменений
2. **Программный** (toggleable): для ThinRuntime и CLI runtime — subprocess wrapper

**Scope**:
1. `TokenOptimizer` Protocol: `optimize(command, output) -> optimized_output`
2. `RtkOptimizer` — wrapper: если `shutil.which("rtk")` → route через `rtk <command>`
3. `RuntimeConfig.token_optimizer: TokenOptimizer | None` (disabled by default)
4. Включение: `RuntimeConfig(token_optimizer=RtkOptimizer())` или env `SWARMLINE_RTK_ENABLED=1`
5. Fallback: если RTK не установлен → warning + pass-through (не crash)
6. Transparent: агент не знает что output оптимизирован

**DoD**:
- [ ] Contract: `TokenOptimizer` Protocol
- [ ] Unit: rtk detection, fallback, enable/disable — 8+ тестов
- [ ] Integration: command через rtk proxy — 3+ тестов

---

## Сводная таблица

| Phase | Идеи | Оценка | Ключевой результат |
|-------|-------|--------|-------------------|
| **6** | 011, 016, 002 | ~6-8 дн | Structured output + @tool + pluggable runtimes |
| **7** | 004, 008, 022, 013, 020 | ~11-15 дн | Budget + guardrails + caller policy + credential proxy |
| **8** | 010+005, 015, 021 | ~9-12 дн | Sessions + tracing + memory scopes |
| **9** | 009, 018, 019, 006, 007 | ~25-35 дн | Tasks + hierarchy + delegation + scheduler |
| **10** | 003, 014, 012, 001, 017 | ~13-19 дн | CLI runtime + MCP + OAuth + RTK |
| **11** | OpenAI Agents SDK | ~11-15 дн | 4-й runtime + bridges |
| **Total** | **22 идеи + SDK** | **~75-104 дня** | Production-ready мультирунтайм платформа с task management |

---

## Критические пути

1. **Structured Output (6A) → Guardrails (7B) → Multi-Agent (9D)** — основная цепочка
2. **Session Backends (8A) → Task Backlog (9B) → Agent Hierarchy (9C) → Delegation (9D) → Scheduler (9E)** — task/agent стек
3. **Adapter Registry (6C) → CLI Runtime (10A)** — расширяемость
4. **Budget (7A) → Agent-as-Tool (9A)** — cost control

## Параллелизация

```
Week 1-2:   6A + 6B + 6C (параллельно)
Week 3-5:   7A + 7C + 7D (параллельно) | 7B после 6A
Week 5-7:   8A + 8B + 8C (параллельно)
Week 8-10:  9A + 9B (параллельно) → 9C после 9B
Week 11-13: 9D → 9E (последовательно)
Week 14-16: 10A-10E (параллельно где возможно)
Week 17-19: 11A → 11B + 11C + 11D
```

---

## Phase 11: OpenAI Agents SDK Integration

**Цель**: 4-й runtime. Мост swarmline ↔ openai-agents.

> **Условие старта**: OpenAI Agents SDK ≥ v1.0 ИЛИ Phase 6-10 done.
> **Референс**: `reports/2026-03-17_research_openai-agents-sdk.md`, ADR-001.

### 11A: OpenAI Agents Runtime (~4-5 дн)
`OpenAIAgentsRuntime` → `AgentRuntime`, tool bridge, event mapping, custom TracingProcessor (не openai traces), LiteLLM multi-provider.

### 11B: Session Backends Bridge (~2-3 дн)
swarmline `SessionBackend` ↔ openai-agents session storage (9 backends).

### 11C: Structured Output & Guardrails Bridge (~2-3 дн)
output_type bridge, guardrails bridge, handoff → delegation mapping.

### 11D: MCP & Advanced (~3-4 дн)
MCP bridge (5 transports), approval bridge, griffe tool schema, agent-as-tool bridge.

---

## Блокеры и риски

| Риск | Impact | Mitigation |
|------|--------|-----------|
| deepagents 0.5.0 не на PyPI | Medium | Остаёмся на 0.4.11, portable path |
| OpenTelemetry overhead | Low | NoopTracer default, sampling |
| Pydantic ≠ LLM JSON Schema | Medium | Retry + relaxed validation |
| Task backlog scale (>10K tasks) | Medium | SQLite indexes + pagination |
| Agent hierarchy cycles | High | Cycle detection (max 50 levels) |
| Multi-agent deadlocks | High | Timeout + task lock + cycle detection |
| OpenAI Agents SDK breaking changes | High | Adapter layer isolates, pin version |
| RTK not installed | Low | Graceful fallback, no crash |
| Concurrent checkout races | Medium | Atomic UPDATE + optimistic locking |
