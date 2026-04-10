# Backlog

## Идеи

### IDEA-001: OAuth subscription auth (Claude Max / OpenAI Plus) (2026-03-17)

**Приоритет**: Medium
**Источник**: Исследование OpenClaw/Paperclip

Добавить поддержку OAuth-токенов от подписок (Claude Pro/Max, OpenAI Plus/Pro) как альтернативу API-ключам.

**Мотивация**: Пользователи с подпиской платят фиксированную сумму и не хотят платить ещё за API. OpenClaw (317K звёзд) уже использует этот подход через `claude setup-token`.

**Техническая суть**:
- Claude: OAuth PKCE через `claude.ai/oauth/authorize` → токен `sk-ant-oat01-...` → Bearer к `api.anthropic.com`
- OpenAI: OAuth через `auth.openai.com` (как Codex) → токен → Bearer к `api.openai.com`
- Оба — официальные, легальные flow

**Что нужно**:
1. Принимать OAuth-токен в RuntimeConfig (наряду с API-ключом)
2. Token refresh (Claude OAuth живёт 8 часов, есть refresh token)
3. Обновить AnthropicAdapter и OpenAICompatAdapter — передавать Bearer вместо API key
4. CLI/UI flow для получения токена (`cognitia auth login --provider claude`)

**Ограничения OAuth-пути**:
- Нет prompt caching (Claude)
- Нет 1M context window (Claude)
- Нет `service_tier` fast-mode (Claude)
- Structured outputs могут быть ограничены (OpenAI)

**Референсы**:
- OpenClaw: `claude setup-token` интеграция
- Paperclip: оркестрация агентов с OAuth
- `reports/2026-03-17_research_openai-agents-sdk.md`
- `notes/2026-03-17_ADR-001_openai-agents-sdk.md`

---

### IDEA-002: Extensible adapter registry (2026-03-17)

**Приоритет**: High
**Сложность**: Low
**Источник**: Paperclip adapter registry pattern

Сделать `RuntimeFactory` расширяемым реестром вместо жёсткого `if/elif`.

**Мотивация**: Сейчас добавление нового runtime требует правки `factory.py`. Сторонние разработчики не могут добавить свой runtime без форка. Paperclip решает это через pluggable registry с единым контрактом.

**Что нужно**:
1. `RuntimeFactory.register(name, factory_fn)` — регистрация runtime'а по имени
2. `RuntimeFactory.unregister(name)` — удаление
3. Entry points (`pyproject.toml [project.entry-points]`) для auto-discovery плагинов
4. Валидация: зарегистрированный runtime должен реализовать `AgentRuntime` Protocol
5. Встроенные runtime'ы (claude_sdk, deepagents, thin) регистрируются через тот же механизм

**DoD**: Сторонний пакет может сделать `pip install cognitia-my-runtime` и он автоматически доступен через `RuntimeConfig(runtime_name="my_runtime")`.

---

### IDEA-003: CLI agent runtime — subprocess + NDJSON (2026-03-17)

**Приоритет**: High
**Сложность**: Medium
**Источник**: Paperclip `claude_local` / `codex_local` адаптеры

Новый runtime, который запускает любой CLI-агент как subprocess и парсит NDJSON stdout.

**Мотивация**: Paperclip запускает Claude Code CLI (`claude --output-format stream-json`), Codex (`codex exec --json`), Gemini CLI как subprocess'ы. Это универсальнее SDK-интеграций:
- Не нужны Python-зависимости на каждый SDK
- CLI сам управляет auth (OAuth подписка работает из коробки)
- Любой CLI-агент подключается одинаково

**Что нужно**:
1. `CliAgentRuntime` реализует `AgentRuntime` Protocol
2. Конфигурация: `command`, `args`, `cwd`, `env`, `timeout`
3. Spawn subprocess → парсинг NDJSON stdout → нормализация в `RuntimeEvent`
4. Контракт: `invoke` / `status` / `cancel` (graceful SIGTERM → SIGKILL)
5. Preset'ы для Claude Code CLI, Codex, Gemini CLI

**Пример использования**:
```python
RuntimeConfig(
    runtime_name="cli",
    extra={"command": "claude", "args": ["--output-format", "stream-json"]}
)
```

---

### IDEA-004: Budget / cost tracking (2026-03-17)

**Приоритет**: High
**Сложность**: Medium
**Источник**: Paperclip per-agent budget с hard ceiling

Учёт токенов и стоимости per-agent с возможностью ограничения.

