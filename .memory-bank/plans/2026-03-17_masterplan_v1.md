# Master Plan v1.0 — Swarmline Roadmap

> Создан: 2026-03-17
> Базовая версия: 0.5.0 (multi-provider ThinRuntime + upstream middleware)
> Все 16 идей из BACKLOG + OpenAI Agents SDK интеграция включены

---

## Обзор

```
Phase 6: DX Foundation          ← structured output, tool decorator, adapter registry
Phase 7: Production Safety      ← budget tracking, guardrails, input filters
Phase 8: Persistence            ← session backends, session persistence, tracing
Phase 9: Multi-Agent            ← agent-as-tool, multi-agent delegation, scheduler
Phase 10: Platform              ← CLI runtime, MCP multi-transport, OAuth, MCP approval
Phase 11: OpenAI Agents SDK     ← 4-й runtime, session backends port, guardrails bridge
```

## Граф зависимостей

```
IDEA-016 (tool decorator) ──────────────────────────────────┐
IDEA-011 (structured output) ──→ IDEA-008 (guardrails) ─────┤
IDEA-002 (adapter registry) ──→ IDEA-003 (CLI runtime) ─────┤
IDEA-004 (budget) ────────────→ IDEA-009 (agent-as-tool) ───┤
IDEA-013 (input filter) ─────────────────────────────────────┤
IDEA-010 (session backends) ──→ IDEA-005 (persistence) ──────┤
IDEA-015 (tracing) ──────────────────────────────────────────┤
IDEA-008 (guardrails) ───────→ IDEA-006 (multi-agent) ──────┤
IDEA-009 (agent-as-tool) ────→ IDEA-006 (multi-agent) ──────┤
IDEA-006 (multi-agent) ──────→ IDEA-007 (scheduler) ────────┘
IDEA-014 (MCP multi-transport) → IDEA-012 (MCP approval)
IDEA-001 (OAuth) — независим
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
- [ ] Документация с примерами

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

**Цель**: Контроль расходов, валидация input/output, pre-LLM хуки.

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

### 7B: Guardrails (IDEA-008)

**Приоритет**: High | **Сложность**: Medium | **~4-5 дней**

**Зависит от**: 6A (structured output — для typed guardrail results)

**Scope**:
1. `Guardrail` Protocol: `async (context, input) -> GuardrailResult(passed, reason, output)`
2. `InputGuardrail` — до LLM (jailbreak, PII, off-topic detection)
3. `OutputGuardrail` — после LLM (format validation, safety, hallucination)
4. Tripwire: `tripwire_triggered=True` → `RuntimeEvent.error(kind="guardrail_tripwire")`
5. `RuntimeConfig.guardrails: list[Guardrail]`
6. Параллельный запуск (asyncio.gather), fail-fast при tripwire
7. Builtin guardrails: `ContentLengthGuardrail`, `RegexGuardrail` (примеры)

**DoD**:
- [ ] Contract: `Guardrail`, `InputGuardrail`, `OutputGuardrail` Protocols
- [ ] Unit: pass/fail/tripwire, parallel execution, chain — 15+ тестов
- [ ] Integration: guardrail блокирует вызов через thin runtime — 4+ тестов
- [ ] Пример: custom guardrail в docs

### 7C: Pre-LLM Input Filter Hook (IDEA-013)

**Приоритет**: Medium | **Сложность**: Low | **~1-2 дня**

**Scope**:
1. `InputFilter` Protocol: `async (messages, system_prompt, config) -> (messages, system_prompt)`
2. `RuntimeConfig.input_filters: list[InputFilter]`
3. Выполняется после compaction, перед adapter.call()
4. Builtin: `MaxTokensFilter` (обрезает историю до N tokens), `SystemPromptInjector`

**DoD**:
- [ ] Contract: `InputFilter` Protocol
- [ ] Unit: filter chain, message trimming, system prompt injection — 10+ тестов
- [ ] Integration: filter применяется в thin runtime — 3+ тестов

---

## Phase 8: Persistence & Observability

**Цель**: Сессии не теряются, всё трейсится.

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
6. Vendor-neutral: OpenTelemetry, НЕ привязка к OpenAI/Anthropic

**DoD**:
- [ ] Contract: `Tracer` Protocol
- [ ] Unit: span lifecycle, nesting, attributes — 12+ тестов
- [ ] Integration: full agent turn с трейсингом — 4+ тестов
- [ ] ConsoleTracer выводит human-readable trace

---

## Phase 9: Multi-Agent

**Цель**: Агенты работают вместе — вызов, делегирование, расписание.

### 9A: Agent-as-Tool (IDEA-009)

**Приоритет**: Medium | **Сложность**: Medium | **~3-4 дня**

**Зависит от**: 7A (budget — для учёта расходов sub-agent)

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

### 9B: Multi-Agent Delegation (IDEA-006)

**Приоритет**: High | **Сложность**: High | **~5-7 дней**

**Зависит от**: 6C (registry), 7A (budget), 7B (guardrails), 9A (agent-as-tool)

**Scope**:
1. `AgentOrchestrator` — координатор нескольких runtime'ов
2. `DelegationTool` — `delegate(agent_name, task)` как tool для агента
3. Routing: по имени, по capability, round-robin
4. Task lock — защита от гонок при параллельных sub-agents
5. Result aggregation — сбор результатов
6. Budget propagation: parent → child limits

**DoD**:
- [ ] Contract: `Orchestrator` Protocol, `DelegationTool`
- [ ] Unit: routing, locking, aggregation, budget propagation — 20+ тестов
- [ ] Integration: orchestrator координирует 2 агента на разных runtime'ах — 4+ тестов
- [ ] E2E: полный delegation flow (parent → child → result) — 2+ тестов

### 9C: Scheduled / Heartbeat Agents (IDEA-007)

**Приоритет**: High | **Сложность**: Medium-High | **~5-7 дней**

**Зависит от**: 8A (session backends — для persistence), 10A (CLI runtime — для subprocess agents)

> **Референсы**: Paperclip heartbeat (4 trigger types, coalescing, queue-then-execute), OpenClaw cron (session targeting, jitter, JSONL history), claudecron (5 trigger types, dependency chains), NanoClaw (container isolation)

**Архитектура** (гибрид лучших паттернов):

```
AgentScheduler
├── TriggerEngine          — cron/interval/one-shot/event evaluation
├── WakeupQueue            — queue-then-execute (Paperclip pattern)
├── SessionTargeting       — isolated/custom-named/main (OpenClaw pattern)
├── CoalescingEngine       — merge concurrent wakeups (Paperclip pattern)
├── RunHistory             — JSONL append-only (OpenClaw/claudecron pattern)
└── JitterPolicy           — deterministic per-job offset (OpenClaw pattern)
```

**Scope**:

**Triggers (4 типа, как в Paperclip)**:
1. `timer` — cron expression (5-field + optional IANA timezone) или interval (seconds)
2. `one_shot` — ISO 8601 timestamp, auto-disable после fire
3. `event` — webhook/callback trigger (HTTP POST → enqueue wakeup)
4. `on_demand` — ручной запуск через API / CLI

**Session targeting (3 режима, как в OpenClaw)**:
1. `isolated` (default) — fresh context per run, prune по retention policy
2. `custom_named` — persistent context across runs (e.g. "daily-standup" session)
3. `main` — inject в существующую сессию (heartbeat mode, с warning про token cost)

**Queue & Coalescing (Paperclip pattern)**:
1. Все wakeup'ы → `WakeupQueue` со статусом `queued`
2. `maxConcurrentRuns` per agent (default 1)
3. Coalescing: если queued run для того же scope — merge context, не создавать новый
4. Orphan detection: при restart пометить running → failed

**State & Persistence**:
1. Job config → SQLite через `SessionBackend` (Phase 8A)
2. Run history → JSONL append-only (`~/.swarmline/scheduler/runs/<job_id>.jsonl`)
3. Persistent: last_run, next_run, run_count, total_tokens, total_cost
4. No catch-up: пропущенный fire = пропущен (как в Claude Code, OpenClaw)

**Jitter**:
1. Deterministic per-job offset derived from job_id hash (не random)
2. Max jitter = min(10% of interval, 5 minutes)
3. Защита от thundering herd при multiple jobs на top-of-hour

**Lifecycle**:
1. `scheduler.add_job(job_config)` → persist + schedule
2. `scheduler.remove_job(job_id)` → cancel + cleanup
3. `scheduler.pause_job(job_id)` / `resume_job(job_id)`
4. Graceful shutdown: finish current run, drain queue, persist state

**Wakeup Context** (передаётся агенту при каждом run):
```python
WakeupContext(
    trigger_type="timer",           # timer/one_shot/event/on_demand
    trigger_detail="cron: 0 9 * * 1-5",
    last_run_at=datetime,
    last_run_summary=str | None,    # rolling summary предыдущего run'а
    run_number=int,
    session_mode="isolated",
    event_payload=dict | None,      # для event trigger
)
```

**Use cases**:
- Мониторинг: проверка health endpoints каждые 5 минут (timer + isolated)
- CI/CD: агент реагирует на новые PR (event trigger + custom_named session)
- Daily standup: ежедневный summary кодовой базы (cron + custom_named "standup")
- Data pipeline: ежечасный ETL check (timer + isolated)
- Code review: периодический анализ uncommitted changes (cron + main session)
- Incident response: webhook от alertmanager → agent analyzes logs (event + isolated)

**DoD**:
- [ ] Contract: `Scheduler`, `Trigger`, `WakeupQueue`, `SessionTarget` Protocols
- [ ] Unit: cron parsing, interval eval, one-shot, jitter calc — 10+ тестов
- [ ] Unit: coalescing, queue lifecycle, orphan detection — 10+ тестов
- [ ] Unit: session targeting (isolated/custom/main), JSONL history — 8+ тестов
- [ ] Integration: scheduled agent просыпается и выполняет задачу — 4+ тестов
- [ ] Integration: coalescing при concurrent wakeups — 3+ тестов
- [ ] Integration: event trigger через webhook — 3+ тестов
- [ ] Пример: мониторинг-агент с cron trigger + isolated session

---

## Phase 10: Platform

**Цель**: CLI runtime, расширенный MCP, OAuth — полная платформа.

### 10A: CLI Agent Runtime (IDEA-003)

**Приоритет**: High | **Сложность**: Medium | **~5-7 дней**

**Зависит от**: 6C (adapter registry — для pluggable registration)

> **Референс**: Paperclip `runChildProcess` + адаптеры claude_local/codex_local/gemini_local. Stdin-as-prompt, env isolation, NDJSON stream-json parsing, session resume через CLI flags.

**Архитектура** (по паттерну Paperclip):

```
CliAgentRuntime implements AgentRuntime
├── ProcessManager         — spawn/cancel/reap (runningProcesses registry)
├── NdjsonParser           — line-by-line stream-json → RuntimeEvent
├── SessionCodec           — per-CLI session serialize/resume
├── PromptRenderer         — template → stdin payload
└── Presets                — claude/codex/gemini/cline/opencode configs
```

**Scope**:

**Core: Process Lifecycle (Paperclip pattern)**:
1. `CliAgentRuntime` implements `AgentRuntime` Protocol
2. Config: `command`, `args`, `cwd`, `env`, `timeout`, `grace_period_sec`
3. Spawn subprocess (`asyncio.create_subprocess_exec`, NO shell)
4. Prompt через **stdin** (Paperclip pattern — не через args/env/file)
5. Env isolation: удалять `CLAUDE_CODE_*` vars (защита от nested session rejection)
6. `runningProcesses: dict[run_id, ProcessHandle]` — global registry для orphan detection
7. Cancel: graceful SIGTERM → `grace_period_sec` → SIGKILL
8. Output cap: 4MB stdout buffer (Paperclip default)

**NDJSON Parser (по Paperclip parse.ts)**:
1. Line-by-line async generator из stdout
2. Event mapping per CLI:
   - Claude Code: `type: "system/init"` → session_id, `type: "assistant"` → content, `type: "result"` → final + usage
   - Codex: JSON response с `previous_response_id` chaining
   - Gemini: свой формат (TBD при реализации)
3. Нормализация → `RuntimeEvent` (text/tool_call/error/final)
4. Usage extraction: input_tokens, output_tokens, total_cost_usd

**Session Management (Paperclip двухуровневая модель)**:
1. `SessionCodec` Protocol: `serialize(session_state) -> dict` / `deserialize(dict) -> session_state`
2. Claude Code: `--resume <sessionId>` + cwd compatibility check
3. Codex: `previous_response_id` chaining
4. Session compaction: авторотация при превышении `max_session_runs` / `max_input_tokens` / `max_session_age_hours`
5. Handoff markdown при ротации (summary предыдущей сессии → prompt следующей)

**Presets (6 CLI-агентов)**:
1. **Claude Code**: `claude --print - --output-format stream-json --verbose [--resume <sid>] [--model <m>] [--max-turns N]`
2. **Codex**: `codex exec --json [--model <m>]`
3. **Gemini CLI**: `gemini --json [--model <m>]`
4. **Cline CLI**: `cline --json [-y] [--acp]` (Agent Client Protocol support)
5. **OpenCode**: `opencode --json`
6. **Custom**: user-defined command + args + parser

**DoD**:
- [ ] Contract: `CliAgentRuntime` implements `AgentRuntime`, `NdjsonParser`, `SessionCodec` Protocols
- [ ] Unit: NDJSON parsing (claude/codex/gemini formats) — 12+ тестов
- [ ] Unit: process lifecycle (spawn/cancel/timeout/orphan) — 8+ тестов
- [ ] Unit: session codec (serialize/resume/compaction/handoff) — 8+ тестов
- [ ] Unit: presets validation (все 6 конфигов) — 6+ тестов
- [ ] Integration: subprocess mock + full flow — 4+ тестов
- [ ] Integration: session resume через CLI flag — 3+ тестов
- [ ] Регистрация через adapter registry автоматическая

### 10B: MCP Multi-Transport (IDEA-014)

**Приоритет**: Medium | **Сложность**: Medium | **~3-4 дня**

**Scope**:
1. `McpTransport` Protocol: `connect()` / `call_tool()` / `list_tools()` / `disconnect()`
2. `StdioTransport` — для локальных MCP серверов
3. `StreamableHttpTransport` — для remote (рекомендуемый для prod)
4. Per-server transport config: `McpServer(transport="streamable_http", url=...)`
5. Tool list caching (`cache_tools_list=True`)

**DoD**:
- [ ] Contract: `McpTransport` Protocol
- [ ] Unit: transport lifecycle, caching, error handling — 12+ тестов
- [ ] Integration: Stdio + HTTP transport работают с тестовым MCP server — 4+ тестов

### 10C: MCP Approval Policies (IDEA-012)

**Приоритет**: Medium | **Сложность**: Low | **~1-2 дня**

**Зависит от**: 10B (MCP multi-transport)

**Scope**:
1. `ApprovalPolicy`: `always_allow`, `always_deny`, `require_approval`
2. Per-tool config в `ToolPolicy`: `{"mcp__server__tool": "require_approval"}`
3. `RuntimeEvent.approval_required(tool_name, args)` → ожидание ответа
4. Интеграция с HITL

**DoD**:
- [ ] Contract: `ApprovalPolicy` enum + event flow
- [ ] Unit: policy matching, event emission — 8+ тестов
- [ ] Integration: approval flow через HITL — 3+ тестов

### 10D: OAuth Subscription Auth (IDEA-001)

**Приоритет**: Medium | **Сложность**: Medium | **~3-4 дня**

**Scope**:
1. OAuth token в `RuntimeConfig` (наряду с API key)
2. Token refresh (Claude: 8h TTL + refresh token)
3. `AnthropicAdapter` / `OpenAICompatAdapter` → Bearer вместо API key
4. CLI flow: `swarmline auth login --provider claude`
5. Token storage: keyring или encrypted file

**Ограничения OAuth-пути**: нет prompt caching, нет 1M context, нет service_tier

**DoD**:
- [ ] Contract: `AuthProvider` Protocol (get_token, refresh)
- [ ] Unit: token refresh, expiry, storage — 10+ тестов
- [ ] Integration: OAuth token используется для LLM вызова — 3+ тестов
- [ ] CLI: `swarmline auth login` работает end-to-end

---

## Сводная таблица

| Phase | Идеи | Оценка | Ключевой результат |
|-------|-------|--------|-------------------|
| **6** | 011, 016, 002 | ~6-8 дней | Structured output + @tool + pluggable runtimes |
| **7** | 004, 008, 013 | ~8-11 дней | Budget limits + guardrails + input hooks |
| **8** | 010+005, 015 | ~7-9 дней | Persistent sessions + OpenTelemetry tracing |
| **9** | 009, 006, 007 | ~13-18 дней | Agent-as-tool + delegation + scheduler (Paperclip-grade) |
| **10** | 003, 014, 012, 001 | ~12-17 дней | CLI runtime (Paperclip pattern) + MCP + OAuth |
| **11** | OpenAI Agents SDK | ~11-15 дней | 4-й runtime + bridges (sessions, guardrails, MCP) |
| **Total** | 16 идей + SDK | ~57-80 дней | Полноценная production-ready мультирунтайм платформа |

---

## Критические пути

1. **Structured Output (6A) → Guardrails (7B) → Multi-Agent (9B)** — основная цепочка
2. **Adapter Registry (6C) → CLI Runtime (10A)** — расширяемость
3. **Budget (7A) → Agent-as-Tool (9A) → Multi-Agent (9B) → Scheduler (9C)** — multi-agent стек
4. **Session Backends (8A)** — независим, можно параллелить с Phase 7

## Параллелизация

```
Week 1-2:   6A (structured output) + 6B (tool decorator) + 6C (registry) ← параллельно
Week 3-4:   7A (budget) + 7C (input filter) ← параллельно, 7B (guardrails) ← после 6A
Week 5-6:   8A (sessions) + 8B (tracing) ← параллельно
Week 7-9:   9A (agent-as-tool) → 9B (multi-agent) → 9C (scheduler) ← последовательно
Week 10-12: 10A-10D ← параллельно где возможно
Week 13-15: 11A (base) → 11B + 11C (параллельно) → 11D ← OpenAI Agents SDK
```

---

## Phase 11: OpenAI Agents SDK Integration

**Цель**: 4-й runtime на базе OpenAI Agents SDK. Мост между swarmline абстракциями и openai-agents примитивами.

> **Контекст**: ADR-001 (2026-03-17) отклонил немедленную интеграцию — pre-1.0, API нестабилен, tracing lock-in.
> **Условие старта**: OpenAI Agents SDK ≥ v1.0 (стабильный API) ИЛИ наша архитектура достаточно зрелая (Phase 6-10 done) чтобы абсорбировать breaking changes.
> **Референс**: `reports/2026-03-17_research_openai-agents-sdk.md`, `notes/2026-03-17_ADR-001_openai-agents-sdk.md`

### 11A: OpenAI Agents Runtime — базовая интеграция

**Приоритет**: Medium | **Сложность**: Medium | **~4-5 дней**

**Зависит от**: 6C (adapter registry), 7B (guardrails), 8A (session backends)

**Scope**:
1. `OpenAIAgentsRuntime` implements `AgentRuntime` Protocol
2. Mapping: `RuntimeConfig` → openai-agents `Agent` + `RunConfig`
3. Model routing: swarmline model_id → openai-agents model config
4. Tool bridge: swarmline `ToolSpec` ↔ openai-agents `FunctionTool`
5. Event mapping: openai-agents `RunResult` → swarmline `RuntimeEvent` stream
6. Регистрация через adapter registry (IDEA-002)

**Ключевые решения**:
- НЕ используем openai tracing — подключаем наш `Tracer` (Phase 8B) через custom `TracingProcessor`
- НЕ дублируем guardrails — bridge swarmline `Guardrail` → openai-agents `InputGuardrail`/`OutputGuardrail`
- LiteLLM multi-provider: используем для доступа к Anthropic/Google через openai-agents

**DoD**:
- [ ] Contract: `OpenAIAgentsRuntime` implements `AgentRuntime`
- [ ] Unit: config mapping, tool bridge, event mapping — 15+ тестов
- [ ] Integration: простой агент через OpenAI Agents SDK — 4+ тестов
- [ ] Все существующие contract тесты проходят для нового runtime

### 11B: Session Backends Bridge

**Приоритет**: Medium | **Сложность**: Low | **~2-3 дня**

**Зависит от**: 8A (session backends), 11A

**Scope**:
1. Адаптер: swarmline `SessionBackend` → openai-agents session storage
2. Поддержка 9 openai-agents backends (SQLite, Redis, PostgreSQL, Dapr, encrypted, DynamoDB, CosmosDB)
3. Импорт: `swarmline[openai-sessions]` — optional extra
4. Двунаправленный bridge: sessions созданные в openai-agents доступны в swarmline и наоборот

**DoD**:
- [ ] Contract: `OpenAISessionBridge` adapts SessionBackend
- [ ] Unit: bridge save/load/list для SQLite + Redis — 8+ тестов
- [ ] Integration: session resume через bridge — 3+ тестов

### 11C: Structured Output & Guardrails Bridge

**Приоритет**: Medium | **Сложность**: Low | **~2-3 дня**

**Зависит от**: 6A (structured output), 7B (guardrails), 11A

**Scope**:
1. Structured output: swarmline `output_type` → openai-agents `Agent(output_type=...)` → Pydantic validated
2. Guardrails bridge: swarmline `Guardrail` → openai-agents `InputGuardrail` / `OutputGuardrail`
3. Tripwire mapping: openai-agents guardrail failure → swarmline `RuntimeEvent.error(kind="guardrail_tripwire")`
4. Handoffs: swarmline multi-agent delegation (IDEA-006) → openai-agents `Handoff` primitive

**DoD**:
- [ ] Unit: output bridge, guardrail bridge, handoff bridge — 12+ тестов
- [ ] Integration: guardrail блокирует через openai-agents runtime — 3+ тестов
- [ ] E2E: structured output + guardrails full flow — 2+ тестов

### 11D: MCP & Advanced Features

**Приоритет**: Low | **Сложность**: Medium | **~3-4 дня**

**Зависит от**: 10B (MCP multi-transport), 10C (MCP approval), 11A

**Scope**:
1. MCP bridge: swarmline `McpBridge` → openai-agents MCP (5 транспортов)
2. Использовать openai-agents native MCP где доступен (Streamable HTTP, SSE, Stdio)
3. Approval policies bridge: swarmline → openai-agents approval
4. griffe tool schema: интеграция IDEA-016 с openai-agents `@function_tool` (reference impl)
5. Agent-as-tool bridge: swarmline `as_tool()` → openai-agents `agent.as_tool()`

**DoD**:
- [ ] Unit: MCP bridge, approval bridge, tool bridge — 10+ тестов
- [ ] Integration: MCP server через openai-agents transport — 3+ тестов

---

### Phase 11 — Сводка

| Sub-phase | Оценка | Зависимости |
|-----------|--------|------------|
| 11A: Base runtime | ~4-5 дней | 6C, 7B, 8A |
| 11B: Session bridge | ~2-3 дней | 8A, 11A |
| 11C: Output & guardrails | ~2-3 дней | 6A, 7B, 11A |
| 11D: MCP & advanced | ~3-4 дней | 10B, 10C, 11A |
| **Total Phase 11** | **~11-15 дней** | Phase 6-10 largely complete |

---

## Блокеры и риски

| Риск | Impact | Mitigation |
|------|--------|-----------|
| deepagents 0.5.0 не выходит на PyPI | Medium | Остаёмся на 0.4.11, portable path покрывает gaps |
| OpenTelemetry overhead в hot path | Low | NoopTracer по умолчанию, sampling |
| Pydantic schema ≠ LLM JSON Schema | Medium | Retry + relaxed validation mode |
| OAuth tokens revoked/changed | Low | Refresh flow + fallback на API key |
| Multi-agent deadlocks | High | Timeout + task lock + cycle detection |
| OpenAI Agents SDK pre-1.0 breaking changes | High | Adapter layer изолирует, pin version, integration tests |
| LiteLLM transitive deps bloat | Medium | Optional extra `swarmline[openai-agents]`, не в core |
| OpenAI tracing lock-in | Low | Custom TracingProcessor → наш Tracer, не используем openai traces |
