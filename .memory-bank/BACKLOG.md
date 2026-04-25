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
4. CLI/UI flow для получения токена (`swarmline auth login --provider claude`)

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

**DoD**: Сторонний пакет может сделать `pip install swarmline-my-runtime` и он автоматически доступен через `RuntimeConfig(runtime_name="my_runtime")`.

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

**Мотивация**: Paperclip считает стоимость каждого агента и автоматически паузит при превышении бюджета. В swarmline есть `max_iterations` и `max_tool_calls`, но нет учёта токенов и денег. Для production это must-have.

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

**Мотивация**: Paperclip сохраняет `sessionId` (Claude Code) и `previous_response_id` (Codex) между heartbeat'ами, чтобы возобновлять разговор. В swarmline `InMemorySessionManager` теряет всё при перезапуске.

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

**Мотивация**: В Paperclip агент создаёт subtask и назначает другому агенту. В OpenAI Agents SDK — handoffs. В swarmline multi-agent отсутствует полностью. Это ключевая фича для сложных workflow: дешёвая модель для triage → дорогая для решения.

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

**Мотивация**: Paperclip будит агентов по таймеру, при назначении задачи, on-demand или по автоматизации. В swarmline агент работает только при явном вызове.

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

**Мотивация**: В swarmline валидация только на уровне `ToolPolicy` (какие tools разрешены). Нет проверки самого контента: jailbreak detection, content moderation, PII filtering, format validation. Для production это критично.

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

**Мотивация**: В swarmline tools — только MCP и local functions. Нет способа вызвать одного агента из другого как инструмент. Это проще чем полный multi-agent (IDEA-006) и покрывает основной use case: «спроси у специалиста и верни ответ».

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
3. `RedisSessionBackend` (optional extra `swarmline[redis]`) — для distributed
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

**Мотивация**: В swarmline есть `RuntimeConfig.output_format` (JSON Schema dict), но без Pydantic валидации. Пользователь получает сырой JSON и должен сам парсить/валидировать.

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

**Мотивация**: В swarmline есть `ToolPolicy` (allow/deny на уровне tool name), но нет per-call approval. Нельзя сказать «этот tool разрешён, но каждый вызов требует подтверждения пользователя».

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

**Мотивация**: В swarmline compaction работает на уровне истории (между turns), но нет per-call hook. Нельзя обрезать историю, добавить context, сделать prompt injection прямо перед конкретным LLM вызовом.

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

**Мотивация**: В swarmline только logging. Нет structured tracing для отладки, мониторинга и observability в production. OpenAI Agents SDK трейсит автоматически, но привязан к OpenAI Traces.

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
4. Env toggle: `SWARMLINE_RTK_ENABLED=1`
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

`swarmline init [project-name]` — генерирует minimal project (main.py, tools.py, config.py, .env.example).

**Зависимости**: нет. Phase 10G.

---

### IDEA-030: LiteLLM Adapter — 200+ providers (2026-03-18)

**Приоритет**: **High** (upgraded 2026-03-30, confirmed by user)
**Сложность**: Low
**Источник**: Архитектурный review v3

`LiteLLMAdapter` implements `LlmAdapter` — wrapper вокруг litellm.completion(). Optional extra: `swarmline[litellm]`. Fallback для exotic providers.

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

### IDEA-044: Conversation Compaction — LLM-суммаризация при сжатии контекста (2026-04-13)

**Приоритет**: High
**Сложность**: Medium
**Источник**: Claude Code parity gap analysis

Вместо обрезки старых сообщений — суммаризация через LLM перед удалением.

**Мотивация**: `MaxTokensFilter` просто отбрасывает старые сообщения. Claude Code при приближении к лимиту контекста вызывает LLM для суммаризации ранних сообщений, сохраняя ключевые решения и факты. Без compaction длинные coding-сессии теряют контекст о принятых решениях.