**Мотивация**: Paperclip считает стоимость каждого агента и автоматически паузит при превышении бюджета. В cognitia есть `max_iterations` и `max_tool_calls`, но нет учёта токенов и денег. Для production это must-have.

**Что нужно**:
1. `BudgetPolicy` dataclass: `max_input_tokens`, `max_output_tokens`, `max_cost_usd`, `action_on_exceed` (pause/error/warn)
2. `UsageTracker` — аккумулирует usage из `TurnMetrics` по сессии
3. Интеграция в `RuntimeConfig`: `budget: BudgetPolicy | None`
4. Pre-call check: если бюджет исчерпан → `RuntimeEvent.error(kind="budget_exceeded")`
5. Pricing table: модель → стоимость per 1K input/output tokens

---

### IDEA-005: Session persistence — resume across restarts (2026-03-17)

**Приоритет**: Medium
**Сложность**: Medium
**Источник**: Paperclip sessionId / previous_response_id chaining

Сохранение и восстановление сессий между перезапусками процесса.

**Мотивация**: Paperclip сохраняет `sessionId` (Claude Code) и `previous_response_id` (Codex) между heartbeat'ами, чтобы возобновлять разговор. В cognitia `InMemorySessionManager` теряет всё при перезапуске.

**Что нужно**:
1. `SessionBackend` Protocol: `save(key, state)` / `load(key)` / `delete(key)`
2. Реализации: `FileSessionBackend` (JSON/SQLite), опционально Redis
3. Сериализация `SessionState`: history, rolling_summary, session_id, turn_count
4. `SessionManager` принимает `backend` в конструкторе
5. Auto-resume: при `connect()` проверяет наличие сохранённой сессии

---

### IDEA-006: Multi-agent delegation (2026-03-17)

**Приоритет**: High
**Сложность**: High
**Источник**: Paperclip task delegation + OpenAI Agents SDK handoffs

Агент может делегировать подзадачу другому агенту (возможно на другой модели/runtime).

**Мотивация**: В Paperclip агент создаёт subtask и назначает другому агенту. В OpenAI Agents SDK — handoffs. В cognitia multi-agent отсутствует полностью. Это ключевая фича для сложных workflow: дешёвая модель для triage → дорогая для решения.

**Что нужно**:
1. `AgentOrchestrator` — координатор нескольких runtime'ов
2. `DelegationTool` — tool, который агент вызывает для делегирования (`delegate(agent_name, task)`)
3. Routing: какой агент получает подзадачу (по имени, по capability, автоматически)
4. Atomic task lock — защита от гонок при параллельных агентах
5. Result aggregation — сбор результатов от sub-agents
6. Бюджетирование: расходы sub-agent атрибутируются к parent task

**Зависимости**: IDEA-002 (extensible registry), IDEA-004 (budget tracking)

---

### IDEA-007: Scheduled / heartbeat agents (2026-03-17)

**Приоритет**: High
**Сложность**: Medium
**Источник**: Paperclip heartbeat scheduler с 4 типами триггеров

Агенты, которые просыпаются по расписанию, проверяют условия и действуют.

**Мотивация**: Paperclip будит агентов по таймеру, при назначении задачи, on-demand или по автоматизации. В cognitia агент работает только при явном вызове.

**Что нужно**:
1. `AgentScheduler`: cron/interval расписание для агента
2. Trigger types: timer, event (webhook), on-demand
3. Wakeup context: что изменилось с прошлого раза
4. Merge concurrent wakeups (как в Paperclip — не дублировать)

**Use cases**: мониторинг, CI/CD автоматизация, периодический code review, data pipeline checks.

---

### IDEA-008: Guardrails — input/output валидация (2026-03-17)

**Приоритет**: High
**Сложность**: Medium
**Источник**: OpenAI Agents SDK guardrails, общий паттерн safety layer

Автоматическая валидация входа и выхода агента. Tripwire механизм — блокирует опасный/невалидный ввод до того, как основная модель его обработает.

**Мотивация**: В cognitia валидация только на уровне `ToolPolicy` (какие tools разрешены). Нет проверки самого контента: jailbreak detection, content moderation, PII filtering, format validation. Для production это критично.

**Что нужно**:

1. `Guardrail` Protocol: `async (context, input) -> GuardrailResult(passed: bool, reason: str | None)`
2. `InputGuardrail` — проверка до LLM вызова (jailbreak, PII, off-topic)
3. `OutputGuardrail` — проверка после LLM ответа (hallucination, format, safety)
4. Tripwire: `tripwire_triggered=True` → прерывание с `RuntimeEvent.error(kind="guardrail_tripwire")`
5. Конфигурация per-agent: `RuntimeConfig(guardrails=[...])` или per-runtime
6. Параллельный запуск guardrails (не блокировать друг друга)
7. Быстрая/дешёвая модель для проверки (haiku/mini) — не тратить бюджет основной модели

---

### IDEA-009: Agent-as-tool — агент как инструмент другого агента (2026-03-17)

**Приоритет**: Medium
**Сложность**: Medium
**Источник**: OpenAI Agents SDK `agent.as_tool()`

Агент может быть вызван как tool другим агентом — без передачи управления (handoff), только вызов и возврат результата.

**Мотивация**: В cognitia tools — только MCP и local functions. Нет способа вызвать одного агента из другого как инструмент. Это проще чем полный multi-agent (IDEA-006) и покрывает основной use case: «спроси у специалиста и верни ответ».

**Что нужно**:

1. `AgentRuntime.as_tool(name, description) -> ToolSpec` — обернуть runtime в ToolSpec
2. Tool executor: при вызове запускает sub-agent с переданным input, возвращает текстовый результат
3. Изоляция: sub-agent не видит историю parent'а
4. Budget: расходы sub-agent учитываются в общем бюджете (IDEA-004)

**Зависимости**: IDEA-004 (budget tracking) — желательно, не обязательно

---

### IDEA-010: Session backends — pluggable persistent storage (2026-03-17)

**Приоритет**: High
**Сложность**: Medium
**Источник**: OpenAI Agents SDK (9 backends), Paperclip session persistence

Pluggable backends для хранения сессий: SQLite, Redis, PostgreSQL.

**Мотивация**: Сейчас только `InMemorySessionManager` — всё теряется при перезапуске. Для production нужна persistence. Перекликается с IDEA-005, но шире: не только resume, а полноценный storage layer.

**Что нужно**:

1. `SessionBackend` Protocol: `save(key, state)` / `load(key)` / `delete(key)` / `list()`
2. `SqliteSessionBackend` — файловый, zero-config, для dev/single-node
3. `RedisSessionBackend` (optional extra `cognitia[redis]`) — для distributed
4. `EncryptedSessionBackend` — overlay поверх любого backend (AES-256)
5. Сериализация: history, rolling_summary, session_id, turn_count, metadata
6. `SessionManager(backend=...)` — inject в конструктор

**Поглощает**: IDEA-005 (session persistence) — входит как подмножество

---

### IDEA-011: Structured output через Pydantic (2026-03-17)

**Приоритет**: Medium
**Сложность**: Low
**Источник**: OpenAI Agents SDK `Agent(output_type=MyModel)`

Гарантированный структурированный вывод, валидированный Pydantic моделью.

**Мотивация**: В cognitia есть `RuntimeConfig.output_format` (JSON Schema dict), но без Pydantic валидации. Пользователь получает сырой JSON и должен сам парсить/валидировать.

**Что нужно**:

1. `RuntimeConfig.output_type: type[BaseModel] | None` — Pydantic модель
2. Auto-генерация JSON Schema из Pydantic модели → передача в LLM
3. Post-validation: парсинг ответа LLM через `output_type.model_validate_json()`
4. Retry при невалидном ответе (до `max_model_retries`)
5. `RuntimeEvent.final(structured_output=parsed_model)` — типизированный результат

---

### IDEA-012: MCP approval policies — per-call approve/reject (2026-03-17)

**Приоритет**: Medium
**Сложность**: Low
**Источник**: OpenAI Agents SDK MCP approval policies

Per-tool политики "always"/"never" или callback для approve/reject MCP вызовов.

**Мотивация**: В cognitia есть `ToolPolicy` (allow/deny на уровне tool name), но нет per-call approval. Нельзя сказать «этот tool разрешён, но каждый вызов требует подтверждения пользователя».

**Что нужно**:

1. `ApprovalPolicy` enum: `always_allow`, `always_deny`, `require_approval`
2. Per-tool конфигурация в `ToolPolicy`: `{"mcp__server__tool": "require_approval"}`
3. При `require_approval` → `RuntimeEvent.approval_required(...)` → ожидание ответа
4. Интеграция с HITL: approval как частный случай human-in-the-loop

---

### IDEA-013: Pre-LLM input filter hook (2026-03-17)