**Что нужно**:
1. `CompactionStrategy` Protocol: `async compact(messages, budget_tokens) → list[Message]`
2. `LlmCompactionStrategy` — вызывает LLM (дешёвую модель) для суммаризации обрезаемых сообщений
3. Summary вставляется как system message в начало оставшейся истории
4. Интеграция в ThinRuntime: вызов compaction перед LLM call когда `len(messages) * avg_tokens > budget`
5. Конфигурация: `RuntimeConfig.compaction_strategy: CompactionStrategy | None`

**Отличие от MaxTokensFilter**: MaxTokensFilter = truncation (потеря), Compaction = summarization (сохранение смысла).

---

### IDEA-045: Project Instructions Loading — автозагрузка CLAUDE.md (2026-04-13)

**Приоритет**: High
**Сложность**: Low
**Источник**: Claude Code parity gap analysis

Автоматическое чтение project instruction files и инжект в system prompt.

**Мотивация**: Claude Code автоматически загружает `CLAUDE.md` из корня проекта, родительских директорий и `~/.claude/`. Это позволяет кастомизировать поведение агента под проект без кода. ThinRuntime сейчас `supports_project_instructions: False`.

**Что нужно**:
1. `ProjectInstructionsLoader` — сканирует cwd → parent dirs → home для instruction files
2. Поддержка нескольких форматов (multi-agent universal):
   - `CLAUDE.md` — Claude Code формат
   - `AGENTS.md` — OpenAI Codex / Agents формат
   - `GEMINI.md` — Google Gemini CLI формат
   - `RULES.md` — swarmline-native формат
   - Кастомный файл через конфигурацию
3. Приоритет загрузки: `RULES.md` > `CLAUDE.md` > `AGENTS.md` > `GEMINI.md` (первый найденный в директории)
4. Мерж стратегия: home (lowest) → parent dirs → project root (highest priority)
5. Инжект в system prompt через `SystemPromptInjector` (уже есть)
6. Hot reload: при изменении файла — обновить prompt (опционально)
7. `RuntimeConfig.instructions_files: list[str] | None` — override списка файлов для поиска
8. `RuntimeConfig.instructions_dir: Path | None` — override директории поиска

**Универсальность**: один и тот же проект может использовать swarmline + Claude Code + Codex. Каждый агент читает свой файл, но `ProjectInstructionsLoader` понимает все форматы.

---

### IDEA-046: Session Resume — продолжение разговора между run() вызовами (2026-04-13)

**Приоритет**: High
**Сложность**: Medium
**Источник**: Claude Code parity gap analysis

Сохранение и восстановление conversation state между вызовами `run()`.

**Мотивация**: Claude Code сохраняет полную историю и может продолжить с места остановки. ThinRuntime stateless — каждый `run()` начинается с пустой истории. Для coding agent это критично: пользователь хочет продолжить работу после перерыва.

**Что нужно**:
1. Интеграция с `MessageStore` / `SessionStateStore` (уже есть в swarmline)
2. `ThinRuntime.run(session_id="abc")` → загрузка истории из store перед LLM call
3. Auto-save: после каждого turn сохранять messages в store
4. Resume: при повторном `run(session_id="abc")` — продолжение с сохранённой историей
5. Compaction-aware: при resume применять compaction к восстановленной истории (IDEA-044)

**Поглощает**: IDEA-005 (session persistence) — расширяет и конкретизирует для ThinRuntime.

---

### IDEA-047: Web Tools — встроенные WebSearch и WebFetch (2026-04-13)

**Приоритет**: High
**Сложность**: Low
**Источник**: Claude Code parity gap analysis

Подключение web-инструментов как built-in tools в ThinRuntime.

**Мотивация**: Claude Code имеет `WebSearch` и `WebFetch` как стандартные инструменты. В swarmline вся инфраструктура есть (`web_httpx.py`, провайдеры Tavily/Brave/Jina), но не подключена к ThinRuntime. Разработчику нужно вручную создавать `local_tools`.

**Что нужно**:
1. `create_web_tools(provider) → dict[str, Callable]` — фабрика для web search + fetch
2. `WebSearchTool` ToolSpec: `query: str, max_results: int` → JSON результаты
3. `WebFetchTool` ToolSpec: `url: str` → markdown content
4. Регистрация в coding tool pack как опциональные (не в CODING_TOOL_NAMES по умолчанию)
5. Конфигурация провайдера: `CodingProfileConfig.web_provider: str | None`

---

### IDEA-048: Multimodal Input — изображения, PDF, Jupyter notebooks (2026-04-13)

**Приоритет**: Medium
**Сложность**: High
**Источник**: Claude Code parity gap analysis

Поддержка мультимодального input (не только текст) в ThinRuntime.

**Мотивация**: Claude Code может читать изображения (PNG/JPG), PDF файлы (с пагинацией), Jupyter notebooks. ThinRuntime's `Message.content` — только `str`. Для coding agent это важно: скриншоты UI, PDF спецификации, анализ notebook'ов.

**Что нужно**:
1. Расширить `Message.content` до `str | list[ContentBlock]` (text, image, file)
2. `ContentBlock` union: `TextBlock(text)`, `ImageBlock(media_type, data_b64)`, `FileBlock(path, parsed_text)`
3. Provider-specific конвертация: Anthropic vision blocks, OpenAI image_url, Google inline_data
4. `read` tool: при чтении .png/.jpg → ImageBlock, .pdf → TextBlock с extracted text, .ipynb → TextBlock с cells
5. Lazy loading: изображения конвертируются в base64 только при отправке LLM

---

### IDEA-049: MCP Resource Reading — чтение MCP ресурсов (2026-04-13)

**Приоритет**: Medium
**Сложность**: Low
**Источник**: Claude Code parity gap analysis

Расширение MCP интеграции для чтения resources (не только tools).

**Мотивация**: MCP Protocol определяет два типа взаимодействия: tools (вызов функций) и resources (чтение данных). ThinRuntime поддерживает только tools. Claude Code может читать MCP resources через `ReadMcpResource`.

**Что нужно**:
1. Расширить `McpClient`: `list_resources()`, `read_resource(uri)` 
2. `ReadMcpResourceTool` ToolSpec: `server: str, uri: str` → content
3. Resource discovery: при подключении MCP сервера — запрос `resources/list`
4. Кэширование: resource list кэшируется, content — нет (может меняться)

---

### IDEA-050: System Reminders — динамические контекстные подсказки (2026-04-13)

**Приоритет**: Medium
**Сложность**: Medium
**Источник**: Claude Code parity gap analysis

Адаптивные system reminder блоки, инжектируемые в контекст по условиям.

**Мотивация**: Claude Code вставляет `<system-reminder>` блоки с контекстной информацией: доступные инструменты, текущие задачи, напоминания. Они появляются и исчезают в зависимости от состояния. ThinRuntime имеет статичный system prompt.

**Что нужно**:
1. `SystemReminder` dataclass: `condition: Callable[[RunContext], bool]`, `content: str`, `priority: int`
2. `SystemReminderManager`: коллекция reminders, `assemble(context) → str` — собирает активные
3. Conditional triggers: "если agent давно не использовал tasks", "если budget > 80%", "если ошибка в предыдущем tool call"
4. Интеграция: reminder text добавляется в system prompt перед каждым LLM call
5. Бюджет: reminders не должны занимать > N% от context window

---

### IDEA-051: Git Worktree Isolation для субагентов (2026-04-13)

**Приоритет**: Medium
**Сложность**: Medium
**Источник**: Claude Code parity gap analysis

Запуск субагентов в изолированных git worktree.

**Мотивация**: Claude Code может спавнить агентов в отдельных git worktree — каждый работает со своей копией репозитория, параллельные агенты не конфликтуют. ThinRuntime субагенты работают в одном sandbox.

**Что нужно**:
1. `WorktreeIsolation` — создание tmp git worktree (`git worktree add`)
2. Интеграция в `ThinSubagentOrchestrator`: опция `isolation="worktree"` в SubagentSpec
3. При спавне: создать worktree → переключить cwd субагента → cleanup после завершения
4. Auto-cleanup: удаление worktree после `wait()` (или при cancel)
5. Merge-back: опциональный автомерж изменений из worktree в основную ветку