**Приоритет**: Medium
**Сложность**: Low
**Источник**: OpenAI Agents SDK `call_model_input_filter` в RunConfig

Pre-LLM hook: трансформация input прямо перед вызовом модели.

**Мотивация**: В cognitia compaction работает на уровне истории (между turns), но нет per-call hook. Нельзя обрезать историю, добавить context, сделать prompt injection прямо перед конкретным LLM вызовом.

**Что нужно**:

1. `InputFilter` Protocol: `async (messages, system_prompt, config) -> (messages, system_prompt)`
2. `RuntimeConfig.input_filters: list[InputFilter]` — цепочка фильтров
3. Выполняется перед каждым LLM вызовом (после compaction, перед adapter.call)
4. Use cases: history trimming, RAG injection, dynamic system prompt, token budget enforcement

---

### IDEA-014: MCP multi-transport (2026-03-17)

**Приоритет**: Medium
**Сложность**: Medium
**Источник**: OpenAI Agents SDK (5 MCP транспортов)

Расширить `McpBridge` поддержкой нескольких MCP транспортов.

**Мотивация**: Сейчас один транспорт. OpenAI Agents SDK поддерживает 5: Streamable HTTP (рекомендуемый), SSE (legacy), Stdio (локальные процессы), Hosted (через инфраструктуру провайдера), Manager (unified). Streamable HTTP — основной для production.

**Что нужно**:

1. `McpTransport` Protocol: `connect()` / `call_tool()` / `list_tools()` / `disconnect()`
2. `StdioTransport` — stdin/stdout, для локальных MCP серверов
3. `StreamableHttpTransport` — HTTP с streaming, для remote серверов
4. `McpBridge(servers=[McpServer(transport="streamable_http", url=...)])` — per-server transport
5. Tool list caching (`cache_tools_list=True`)

---

### IDEA-015: Tracing — автоматический observability (2026-03-17)

**Приоритет**: Medium
**Сложность**: Medium
**Источник**: OpenAI Agents SDK built-in tracing, OpenTelemetry паттерн

Автоматический трейсинг всех LLM вызовов, tool calls, handoffs.

**Мотивация**: В cognitia только logging. Нет structured tracing для отладки, мониторинга и observability в production. OpenAI Agents SDK трейсит автоматически, но привязан к OpenAI Traces.

**Что нужно**:

1. `Tracer` Protocol: `start_span(name, attributes)` / `end_span()` / `add_event()`
2. Auto-instrumentation: каждый LLM call, tool call, guardrail check → span
3. Backends: `ConsoleTracer` (dev), `OpenTelemetryTracer` (production), `NoopTracer` (off)
4. `RuntimeConfig.tracer: Tracer | None`
5. НЕ привязывать к OpenAI Traces — vendor-neutral (OpenTelemetry)

---

### IDEA-016: Tool schema auto-generation из docstring (2026-03-17)

**Приоритет**: Medium
**Сложность**: Low
**Источник**: OpenAI Agents SDK `@function_tool` + griffe

Автогенерация JSON Schema для `ToolSpec` из Python function signature + docstring.

**Мотивация**: Сейчас `ToolSpec.parameters` пишется вручную как JSON Schema dict. OpenAI Agents SDK использует `griffe` для парсинга docstring и автогенерации schema из type hints.

**Что нужно**:

1. `@tool` декоратор: `def my_tool(query: str, limit: int = 10) -> str` → auto ToolSpec
2. Парсинг type hints → JSON Schema (str→string, int→integer, Optional→nullable)
3. Парсинг docstring (Google/NumPy style) → description для параметров
4. Без новых зависимостей: использовать `inspect` + `typing.get_type_hints` (griffe опционально)

---

### IDEA-017: RTK token optimization — toggleable proxy (2026-03-18)

**Приоритет**: Low
**Сложность**: Low
**Источник**: rtk-ai.app (Rust Token Killer)

Интеграция RTK как опционального оптимизатора токенов. RTK — CLI proxy на Rust, фильтрует boilerplate из вывода bash-команд (git diff 94%, pytest 96%). Детерминированная фильтрация, не LLM.

**Что нужно**:
1. `TokenOptimizer` Protocol: `optimize(command, output) -> optimized_output`
2. `RtkOptimizer` — subprocess wrapper (`shutil.which("rtk")`)
3. `RuntimeConfig.token_optimizer: TokenOptimizer | None` (disabled by default)
4. Env toggle: `COGNITIA_RTK_ENABLED=1`
5. Graceful fallback: RTK не установлен → warning + pass-through

---

### IDEA-018: Task Backlog System (2026-03-18)

**Приоритет**: High
**Сложность**: High
**Источник**: Paperclip issues system

Полная система задач для агентов: backlog, статусы, приоритеты, атомарный checkout, session per task.

**Мотивация**: Агенты должны работать с очередью задач — брать задачу, делать, проставлять статус, переходить к следующей. Как в Paperclip, но универсально.

**Что нужно**:
1. `TaskStore` — CRUD + фильтры + полнотекстовый поиск
2. Status machine: backlog → todo → in_progress → in_review → done/cancelled/blocked
3. `CheckoutEngine` — атомарный захват задачи (Paperclip pattern)
4. Priority: critical > high > medium > low
5. Task Session — persistent session per task
6. Дочерние задачи (parent_id)
7. Агент может создавать задачи (create_by_agent_id)

**Зависимости**: IDEA-010 (session backends)

---

### IDEA-019: Agent Hierarchy & Org Chart (2026-03-18)

**Приоритет**: High
**Сложность**: Medium-High
**Источник**: Paperclip agents.reportsTo + permissions + lifecycle

Иерархия агентов: org chart, lifecycle management, permissions, budget per agent. Один агент может создавать/управлять/останавливать других.

**Мотивация**: Для сложных workflow нужна структура: менеджер ставит задачи, инженеры выполняют. Внешние приложения должны мочь строить произвольные топологии.

**Что нужно**:
1. `AgentRegistry` — CRUD для агентов
2. `reports_to` — дерево через само-ссылку с cycle detection
3. `AgentPermissions` — can_create_agents, can_assign_tasks, etc.
4. Lifecycle: pending → idle → running → paused → terminated
5. Budget per agent (monthly limit)
6. Config versioning + rollback
7. Event hooks: on_created, on_status_changed, on_task_assigned

**Зависимости**: IDEA-004 (budget — optional). НЕ зависит от IDEA-018 (агенты существуют без задач)

---

### IDEA-020: Credential Proxy — secret isolation (2026-03-18)

**Приоритет**: Medium
**Сложность**: Low
**Источник**: NanoClaw credential-proxy.ts

Секреты никогда не попадают в runtime агента. Injector подставляет реальные credentials перед HTTP-вызовом.

**Что нужно**:
1. `CredentialInjector` Protocol
2. Placeholder key → real key injection
3. Multi-tenant: разные агенты → разные credentials
4. `RuntimeConfig.credential_injector`

---

### IDEA-021: Memory Scopes — global/agent/shared (2026-03-18)

**Приоритет**: Medium
**Сложность**: Low
**Источник**: NanoClaw three-tier memory hierarchy

Трёхуровневая иерархия памяти: global (все читают, orchestrator пишет), agent (изолированная), shared (группа).

**Что нужно**:
1. `MemoryScope` enum: global_, agent, shared
2. Namespace-based keys в SessionBackend
3. Enforcement: agent не пишет в чужой scope

**Зависимости**: IDEA-010 (session backends)

---

### IDEA-022: CallerPolicy — identity-based access control (2026-03-18)

**Приоритет**: Medium
**Сложность**: Low
**Источник**: NanoClaw sender allowlist

Allowlist/denylist по caller identity — первая линия защиты до content guardrails.

**Что нужно**:
1. `CallerPolicy` — allowlist/denylist по API key, user ID
2. Два режима: trigger (не активирует) и drop (молча дропает)
3. Per-agent overrides

**Зависимости**: IDEA-008 (guardrails — встраивается как pre-guardrail)

---

### IDEA-023: UI Event Projection — ready-to-render state from events (2026-03-18)

**Приоритет**: High
**Сложность**: Medium
**Источник**: UI Event Projection pattern (CQRS/Event Sourcing applied to agent UI)

Слой между RuntimeEvent stream и UI — projection собирает сырые события в готовое состояние для рендеринга. UI не парсит токены, tool calls, lifecycle — он получает `UIState` и просто рендерит.

**Мотивация**: Сейчас каждый frontend должен сам собирать UI state из RuntimeEvent'ов (парсить токены в текст, собирать tool results, отслеживать lifecycle). Это дублирование бизнес-логики агента в UI, невозможность replay/debug, сложность при смене event model.