---

### IDEA-052: Thinking Events — отдельный поток reasoning (2026-04-13)

**Приоритет**: Low
**Сложность**: Low
**Источник**: Claude Code parity gap analysis

Парсинг `<thinking>` блоков как отдельного типа событий.

**Мотивация**: Claude модели поддерживают extended thinking. Claude Code показывает thinking как отдельный сворачиваемый блок. ThinRuntime парсит всё как единый `assistant_delta` — thinking и ответ смешиваются.

**Что нужно**:
1. Парсинг `<thinking>...</thinking>` блоков из LLM ответа
2. Новый тип: `RuntimeEvent(type="thinking", text="...")` 
3. Антропик SDK: парсинг `thinking` content blocks из API response
4. Конфигурация: `RuntimeConfig.emit_thinking: bool = False` (opt-in)

---

### IDEA-053: Background Agents и Monitor Tool (2026-04-13)

**Приоритет**: Low
**Сложность**: Medium
**Источник**: Claude Code parity gap analysis

Запуск агентов в фоне с уведомлениями и мониторинг stdout процессов.

**Мотивация**: Claude Code запускает агентов в background (`run_in_background: true`) и уведомляет при завершении. Также имеет `Monitor` tool для streaming stdout от background процессов. ThinRuntime subagents блокирующие — `wait()` ждёт завершения.

**Что нужно**:
1. `spawn()` возвращает `agent_id` (уже есть) + event notification при завершении
2. `RuntimeEvent(type="background_complete", agent_id, result)` — уведомление
3. `MonitorTool` ToolSpec: `pid: int` → async streaming stdout/stderr
4. `bash` tool: опция `run_in_background: bool` → запуск без ожидания

**Связано с**: IDEA-024 (Cancellation/Abort) — уже реализовано.

---

## ADR

- **ADR-001**: OpenAI Agents SDK — REJECTED (пересмотреть после v1.0). См. `notes/2026-03-17_ADR-001_openai-agents-sdk.md`


### ADR-002 — Use roadmap.md as canonical Memory Bank entrypoint with plan.md backwards-compat symlink [2026-04-25]

**Context:** Skill memory-bank v3.x использует `roadmap.md` (lowercase) как canonical имя для активного плана и приоритетов проекта. Свarmline исторически использует `plan.md` (старая convention). При вызове `mb-plan-sync.sh` скрипт падает с `[error] roadmap.md not found`. У пользователя `plan.md` упоминается во множестве ссылок: `~/.claude/CLAUDE.md`, project `RULES.md`, `.memory-bank/RULES.md`, существующие plans/notes.

**Options:**
- **A: Переименовать `plan.md` → `roadmap.md`** — pros: canonical name; cons: ломает все существующие ссылки в CLAUDE.md/RULES.md/notes; невозможно сделать без массового rename'а (≥30 мест)
- **B: Оставить `plan.md`, симлинк `roadmap.md → plan.md`** — pros: zero break, обратная совместимость, обратимо в одну команду; cons: имя `plan.md` остаётся "primary" в commit'ах
- **C: Patch `mb-plan-sync.sh` для fallback на `plan.md`** — pros: чистое исправление в коде; cons: требует менять глобальный skill, расходится с upstream
- **D: Hybrid — сейчас вариант B (симлинк), при следующем `/mb upgrade` миграция вариант A (rename + reverse symlink `plan.md → roadmap.md`)** — pros: zero break сейчас, постепенный переход на canonical; cons: 2 шага вместо 1

**Decision:** **D — Hybrid, две фазы**.

Фаза 1 (сейчас, 2026-04-25): создан симлинк `.memory-bank/roadmap.md → plan.md` (и `status.md → STATUS.md` если case-sensitive FS — на macOS APFS не нужен из-за case-insensitivity). Это разблокировало `mb-plan-sync.sh`.

Фаза 2 (при следующем `/mb upgrade`): автоматическая миграция через расширенный `mb-migrate-structure.sh` или новый шаг в `mb-upgrade.sh`:
1. `mv .memory-bank/plan.md .memory-bank/roadmap.md` (canonical name становится roadmap.md)
2. `ln -sf roadmap.md .memory-bank/plan.md` (reverse symlink — старые ссылки `plan.md` продолжают работать)
3. Обновить ссылки в `~/.claude/CLAUDE.md`, project `RULES.md`, `.memory-bank/RULES.md` через sed-replace на `roadmap.md`
4. Idempotent: повторный запуск не делает ничего

**Rationale:**
- Variant D = zero downtime, постепенный переход.
- Variant A сейчас сломал бы все существующие команды и notes, ссылающиеся на `plan.md`.
- Variant B сам по себе оставляет неправильный canonical name — нежелательно для долгосрочной поддержки.
- Variant C потребовал бы патчить и поддерживать отдельную форк-версию skill.
- Symlink в Memory Bank — privacy-safe (фильтруется при `sync-public.sh`).

**Consequences:**
- Сейчас: `mb-plan-sync.sh` работает; canonical имя в файловой системе — `plan.md`; `roadmap.md` — alias.
- В будущем: после `/mb upgrade` (требует patch) — canonical имя будет `roadmap.md`; `plan.md` — legacy alias через симлинк. Все скрипты skill уже ожидают `roadmap.md`.
- Связанные artifact: `I-001` (idea для патча skill), notes/2026-04-25_roadmap-vs-plan-md-decision.md (документация для будущих сессий).
- Обратная совместимость гарантируется на ВСЕХ этапах: ни одна ссылка `plan.md` или `roadmap.md` не сломается.


### ADR-003 — Use ty in strict mode as sole type checker (no mypy) [2026-04-25]

**Context:** Project ранее использовал **2 type checkers** одновременно: `mypy` (lenient defaults — 4 errors) и `ty` (strict mode `respect-type-ignore-comments=false`, `error-on-warning=true` — 75 errors). Это создаёт drift между tool'ами: код, проходящий mypy, фейлит ty и наоборот. CI gate отсутствовал — регрессии типизации проходили незамеченными до релиза. Sprint 1A решает эту разрозненность.

**Options:**
- **A: mypy only** — pros: mature ecosystem, известный pattern; cons: lenient defaults пропускают real bugs (audit показал 11 потенциальных runtime crashes); не находит class problems типа `__name__` на `partial` callable union
- **B: ty only, strict mode** — pros: faster (Rust-based), strict by default, обнаруживает 75 vs 4 errors, official astral.sh tool, активно развивается; cons: новый (v0.0.x), API may shift, smaller ecosystem
- **C: Both with sync** — pros: cross-validation; cons: high maintenance, конфигурации drift'уют, double CI time, конфликты между ними

**Decision:** **B — ty only, strict mode**.

**Rationale:**
- ty обнаружил 11 critical потенциальных runtime crashes (`coding_task_runtime` calling missing methods, `project_instruction_filter` tuple type bug, `agent_registry_postgres` rowcount on abstract Result, decorator pattern unresolved attrs, partial callable `__name__` access). Эти ошибки невидимы для mypy в lenient mode.
- ruff + ty — оба от astral.sh, целостный Rust-based toolchain, синхронные релизы, унифицированный конфиг paradigm.
- 75 errors при первом запуске — высокая первоначальная боль, но **тип-системные ошибки не появляются если их сразу не пропускать** (Sprint 1A + 1B их закрывают).
- Альтернатива (B+C) — поддерживать 2 конфигурации, удваивая maintenance cost без proportional value.