**Что нужно**:
1. `EventProjection` Protocol: `apply(event) -> UIState`
2. `ChatProjection` builtin — собирает messages из event stream
3. `UIState` / `UIMessage` / `UIBlock` — typed state для UI
4. Streaming: `project_stream(events) -> AsyncIterator[UIState]`
5. Snapshot: сериализуемый state для fast reconnect
6. Replay: восстановление UI из сохранённых events
7. Custom projections: dashboard, analytics, debug

**Use cases**: Web (SSE/WS → React), Mobile, Debug console, Analytics, Multi-client streaming.

**Зависимости**: нет (работает поверх существующего RuntimeEvent)

---

### IDEA-024: Cancellation / Abort (2026-03-18)

**Приоритет**: High
**Сложность**: Low
**Источник**: Архитектурный review v3

`AgentRuntime.cancel()` + `CancellationToken`. Отмена для CLI → SIGTERM, SDK → cancel HTTP. `RuntimeEvent.error(kind="cancelled")`.

**Зависимости**: нет. Входит в Phase 6D.

---

### IDEA-025: AsyncContextManager for Agent/Runtime (2026-03-18)

**Приоритет**: High
**Сложность**: Low
**Источник**: Архитектурный review v3

`async with runtime:` и `async with Agent(...) as agent:` — cleanup on exit. Default `__aenter__`=noop, `__aexit__`=cleanup().

**Зависимости**: нет. Входит в Phase 6D.

---

### IDEA-026: Retry / Fallback Policy (2026-03-18)

**Приоритет**: High
**Сложность**: Medium
**Источник**: Архитектурный review v3

`RetryPolicy` Protocol: exponential backoff, jitter. `ModelFallbackChain`: rate limit → fallback model. `ProviderFallback`: provider down → другой.

**Что нужно**:
1. `RetryPolicy` Protocol: `should_retry(error, attempt) -> (bool, delay_seconds)`
2. `ExponentialBackoff` builtin: base=1s, max=60s, jitter=True
3. `ModelFallbackChain`: chain of models при rate limit
4. `ProviderFallback`: chain of providers при outage
5. `RuntimeConfig.retry_policy: RetryPolicy | None`
6. Events: `RuntimeEvent.warning(kind="retry", attempt=2)`

**Зависимости**: нет. Phase 7D.

---

### IDEA-027: Event Bus — universal callbacks (2026-03-18)

**Приоритет**: Medium
**Сложность**: Medium
**Источник**: Архитектурный review v3

`EventBus` Protocol: subscribe/emit. Universal callbacks для всех runtime (не только claude_sdk HookRegistry). Трейсинг строится поверх EventBus.

**Что нужно**:
1. `EventBus` Protocol: `subscribe(event_type, callback)` / `emit(event)`
2. Event types: llm_call_start/end, tool_call_start/end, error, final
3. Fire-and-forget callbacks (не блокируют)
4. Replaces claude_sdk-specific HookRegistry

**Зависимости**: нет. Phase 8B.

---

### IDEA-028: RAG / Retriever Protocol + Vector Store Connectors (2026-03-18)

**Приоритет**: **High** (upgraded 2026-03-30, confirmed by user)
**Сложность**: Low
**Источник**: Архитектурный review v3 (80% production agents use RAG)

`Retriever` Protocol + `RagInputFilter`. Только Protocol — пользователь приносит свой vector store.

**Что нужно**:
1. `Retriever` Protocol: `async retrieve(query, top_k) -> list[Document]`
2. `Document` dataclass: content, metadata, score
3. `RagInputFilter` — реализация InputFilter (7C): retrieve → inject context
4. НЕ включает vector store / embedding / chunking
5. Builtin example: `SimpleRetriever` (in-memory TF-IDF, для dev)

**Зависимости**: IDEA-013 (input filter). Phase 8D.

---

### IDEA-029: `swarmline create` CLI scaffolding (2026-03-18)

**Приоритет**: **High** (upgraded 2026-03-30, confirmed by user)
**Сложность**: Low
**Источник**: Архитектурный review v3 (Mastra/CrewAI имеют, у нас нет)

`cognitia init [project-name]` — генерирует minimal project (main.py, tools.py, config.py, .env.example).

**Зависимости**: нет. Phase 10G.

---

### IDEA-030: LiteLLM Adapter — 200+ providers (2026-03-18)

**Приоритет**: **High** (upgraded 2026-03-30, confirmed by user)
**Сложность**: Low
**Источник**: Архитектурный review v3

`LiteLLMAdapter` implements `LlmAdapter` — wrapper вокруг litellm.completion(). Optional extra: `cognitia[litellm]`. Fallback для exotic providers.

**Зависимости**: нет. Phase 10H.

---

### Review findings — Graph Agents + Knowledge Bank (2026-03-29)

**Источник**: Code review `.memory-bank/reports/2026-03-29_review_graph-agents-knowledge-bank.md`

**S3: Race condition в DefaultKnowledgeStore index при concurrent saves**
- Приоритет: Medium
- Файл: `memory_bank/knowledge_store.py:113-130`
- Два concurrent `save()` могут потерять index entry. Fix: in-memory кеш с asyncio.Lock или atomic read-modify-write.

**S4: InMemoryKnowledgeSearcher ломает инкапсуляцию через store._entries**
- Приоритет: Low
- Файл: `memory_bank/knowledge_inmemory.py:66`
- Добавить public итератор в InMemoryKnowledgeStore.

**W1: Лишний getattr для capabilities**
- Файл: `multi_agent/graph_context.py:150`
- `getattr(node, "capabilities", None)` → `node.capabilities`

**W2: time.strftime() без timezone в 5 модулях Knowledge Bank**
- Файлы: knowledge_store, knowledge_search, knowledge_inmemory, knowledge_consolidation
- Использовать `datetime.now(UTC).strftime()` для согласованных timestamps.

**W3: DRY — index JSON serialization дублируется**
- Файлы: `knowledge_store.py` + `knowledge_search.py`
- Вынести IndexEntry ↔ JSON в shared helper.

**W4: DRY — IndexEntry construction дублируется в InMemory**
- Файл: `knowledge_inmemory.py`
- 3 места строят IndexEntry из KnowledgeEntry одинаково.

**W5: DefaultKnowledgeStore.exists() читает весь файл**
- Файл: `knowledge_store.py:62-65`
- Для больших файлов wasteful. Альтернатива: проверять через list_files или добавить exists в MemoryBankProvider.

**W6: frontmatter.py не обрабатывает BOM и leading whitespace**
- Файл: `frontmatter.py:29`
- `text.startswith("---")` ломается с UTF-8 BOM.

**W7: Redundant exception types в wait_for_task**
- Файл: `graph_orchestrator.py:215`
- `except (TimeoutError, asyncio.CancelledError, Exception)` → `except Exception`.

---

---

### IDEA-031: Teachability — persistent learning via vector DB (2026-03-30)

**Приоритет**: Medium
**Сложность**: Medium
**Источник**: Competitive analysis (AutoGen)

Агент запоминает коррекции пользователя между сессиями. При поправке ("нет, я имел в виду X") сохраняет пару (ошибка → правильный ответ) как embedding в vector DB. При следующем разговоре ищет похожие ситуации и подгружает как контекст.

**Реализация**: Расширение FactStore + vector search. Мы уже имеем Procedural Memory (tool sequences), Teachability — следующий уровень: предпочтения пользователя + корректировки.

**Зависимости**: IDEA-028 (RAG/Vector stores)

---

### IDEA-032: Nested Chat — internal agent deliberation (2026-03-30)

**Приоритет**: Low
**Сложность**: Medium
**Источник**: Competitive analysis (AutoGen)

Агент может запускать внутренний диалог между другими агентами как "внутренний монолог". Main agent получает вопрос → запускает nested chat между researcher и critic → они спорят → main agent получает итоговый результат. Пользователь видит только финальный ответ.

**Реализация**: "Deliberation subgraph" как tool через Graph Agents.

---

### IDEA-033: Carryover / History Compression при delegation (2026-03-30)

**Приоритет**: Medium
**Сложность**: Low
**Источник**: Competitive analysis (AutoGen + OpenAI SDK `nest_handoff_history`)

При делегации задачи в Graph Agents — генерировать LLM-summary контекста вместо передачи полной истории. Экономит токены, убирает шум.

**Реализация**: При `delegate_task()` — опциональный `compress_history=True` → LLM summary предыдущих сообщений.

---

### IDEA-034: MCP HTTP Transport (2026-03-30)

**Приоритет**: Medium
**Сложность**: Low
**Источник**: Competitive analysis (OpenAI SDK — 5 транспортов vs наш 1)

Добавить HTTP Streamable transport для MCP. Позволит подключать удалённые MCP-серверы без subprocess (один httpx-клиент).

**Зависимости**: нет

---

### IDEA-035: Tool Guardrails — modify result (2026-03-30)

**Приоритет**: Medium
**Сложность**: Low
**Источник**: Competitive analysis (OpenAI SDK)