**Consequences:**
- ✅ **Sprint 1A** (этот): infrastructure (CI gate via `tests/architecture/test_ty_strict_mode.py`) + 11 critical fixes → 75 → 62 (-13 cumulative)
- ✅ **Sprint 1B**: bulk применение 3 канонических паттернов (OptDep / DecoratedTool / CallableUnion — см. `notes/2026-04-25_ty-strict-decisions.md`) к ~62 оставшимся ошибкам в ~35 файлах
- ✅ `.pipeline.yaml` — удалён `typecheck_mypy` ключ (canonical = `typecheck: ty check src/swarmline/`)
- ✅ `.github/workflows/ci.yml` — новый job `typecheck` запускает `ty check` на каждый PR, fail-on-error
- ✅ Все `# type: ignore[attr-defined]` где возможно — заменены на typed `cast(...)`; новые добавляются ТОЛЬКО для опциональных deps (`# type: ignore[unresolved-import]  # optional dep`) с обязательным reason-комментарием
- 🔁 **Reversibility:** если ty в будущем deprecated или конфликтует с major Python version — миграция обратно на mypy = 1-2 недели работы (CI step + конфиг)
- 📌 **Tracking:** меньшее число type-checkers = меньше CI minutes, faster local dev cycle (~10x)

**Related artifacts:**
- `tests/architecture/test_ty_strict_mode.py` (CI gate + baseline tracking)
- `tests/architecture/ty_baseline.txt` (current: 62, target after Sprint 1B: 0)
- `notes/2026-04-25_ty-strict-decisions.md` (3 reusable patterns)
- `plans/2026-04-25_feature_production-v2-phase-01a-ty-strict-foundation.md` (this Sprint)
- `plans/2026-04-25_feature_production-v2-phase-01b-ty-bulk-cleanup.md` (next Sprint)

## Отклонённое

- **Graph/Flow Visualization** (2026-03-30): Использовать внешние решения вместо built-in. Источник: competitive analysis.
- **Enterprise SaaS / Hosted Platform** (2026-03-30): Только документация + community сайт. Источник: user decision.

## Ideas

### I-001 — Auto-migrate plan.md to roadmap.md on next /mb upgrade with reverse symlink [HIGH, NEW, 2026-04-25]

**Source:** ADR-002 (Hybrid migration plan, Phase 2).

**What:** Patch `~/.claude/skills/memory-bank/scripts/mb-migrate-structure.sh` (or `mb-upgrade.sh`) so that on next `/mb upgrade` it performs idempotent migration:

```bash
# Detect: plan.md is regular file AND roadmap.md is symlink → plan.md
if [[ -f .memory-bank/plan.md && -L .memory-bank/roadmap.md && "$(readlink .memory-bank/roadmap.md)" == "plan.md" ]]; then
    # Phase 2 migration:
    cp .memory-bank/plan.md .memory-bank/roadmap.md.tmp        # write through symlink target (=plan.md) — actually breaks
    # Better: remove symlink first, then rename, then create reverse
    rm .memory-bank/roadmap.md
    mv .memory-bank/plan.md .memory-bank/roadmap.md
    ln -s roadmap.md .memory-bank/plan.md
    # Update references
    sed -i.bak 's|\.memory-bank/plan\.md|\.memory-bank/roadmap.md|g' \
        ~/.claude/CLAUDE.md \
        ./RULES.md \
        ./.memory-bank/RULES.md 2>/dev/null || true
    echo "[migrate] plan.md → roadmap.md, reverse symlink installed"
fi
```

**Why HIGH:** Без этого patch'а каждый новый проект будет страдать от той же проблемы. Это user-facing concern для всех, кто использует skill memory-bank на legacy `plan.md` setup.

**Acceptance criteria:**
- [ ] Скрипт идемпотентен (повторный запуск = no-op)
- [ ] Все ссылки `plan.md` в CLAUDE.md / RULES.md заменены на `roadmap.md`
- [ ] Симлинк `plan.md → roadmap.md` создан как backwards-compat alias
- [ ] `mb-plan-sync.sh` продолжает работать после миграции
- [ ] Все существующие notes/plans с `[plan.md](plan.md)` ссылками продолжают резолвиться (через симлинк)
- [ ] Migration logged в progress.md

**Plan:** *(не создан, ждёт promotion через `/mb idea-promote I-001 refactor`)*