Расширить PostToolUse hook contract чтобы мог возвращать `modified_result`. Сейчас hooks могут только наблюдать результат, но не заменять его.

**Зависимости**: нет

---

### IDEA-036: Composable ToolPolicy chain (2026-03-30)

**Приоритет**: High
**Сложность**: Medium
**Источник**: Competitive analysis (Claude SDK — 5-step permission eval chain)

Сделать ToolPolicy composable — цепочка из нескольких policy layers, каждый может allow/deny/pass-through. Порядок: Hooks → DenyList → PolicyMode → AllowList → AppCallback. Deny всегда побеждает.

**Зависимости**: нет

---

### IDEA-037: Extended HookRegistry — 8+ events (2026-03-30)

**Приоритет**: Medium
**Сложность**: Low
**Источник**: Competitive analysis (Claude SDK — 12+ hooks vs наши 4)

Добавить lifecycle hooks: SubagentStart, SubagentStop, PreCompact, PermissionRequest. Расширяет HookRegistry без breaking changes.

**Зависимости**: нет

---

### IDEA-038: Session Fork/Resume (2026-03-30)

**Приоритет**: Low
**Сложность**: Medium
**Источник**: Competitive analysis (Claude SDK)

`SessionManager.fork(session_id) -> new_session_id` — копирует историю, продолжает с нового состояния. Для A/B exploration и pipeline "what if".

**Зависимости**: нет

---

### IDEA-039: OpenAPI Plugin Import (2026-03-30)

**Приоритет**: Medium
**Сложность**: Medium
**Источник**: Competitive analysis (Semantic Kernel)

`OpenApiToolLoader("https://api.example.com/openapi.json")` → list[ToolSpec]. Parse OpenAPI spec, каждый endpoint → ToolSpec с JSON Schema, executor через httpx.

**Зависимости**: нет

---

### IDEA-040: Named Orchestration Pattern Shortcuts (2026-03-30)

**Приоритет**: Medium
**Сложность**: Low
**Источник**: Competitive analysis (Semantic Kernel)

Фабричные функции поверх Graph Agents: `swarmline.sequential([a, b])`, `swarmline.parallel([agents])`, `swarmline.hierarchy(lead, workers)`, `swarmline.mixture([experts], aggregator=synth)`. Не замена, а shortcut поверх Graph API.

**Зависимости**: нет

---

### IDEA-041: Prompt Render Filter (2026-03-30)

**Приоритет**: Low
**Сложность**: Low
**Источник**: Competitive analysis (Semantic Kernel)

Middleware между ContextBuilder и LLM call. Перехватывает собранный prompt после assembly, до отправки. Для dynamic RAG injection, PII redaction, semantic caching.

**Зависимости**: нет

---

### IDEA-042: Graph.from_dsl() — string syntax (2026-03-30)

**Приоритет**: Low
**Сложность**: Low
**Источник**: Competitive analysis (Swarms — AgentRearrange)

`Graph.from_dsl("lead -> [researcher, coder] -> reviewer")` — компактный строковый синтаксис для описания agent flow. Тривиальный парсер, большой выигрыш в DX для простых случаев.

**Зависимости**: нет

---

### IDEA-043: Monitor Microsoft Agent Framework GA (2026-03-30)

**Приоритет**: Medium (tracking)
**Сложность**: N/A
**Источник**: Competitive analysis (AutoGen + Semantic Kernel → Agent Framework)

Microsoft Agent Framework = AutoGen + Semantic Kernel merger. GA target Q1 2026. Обе компоненты в maintenance mode. Agent Framework — потенциальный крупный конкурент с enterprise backing.

**Действие**: отслеживать API, архитектуру, adoption после GA. Пересмотреть позиционирование.

---

## Priority updates from competitive analysis (2026-03-30)

- **IDEA-028** (RAG/Vector stores): Low → **High** (confirmed by user)
- **IDEA-029** (CLI scaffolding): Medium → **High** (confirmed by user)
- **IDEA-030** (LiteLLM adapter): Low → **High** (confirmed by user)

---

## ADR

- **ADR-001**: OpenAI Agents SDK — REJECTED (пересмотреть после v1.0). См. `notes/2026-03-17_ADR-001_openai-agents-sdk.md`

## Отклонённое

- **Graph/Flow Visualization** (2026-03-30): Использовать внешние решения вместо built-in. Источник: competitive analysis.
- **Enterprise SaaS / Hosted Platform** (2026-03-30): Только документация + community сайт. Источник: user decision.
