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

### IDEA-054: Handoff as primitive с HandoffInputFilter (2026-05-05)

**Приоритет**: High
**Сложность**: Medium
**Источник**: openai-agents-python (`src/agents/handoffs/`) — сравнение архитектур

Добавить first-class handoff-примитив с фильтрацией истории при передаче контроля между агентами.

**Мотивация**: У swarmline богатый `multi_agent/` (graph_orchestrator, persistent_graph, governance, agent_registry), но именно «handoff с переписыванием/обрезкой conversation history» как стандартный примитив отсутствует. agents-sdk имеет `Handoff`, `HandoffInputData`, `HandoffInputFilter`, `default_handoff_history_mapper`, `nest_handoff_history` — следующий агент видит не raw history, а отфильтрованный/трансформированный контекст. Полезно для приватности (один агент не должен видеть креды другого), снижения токенов и аудита передач.

**Что нужно**:
1. `Handoff` dataclass: target agent + optional `input_filter` callable + optional `on_handoff` hook
2. `HandoffInputData(input_history, pre_handoff_items, new_items, run_context, input_items)` — что передаётся фильтру
3. `HandoffInputFilter` Protocol: `(data: HandoffInputData) -> HandoffInputData`
4. Defaults: `default_handoff_history_mapper` (всё видно), `nest_handoff_history` (вложенная история как одно сообщение)
5. Интеграция в `multi_agent/graph_communication` и `a2a` — handoff поверх существующих message-channels
6. Span `handoff_span` в observability/tracer для аудита

**Тесты**: filter не пропускает PII; nested handoffs работают; tripwire через filter возвращающий error.

**Связано с**: IDEA-055 (RunState recovery) — handoff-то как точка восстановления.

---

### IDEA-055: RunState + RunErrorHandler — mid-run recovery (2026-05-05)

**Приоритет**: High
**Сложность**: High
**Источник**: openai-agents-python (`src/agents/run_state.py`, `run_error_handlers.py`)

Сериализуемый `RunState` + хуки восстановления после ошибок прямо посреди выполнения, не только на границах сессии.

**Мотивация**: У swarmline есть `session/session_resumption.py`, но это resumption на уровне session. agents-sdk даёт `RunState` (snapshot in-flight run) + `RunErrorHandler` который вызывается при ошибке на N-ом turn и решает: retry / fallback / handoff / abort. Критично для долгих агентов с дорогим контекстом — упало на 12-м turn → не начинать с нуля.

**Что нужно**:
1. `RunState` dataclass — frozen snapshot: turn_count, history, tool_calls, current_agent, accumulated_output, run_config_hash
2. `RunState.serialize()` / `RunState.deserialize()` — JSON-serialization для persistence
3. `RunErrorHandler` Protocol: `(error, state) -> RunErrorHandlerResult` (`retry` / `fallback_to_agent(...)` / `abort` / `transform_error`)
4. `RunErrorHandlers` collection — chain handlers по типу ошибки (`MaxTurnsExceeded` → retry, `ModelRefusalError` → fallback)
5. Integration: thin runtime emits `state_snapshot` event, persistable в `runtime/portable_memory.py`
6. `runner.resume(state)` — продолжить с конкретного RunState

**DoD**: тесты на kill -9 после 5 turn → restart продолжает с 6; ModelBehaviorError → handler меняет model → retry; chain handlers порядок гарантирован.

**Связано с**: session/session_resumption (уровень сессии vs run), resilience/circuit_breaker (стратегии fallback).

---

### IDEA-056: Sandbox Manifest + Snapshots — declarative workspaces (2026-05-05)

**Приоритет**: High
**Сложность**: High
**Источник**: openai-agents-python `sandbox/` (v0.14, новинка)

Декларативное описание workspace через Manifest + capabilities + Local/Remote snapshots для долгих агентов.

**Мотивация**: У swarmline есть `multi_agent/worktree_orchestrator` и `tools/sandbox`, но manifest-based composable workspace с snapshots — уровень выше. agents-sdk:
```python
Manifest(entries={
    "repo": GitRepo("openai/x", ref="main"),
    "data": LocalFile(path="/tmp/data.json"),
    "mount": RemoteMount(...)
})
```
+ Capabilities (`Filesystem`, `Shell`, `Compaction`, `Memory`, `Skills`) — декларация, что доступно в sandbox. + `LocalSnapshot` / `RemoteSnapshot` — replay state. + `SandboxPathGrant` — fine-grained path permissions.

**Что нужно**:
1. `Manifest` dataclass с `entries: dict[str, ManifestEntry]`
2. Entry types: `GitRepoEntry`, `LocalFileEntry`, `RemoteMountEntry`, `DirEntry`
3. `Capability` Protocol + `Filesystem` / `Shell` / `Compaction` / `Memory` / `Skills` impls
4. `Snapshot` Protocol + `LocalSnapshot` (filesystem tar) / `RemoteSnapshot` (object storage)
5. `SandboxPathGrant` — read-only / read-write / deny per path
6. Integration: расширить `tools/sandbox` + `multi_agent/workspace.py` Manifest-driven setup
7. CLI: `swarmline sandbox snapshot save/restore <name>`

**DoD**: agent с GitRepo entry получает свежий repo на старте; snapshot save/restore round-trip; deny-path реально блокирует write.

**Связано с**: IDEA-051 (worktree isolation, уже есть), path_safety.py.

---

### IDEA-057: Tool-level guardrails (ToolInput/ToolOutputGuardrail) (2026-05-05)

**Приоритет**: High
**Сложность**: Low

**Источник**: openai-agents-python `tool_guardrails.py`

Отдельный примитив для read-only валидации tool args/results, рядом с PreToolUse hook (который для side-effects).

**Мотивация**: У swarmline `hooks/` (PreToolUse/PostToolUse) — для побочных эффектов (logging, mutating context). agents-sdk имеет `ToolInputGuardrail` / `ToolOutputGuardrail` — pure functions с tripwire-семантикой, специально для validation. Чище separation of concerns: guardrail валидирует и решает halt/proceed, hook делает side-effect.

**Что нужно**:
1. `ToolInputGuardrail` Protocol: `(ctx, data: ToolInputGuardrailData) -> ToolGuardrailFunctionOutput`
2. `ToolOutputGuardrail` Protocol: `(ctx, data: ToolOutputGuardrailData) -> ToolGuardrailFunctionOutput`
3. `ToolGuardrailFunctionOutput(output_info, tripwire_triggered)` — tripwire halts run
4. Декораторы `@tool_input_guardrail` / `@tool_output_guardrail`
5. Регистрация: per-tool list в FunctionTool / в AgentConfig.tool_guardrails
6. Интеграция в thin runtime executor: гонять параллельно с tool execution
7. Exceptions: `ToolInputGuardrailTripwireTriggered`, `ToolOutputGuardrailTripwireTriggered`

**DoD**: guardrail rejecting PII в args останавливает run; tripwire поднимает typed exception; decorator-style работает; параллельное выполнение не блокирует tool.

**Связано с**: guardrails.py (агент-уровень) — этот идея на tool-уровень.

---

### IDEA-058: tool_use_behavior — granular контроль loop'а (2026-05-05)

**Приоритет**: Medium
**Сложность**: Low
**Источник**: openai-agents-python `agent.py` (`tool_use_behavior` field)

4 режима для контроля «что считать финальным выходом агента» — защита от бесконечных tool-loops.

**Мотивация**: agents-sdk:
- `"run_llm_again"` — default, результат tool → LLM (как сейчас)
- `"stop_on_first_tool"` — первый tool result = final output
- `StopAtTools(stop_at_tool_names=["submit", "answer"])` — стоп на конкретных tools
- `ToolsToFinalOutputFunction(ctx, results) -> ToolsToFinalOutputResult` — кастомная функция

Полезно для специализированных агентов: research-агент с tool `final_answer` → стоп; единичный SQL-агент → first-tool-result финал.

**Что нужно**:
1. `ToolUseBehavior` union в `agent/config.py`
2. `StopAtTools` TypedDict + `ToolsToFinalOutputFunction` callable type
3. `ToolsToFinalOutputResult(is_final_output, final_output)` dataclass
4. Логика в thin runtime executor: после tool calls применить behavior
5. `reset_tool_choice: bool = True` — авто-сброс tool_choice после tool call (предотвращает infinite loop)

**DoD**: stop_on_first_tool возвращает первый result; StopAtTools(["x"]) останавливается только на x; custom function переопределяет; reset_tool_choice ломает infinite loop в тесте.

---

### IDEA-059: Generic typed context Agent[TContext] (2026-05-05)

**Приоритет**: Medium
**Сложность**: Medium

**Источник**: openai-agents-python `RunContextWrapper[TContext]`

Type-safe shared state, текущий через tools/guardrails/handoffs, проверяемый mypy/pyright.

**Мотивация**: swarmline использует dict-based context в основном. agents-sdk: `Agent[MyContext]` + `RunContextWrapper[MyContext]` — generic тип течёт через всё, IDE и type-checker ловят ошибки доступа к полям.

**Что нужно**:
1. `RunContext[T]` Generic в domain_types
2. Параметризовать `Agent`, tool signature, hook signature, guardrail signature через TContext
3. Backward compat: `RunContext[Any]` = текущее поведение
4. Doc: пример с typed dataclass context

**DoD**: пример с typed dataclass context проходит ty check; backward compat с dict-context работает.

---

### IDEA-060: Hosted tools as primitives (2026-05-05)

**Приоритет**: Medium
**Сложность**: Medium

**Источник**: openai-agents-python tools (WebSearchTool, FileSearchTool, CodeInterpreterTool, ImageGenerationTool, ApplyPatchTool, ToolSearchTool)

Готовые tool-классы для распространённых сценариев — лучший DX чем «опиши свой через @tool».

**Мотивация**: У swarmline есть builtin (sandbox/web/thinking) + MCP. Но импорт-готовые `WebSearchTool()`, `FileSearchTool(index=...)`, `CodeInterpreterTool()` — добавил в `tools=[...]` и поехал. Снижает порог входа.

**Что нужно** (минимум, провайдер-нейтральные обёртки):
1. `WebSearchTool` — поверх Anthropic web search / OpenAI / Tavily / Brave
2. `FileSearchTool` — поверх RAG (см. rag.py) с index argument
3. `ApplyPatchTool` — diff application (см. IDEA-062)
4. `ToolSearchTool` — meta-tool, ищет тулзы по описанию когда tools >50

**DoD**: каждая обёртка работает с минимум 2 провайдерами; integration tests; docs пример «тулы за 5 строк».

**Связано с**: IDEA-047 (Web Tools), rag.py.

---

### IDEA-061: Apply patch + ApplyPatchEditor (2026-05-05)

**Приоритет**: Medium
**Сложность**: Low
**Источник**: openai-agents-python `apply_diff.py`, `editor.py`

Первоклассный diff-tool для код-пишущих агентов.

**Мотивация**: thin runtime имеет coding-tools (`thin/coding_toolpack.py`), но «apply patch как стандартный tool с проверкой результата и rollback» отдельно — полезно для PR-генераторов и refactor-агентов. agents-sdk: `apply_diff()` + `ApplyPatchOperation` + `ApplyPatchResult` + `ApplyPatchEditor`.

**Что нужно**:
1. `apply_diff(file_content, patch)` → result с success/failure + new_content
2. `ApplyPatchOperation(target_file, patch_text)` dataclass
3. `ApplyPatchResult(success, new_content, error_message, line_offsets)` 
4. `ApplyPatchTool` ToolSpec: операция → результат, dry-run опция
5. `ApplyPatchEditor` для batch операций с rollback
6. Format: unified diff (стандартный) + Codex-style (см. agents-sdk)

**DoD**: round-trip apply → result совпадает с git apply; rollback восстанавливает; dry-run не пишет; некорректный patch возвращает structured error.

**Связано с**: IDEA-060 (hosted tools).

---

### IDEA-062: Dynamic instructions как callable (2026-05-05)

**Приоритет**: Low
**Сложность**: Low
**Источник**: openai-agents-python `Agent.instructions: str | Callable[..., MaybeAwaitable[str]]`

Instructions как функция от context, не только статичная строка.

**Мотивация**:
```python
Agent(instructions=lambda ctx, agent: f"You are working on task {ctx.context.task_id} for user {ctx.context.user.name}")
```
Чище, чем собирать system prompt в setup-коде. Sync/async поддержка. agents-sdk поддерживает str | sync callable | async callable.

**Что нужно**:
1. `agent/config.py`: `instructions: str | InstructionsFunction | None`
2. `InstructionsFunction = Callable[[RunContext, Agent], MaybeAwaitable[str]]`
3. Resolver в bootstrap: вызывать callable перед стартом turn'а
4. Кеширование: если instructions detereministic относительно context — кешировать в run

**DoD**: callable работает sync и async; переменные context корректно подставляются; кеширование при идемпотентном callable.

**Связано с**: IDEA-045 (Project Instructions Loading) — этот про CLAUDE.md, новая идея про runtime генерацию.

---

### IDEA-063: run_demo_loop() REPL (2026-05-05)

**Приоритет**: Low
**Сложность**: Low
**Источник**: openai-agents-python `repl.py`

Однострочный REPL для интерактивного тестирования агента.

**Мотивация**: agents-sdk:
```python
from agents.repl import run_demo_loop
run_demo_loop(agent)  # readline-style chat
```
swarmline имеет CLI с командами, но quick-test REPL для разработчика — отдельная вещь. Снижает trial-and-error цикл при разработке агента.

**Что нужно**:
1. `swarmline.repl.run_demo_loop(agent, *, history=True, render_tools=True)`
2. Readline для навигации история
3. Pretty-print stream events (tool calls, thinking)
4. `:reset`, `:save <file>`, `:load <file>`, `:context` команды
5. Интеграция в CLI: `swarmline repl <agent.yaml>`

**DoD**: agent работает; история сохраняется; tool calls читаемо рендерятся; команды работают.

---

### IDEA-064: tool_namespace для группировки tools (2026-05-05)

**Приоритет**: Low
**Сложность**: Low
**Источник**: openai-agents-python `tool_namespace`

Контекст-менеджер для логической группировки tools когда их 50+.

**Мотивация**: При больших коллекциях (особенно после IDEA-060) tools загромождаются. agents-sdk: `with tool_namespace("github"): @function_tool def create_issue(): ...` → tool name становится `github.create_issue`.

**Что нужно**:
1. Context manager `tool_namespace(prefix)` 
2. Tools зарегистрированные внутри получают prefix
3. ToolSearchTool (IDEA-060) использует namespace для фильтрации

**DoD**: nested namespaces работают; tool_choice по namespace.tool работает; export/import сохраняет namespacing.

---

### IDEA-065: Realtime / voice agents (2026-05-05)

**Приоритет**: Low
**Сложность**: Very High
**Источник**: openai-agents-python `realtime/`

Voice pipeline для голосовых агентов.

**Мотивация**: agents-sdk имеет полный voice (audio_formats, openai_realtime, model_events, runner). swarmline LLM-agnostic, фокус на text. Добавлять только если есть реальный кейс (assistant, voice command, accessibility).

**Что нужно** (если решим делать):
1. `RealtimeAgent` с audio config
2. Audio formats: PCM16, μ-law, WAV
3. WebSocket transport для streaming
4. Provider adapters: OpenAI Realtime, Anthropic (когда выйдет)
5. STT/TTS pipeline опционально

**Решение**: defer до явного запроса — большой объём, узкий use case.

---

### IDEA-066: Computer use (browser automation) (2026-05-05)

**Приоритет**: Low
**Сложность**: High
**Источник**: openai-agents-python `computer.py`, `ComputerTool`

Browser automation tools.

**Мотивация**: agents-sdk: `ComputerTool` + `Computer` Protocol + `Button` + `Environment` для агентов кликающих по сайтам. Anthropic computer-use уже есть в Claude Sonnet. Можно сделать провайдер-нейтральную обёртку.

**Что нужно**:
1. `Computer` Protocol: screenshot, click, type, scroll, drag
2. `AsyncComputer` async вариант
3. `ComputerTool` ToolSpec
4. Backends: Playwright local / Anthropic computer-use API / OpenAI computer

**Решение**: defer — есть конкуренты (browser-use, lavague, stagehand). Делать только если станет частью core use case.

---

### IDEA-067: Self-editing memory blocks через tools (2026-05-05)

**Приоритет**: High
**Сложность**: High
**Источник**: Letta `memory_blocks`, Mastra `working memory`

Агент модифицирует свою долговременную память через tool calls (`core_memory_replace`, `core_memory_append`, `working_memory_update`), а не через application code.

**Мотивация**: У swarmline память (`FactStore`, `MessageStore`, `SummaryStore`) пишется приложением — агент пассивный consumer. У Letta/Mastra агент сам решает что важно и обновляет именованные блоки (`persona`, `human`, `task`, custom). Killer feature: continual learning без ручной orchestration. Mastra идёт дальше — working memory имеет JSON/markdown schema, агент следует ей.

**Что нужно**:
1. `MemoryBlock` dataclass: `{label, value, schema, last_modified, edit_count, char_limit}`
2. `MemoryBlockStore` Protocol с CRUD + history
3. Builtin tools: `core_memory_replace(label, old, new)`, `core_memory_append(label, content)`, `core_memory_search(query)`, `archival_memory_insert(content)`, `archival_memory_search(query)`
4. SystemPrompt assembly: блоки auto-injected в system prompt с границами (`<persona>...</persona>`)
5. Schema-validated блоки — Pydantic model описывает structure, агент обязан вернуть valid update
6. Edit history для audit + rollback

**DoD**: agent с persona-block самообновляет себя через 3 turn'а; schema-validated блок отвергает invalid updates с retry; edit history сохраняется; rollback работает.

**Связано с**: IDEA-068 (three-tier memory), IDEA-069 (sleep-time agents).

---

### IDEA-068: Three-tier memory architecture (core/recall/archival) (2026-05-05)

**Приоритет**: High
**Сложность**: Medium
**Источник**: Letta — direct из MemGPT paper (UC Berkeley)

Явное разделение памяти на три уровня по latency и стоимости: **core** (всегда in-context) / **recall** (полная история, searchable) / **archival** (vector DB, long-term knowledge).

**Мотивация**: swarmline имеет facts/messages/summaries, но без явного контракта «что всегда в context vs searchable vs архивное». MemGPT-paper показал, что чёткое разделение + LLM-driven paging между уровнями = OS-like virtual memory для модели. Это парадигмальный сдвиг от ad-hoc «кладём всё в RAG».

**Что нужно**:
1. `CoreMemory` Protocol — bounded size (e.g. 4KB), всегда в system prompt, mutable через memory blocks (IDEA-067)
2. `RecallMemory` Protocol — full conversation history, searchable, не in-context. Tool: `recall_memory_search(query)`
3. `ArchivalMemory` Protocol — vector DB (RAG), insert/search через tools. Long-term facts/docs.
4. `MemoryRouter` — auto-decision что писать куда (или manual через tools)
5. Migrate существующие FactStore/MessageStore/SummaryStore: messages → recall, facts → archival, summaries → core, или гибрид
6. Token budget enforcement: core memory hard limit + warning system

**DoD**: core memory не превышает limit; recall search возвращает messages из 1000+; archival vector search работает на 10K документов; auto-router classifies new info correctly в 80%+ кейсов.

**Связано с**: IDEA-067 (self-editing), IDEA-044 (compaction), IDEA-046 (session resume).

---

### IDEA-069: Sleep-time agents для memory consolidation (2026-05-05)

**Приоритет**: High
**Сложность**: High
**Источник**: Letta sleep-time agents

Фоновые agent processes между сессиями: суммаризируют, экстрактят facts, обновляют persona, prune outdated info. «Агент видит сны».

**Мотивация**: revolution feature от Letta. Между активными сессиями специализированный agent перерабатывает recall memory → обновляет core, инвалидирует устаревшее. У swarmline есть compaction.py (статическая суммаризация), но не «фоновый agent с собственными tools специально для memory consolidation».

**Что нужно**:
1. `SleepTimeAgent` — minimal agent с tool subset: только memory tools (read recall, write core, write archival)
2. `SleepTrigger` — какие события запускают: `on_session_end`, `cron schedule`, `idle_threshold`, `memory_pressure`
3. `MemoryConsolidationStrategy` — что делать: extract_facts / update_persona / prune_stale / detect_contradictions
4. Изоляция: sleep agent не пишет user-facing output, только memory mutations
5. Cost budget — sleep agent имеет hard token budget, нельзя scope-creep
6. Daemon integration: запуск через `daemon/` или external scheduler

**DoD**: sleep agent после 100 messages обновляет persona block; prune убирает контрадикции; budget enforced; не запускается во время active session (lock).

**Связано с**: IDEA-067, IDEA-068, daemon/.

---

### IDEA-070: Stateful agents API — agent_id lives forever (2026-05-05)

**Приоритет**: Medium
**Сложность**: High
**Источник**: Letta `agent_state` API + Mastra persistent agents

Парадигмальный сдвиг: агенты это persistent entities с `agent_id`, не runtime instances. `client.agents.create()` → можно слать messages в любой момент через дни/недели, state восстанавливается автоматически.

**Мотивация**: swarmline сейчас session-based — `Agent(...)` создаётся в коде, runtime instance, после завершения сессии restart требует ре-сетапа. Letta/Mastra API: `agent.id` URL, можно `POST /agents/{id}/messages` в любой момент. Намного проще для multi-tenant SaaS-style продуктов.

**Что нужно**:
1. `AgentRegistry` (есть в `multi_agent/agent_registry`) расширить: `create(...) -> agent_id`, `get(agent_id)`, `delete(agent_id)`, `update_config(agent_id, ...)`
2. Persistent agent state: config + memory blocks + memory tiers + tool set — всё bound к `agent_id`
3. REST API в `serve/`: `POST /v1/agents`, `GET /v1/agents/{id}`, `POST /v1/agents/{id}/messages`, `GET /v1/agents/{id}/messages`
4. Lazy loading — агент гидрируется из storage при первом use
5. Multi-tenancy: `tenant_id` + `agent_id` namespacing
6. Versioning — config changes сохраняют history; старые сессии используют snapshot конфига того момента

**DoD**: создал agent → процесс убил → restart → POST message работает с тем же id и memory; multi-tenant изоляция гарантирована; версионирование позволяет откатить config.

**Связано с**: IDEA-067/068 (memory persistence), `multi_agent/agent_registry`, `serve/`.

---

### IDEA-071: Reducer-based channels с типизированным state (2026-05-05)

**Приоритет**: High
**Сложность**: Medium
**Источник**: LangGraph `Annotated[T, reducer]` channels

Типизированные state slots с явным reducer'ом для merge'а параллельных writes — Pregel-inspired model. Гарантирует детерминизм при concurrent fan-out.

**Мотивация**: swarmline `graph_orchestrator_state` имеет state, но reducer-семантика для параллельных writes неявная. LangGraph: `state: Annotated[list[Message], operator.add]` — параллельные nodes конкурентно пишут, reducer мерджит. Без этого — race conditions / overwrites.

**Что нужно**:
1. `Channel[T]` Generic type с `reducer: Callable[[T, T], T]` (default = replace)
2. Standard reducers: `add` / `extend` / `merge_dicts` / `last_write_wins` / custom
3. `StateSchema` через TypedDict с `Annotated[type, reducer]`
4. `graph_orchestrator` validate: parallel writes без reducer = error
5. Migrate existing graph state на channel-based model
6. Documentation: examples с parallel branches и merge-correctness

**DoD**: 10 параллельных nodes пишут в `messages` channel — все 10 сообщений в финальном state; race condition тест проходит; `last_write_wins` корректно работает; type errors ловятся ty check.

**Связано с**: `multi_agent/graph_orchestrator_state`, IDEA-072 (super-steps).

---

### IDEA-072: Pregel-style super-steps + barrier sync (2026-05-05)

**Приоритет**: High
**Сложность**: High
**Источник**: LangGraph (Pregel-inspired) / Apache Beam

Формальная модель параллельного исполнения: super-steps с barrier синхронизацией — все nodes текущего шага завершаются до перехода к следующему. Гарантирует детерминизм.

**Мотивация**: текущий swarmline graph executor — нужно проверить, как именно решён параллелизм. Pregel super-step model — индустриальный стандарт (BSP — Bulk Synchronous Parallel). Без этого debug параллельных flow — кошмар.

**Что нужно**:
1. `SuperStep` execution model: collect all messages → execute all enabled nodes in parallel → barrier wait → apply reducers → emit transition
2. Detection of next active nodes по edge conditions
3. Deterministic ordering of reducer applications (по node name lex)
4. Step counter в state — для checkpointing (IDEA-073) и time-travel (IDEA-074)
5. Backward compat: existing graphs работают без opt-in

**DoD**: 5 параллельных nodes завершаются до запуска следующего шага; повторное выполнение с тем же input даёт identical state; performance overhead <10% vs free-fly execution.

**Связано с**: IDEA-071, IDEA-073, IDEA-074.

---

### IDEA-073: Durable execution через checkpointer ABC (2026-05-05)

**Приоритет**: High
**Сложность**: Medium
**Источник**: LangGraph `MemorySaver`/`SqliteSaver`/`PostgresSaver`/`RedisSaver`

Auto-resume from last super-step после crash/restart. Каждый super-step boundary = serializable checkpoint.

**Мотивация**: swarmline session_resumption есть, но именно «упало посреди super-step → restart продолжает с прошлого checkpoint без перезапуска uphill nodes» — нужна формализация. LangGraph даёт unified ABC + 4 backends.

**Что нужно**:
1. `Checkpointer` Protocol: `put(thread_id, checkpoint, metadata)`, `get(thread_id)`, `list(thread_id)`, `get_tuple(config)`
2. Backends: `InMemoryCheckpointer`, `SqliteCheckpointer`, `PostgresCheckpointer`, `RedisCheckpointer`
3. Auto-checkpoint на каждом super-step boundary
4. `Checkpoint` schema: state, next_nodes, step_id, parent_id, created_at
5. `graph.compile(checkpointer=...)` — opt-in
6. Resume API: `graph.run(thread_id="x", input=None)` — continues from last checkpoint

**DoD**: kill -9 после 5 super-steps → restart → продолжает с 6-го; PostgresCheckpointer survives DB restart; concurrent threads с одним checkpointer изолированы.

**Связано с**: IDEA-072, IDEA-055 (RunState recovery).

---

### IDEA-074: Time-travel debugging через checkpoint history (2026-05-05)

**Приоритет**: High
**Сложность**: Medium
**Источник**: LangGraph time-travel + LangSmith Studio

Откатиться на N super-steps назад и пойти другой веткой. Killer feature для отладки сложных flow.

**Мотивация**: LangGraph `graph.get_state_history(thread_id)` → list of checkpoints → `graph.update_state(checkpoint_id, override)` → run continues from there. У swarmline нет primitive «откати агента на 3 turn'а назад и попробуй другой ответ».

**Что нужно** (зависит от IDEA-073):
1. `Checkpointer.list(thread_id)` возвращает upstream history
2. `Checkpoint.parent_id` — DAG of states
3. API: `graph.update_state(thread_id, checkpoint_id, state_update)` — fork from this checkpoint
4. CLI: `swarmline trace history <thread_id>` / `swarmline trace fork <checkpoint_id>`
5. UI: visual checkpoint tree (см. IDEA-080 DevPlayground)

**DoD**: revert to checkpoint 3 → run with new input → forks DAG; original branch сохранён; UI показывает branching tree.

**Связано с**: IDEA-073, IDEA-080.

---

### IDEA-075: Send API для dynamic fan-out (2026-05-05)

**Приоритет**: Medium
**Сложность**: Medium
**Источник**: LangGraph `Send(node, state)`

Runtime-resolved параллельные edges: оркестратор сам решает «сейчас разветвляюсь на N веток с разным state».

**Мотивация**: swarmline graph edges статические (определяются на build). Send API позволяет: `return [Send("worker", {"item": x}) for x in items]` — fan-out количеством зависит от runtime data. Map-reduce паттерн для агентов.

**Что нужно**:
1. `Send(target_node, state_override)` dataclass
2. Node может возвращать `list[Send]` вместо плоского state update
3. Executor создаёт parallel super-step tasks с overridden state
4. Reduce step после fan-out — reducer мерджит результаты обратно
5. Visualisation в UI: dynamic fan-out branches

**DoD**: map-reduce пример (process 10 items в параллель → reduce) работает; overrides не affecting parent state; reducer merge корректен.

**Связано с**: IDEA-071, IDEA-072.

---

### IDEA-076: Native interrupts с Command resume (2026-05-05)

**Приоритет**: Medium
**Сложность**: Medium
**Источник**: LangGraph `interrupt()` + `Command(resume=...)`

Стандартизованный HITL flow: `interrupt(payload) → state.resume(value)` — без custom infrastructure.

**Мотивация**: swarmline `hitl/gate.py` есть, но pattern «node делает interrupt → возвращает state клиенту → клиент решает → resume точно с того же места» лучше формализовать. LangGraph даёт единый pattern.

**Что нужно**:
1. `interrupt(payload: Any) -> Any` function — внутри node останавливает execution, payload идёт в checkpoint
2. `Command(resume=value)` или `Command(goto=node, update=state)` — возобновление
3. `graph.run(input=Command(resume=approval))` — продолжить interrupted graph
4. Integration в hitl/gate.py: Gate использует interrupt поверх своего API
5. UI: pending interrupts list в DevPlayground (IDEA-080)

**DoD**: HITL approval flow через 3 interrupt'а в одном run; resume с фронтенда работает; параллельные interrupts (multiple agents wait) обрабатываются.

**Связано с**: hitl/, IDEA-073, IDEA-080.

---

### IDEA-077: Capabilities как composable bundles (2026-05-05)

**Приоритет**: High
**Сложность**: Medium
**Источник**: Pydantic AI `capabilities=[Thinking(), WebSearch(), MCP(...)]`

Bundle (tools + hooks + instructions snippet + model_settings) как reusable unit. Provider-adaptive — capability сама выбирает native API per provider.

**Мотивация**: у swarmline tools, hooks, instructions, model settings — отдельные слои. Pydantic AI: один импорт `WebSearch()` → bundle всего что нужно для web search, на Anthropic = native web_search, на OpenAI = web_search_preview tool, на Gemini = grounding. Намного лучший DX чем «опиши свой tool на каждый provider».

**Что нужно**:
1. `Capability` Protocol: `apply(agent_config: AgentConfig, runtime: Runtime) -> AgentConfig`
2. Built-in: `Thinking()`, `WebSearch(provider_overrides=...)`, `FileSearch(index=...)`, `MCP(servers=[...])`, `CodeExecution()`, `Memory(tier=...)`
3. Provider-adaptive logic: capability смотрит на runtime kind → выбирает реализацию
4. `AgentConfig.capabilities: list[Capability]` — порядок применения важен
5. Custom capabilities: third-party packages (см. IDEA-002 extensibility)
6. Composability: `WebSearch()` + `Thinking()` не конфликтуют, merge clean

**DoD**: `capabilities=[Thinking(), WebSearch()]` работает на 3+ provider'ах с native APIs; custom capability registry поддерживает third-party; tests на adaptation logic.

**Связано с**: IDEA-060 (hosted tools), IDEA-002 (registry).

---

### IDEA-078: Output retry on validation error (2026-05-05)

**Приоритет**: High
**Сложность**: Low
**Источник**: Pydantic AI auto-retry на schema violation

LLM вернул невалидный JSON для `output_type` → автоматически retry с validation error в качестве hint обратно в LLM.

**Мотивация**: swarmline `structured_output.py` валидирует, но retry-on-validation-error flow стоит проверить/улучшить. Pydantic AI: `agent.run_sync(...)` автоматически делает до N retry с error message обратно. Дешевле чем падать.

**Что нужно**:
1. `OutputValidator` Protocol с retry semantics
2. `AgentConfig.output_max_retries: int = 3`
3. На validation error: error message → user message в conversation → retry с тем же promt
4. Retry budget tracking в `cost.py` (не съесть всё на retry loop)
5. Decorator `@agent.output_validator` для custom validation logic
6. Logging retry attempts в observability

**DoD**: invalid JSON → 1 retry → success; persistent invalid → fail после N с typed exception; retry budget exhausted → controlled failure; tests на edge cases.

**Связано с**: structured_output.py, retry.py.

---

### IDEA-079: Workflow DSL — .then().branch().parallel().foreach() (2026-05-05)

**Приоритет**: High
**Сложность**: High
**Источник**: Mastra workflows + LangGraph

Type-safe builder API для воркфлоу с явным control flow вместо ad-hoc graph building.

**Мотивация**: swarmline `pipeline/` есть, но менее декларативный. Mastra DSL:
```ts
workflow.step(researchAgent).then(writerAgent).branch([
  { when: needsReview, then: reviewerAgent },
  { else: publishStep }
]).parallel([notifyEmail, notifySlack])
```
Клянусь golden DX. Можно адаптировать в Python через method chaining.

**Что нужно**:
1. `Workflow` builder: `.step(handler)`, `.then(handler)`, `.branch(conditions)`, `.parallel(handlers)`, `.foreach(items, handler)`, `.dountil(handler, condition)`
2. Step result types: типизированные через generic `Workflow[Input, Output]`
3. Suspend/resume support — workflow приостанавливается на любом step (см. IDEA-073/074)
4. Compile to internal graph representation (поверх IDEA-071/072 channels)
5. Visualization: render workflow as DAG в UI
6. Backward compat: старый `pipeline/` API остаётся

**DoD**: 5-step workflow с branch + parallel + foreach работает; suspend/resume on any step; types type-check end-to-end; visual rendering матчит execution.

**Связано с**: pipeline/, IDEA-072, IDEA-076.

---

### IDEA-080: DevPlayground — local UI для agent dev (2026-05-05)

**Приоритет**: High
**Сложность**: High
**Источник**: Mastra `mastra dev` (localhost:4111)

Локальный UI с tabs: agents / workflows / memory / tools / evals / traces. Запустил → потыкал агента → посмотрел memory → запустил workflow со step-by-step inspection.

**Мотивация**: swarmline `ui/` есть, но Mastra DevPlayground задаёт стандарт DX. Killer feature для onboarding и debugging. Чем-то похоже на Postman+Insomnia для агентов.

**Что нужно**:
1. `swarmline dev` CLI command поднимает local server (FastAPI + frontend)
2. Tabs:
   - **Agents**: список registered agents → клик → chat interface
   - **Memory**: inspect core/recall/archival по agent_id, edit blocks manually
   - **Workflows**: list workflows, run with custom input, step-by-step inspection
   - **Tools**: list tools per agent, test invocation в isolation
   - **Evals**: run evals, compare results
   - **Traces**: timeline of recent runs с tool calls / thinking / handoffs
   - **Checkpoints**: browse history (IDEA-074), fork from any
3. Frontend: React/Vue/Svelte (определиться) embedded в Python wheel
4. WebSocket для streaming events
5. Auth: defaults `localhost only`, opt-in remote с token

**DoD**: `swarmline dev` поднимает UI на :4111; агента можно прочат интерактивно; memory blocks редактируются; workflow step-by-step run; UI shipped в pip install.

**Связано с**: ui/, IDEA-073, IDEA-074, IDEA-076.

---

### IDEA-081: Minimal Code Agent SDK поверх ThinRuntime (2026-05-05, refined 2026-05-05)

**Приоритет**: HIGH
**Источник**: `reports/2026-05-05_analysis_thin-vs-pi-mono-opencode-code-agent-sdk.md` — сравнение thin с `badlogic/pi-mono` (44.6K ⭐), `anomalyco/opencode` (форк `sst/opencode`, ~155K ⭐), `HarnessLab/claw-code-agent` (Python Claude Code clone), `ultraworkers/claw-code` (Rust).

**Философия**: «LLM умная — дай ей петлю обратной связи и не мешай». Минимум — это **правильные** фичи (safety + self-verification + reactivity), а не маленький набор. После них умный LLM сам себя проверяет, не падает на длинной сессии и не делает страшное.

**Цель**: чтобы разработчик мог построить простейший code-agent тремя строками:

```python
from swarmline import CodeAgent
agent = CodeAgent(model="sonnet", cwd="/repo")
async for ev in agent.run("fix typo in README"):
    print(ev)
```

— без явного знания `RuntimeConfig` / `HookRegistry` / `DefaultToolPolicy` / `ExecutionWorkspace` / `CommandRegistry` / `SwarmlineStack`.

#### Философская карта (как фичи замыкают LLM на себя)

```
Думай свободно
   ↓
   AgentMessage (D) ← LLM не зажат в LLM-формат сообщений
   ↓
Действуй
   ↓
   tools (C: read/write/edit/glob/apply_patch/todo/bash/grep + AG question)
   ↓
Получи структурный сигнал
   ↓
   AH smart truncation        — видишь сигнал, не шум
   AF diagnostics             — видишь свои ошибки (compiler-as-tool)
   tool_output_chunk events   — видишь progress, можешь abort
   ↓
Не упади, не сожги
   ↓
   AA truncation continuation — закончил мысль
   AB reactive compact        — пережил длинную сессию
   AC preflight check         — не сжёг лимит
   AD file safety             — не вышел за workspace
   AE bash safety             — не снёс репо
   ↓
Если совсем неясно
   ↓
   AG question tool           — спросил, не гадал
```

#### P0 — обязательное (19 пунктов)

##### Базовая SDK-механика (A–H)

| ID | Зазор | Что сделать |
|----|-------|-------------|
| **A** | Нет публичного `CodeAgent` фасада | Новый модуль `swarmline.code_agent`: `CodeAgent(model, cwd, tools=..., on_permission=..., on_question=...)`, `.run(prompt)` → `AsyncIterator[Event]`, `.stream()`, `.close()` |
| **B** | `ThinRuntime.__init__` принимает 12 коллабораторов | Builder / `from_config()` factory; авто-дефолты для `hook_registry` / `tool_policy` / `workspace` / `command_registry` / `subagent_config` |
| **C** | Канонический набор coding-tools неполный | Аудит `coding_toolpack.py` против: `read`, `write`, `edit`, `glob`, **`apply_patch`** (нет), **`todo`** (нет), `bash`, `grep` |
| **D** | Нет AgentMessage / convertToLlm seam | Ввести `AgentMessage` (user / assistant / tool_result + UI: notification / status) + `convert_to_llm` callback. Strangler-Fig миграция |
| **E** | Нет async permission-callback | `on_permission_request: (tool, args) -> Allow \| Deny(reason) \| AskUser(prompt)` отдельно от `DefaultToolPolicy` |
| **F** | Нет mid-run control surface | В `RuntimeConfig`: `should_stop_after_turn`, `get_steering_messages`, `get_followup_messages`, `transform_context` (паттерн pi-agent-core) |
| **G** | Tool execution mode неявный | `tool_execution: Literal["sequential","parallel"]` поле в `RuntimeConfig` |
| **H** | Нет CLI-runner | `python -m swarmline.code_agent "<prompt>"` поверх фасада — adoption + e2e smoke |

##### Safety / resilience guards (AA–AE)

| ID | Что | Почему must-have | Цена |
|----|-----|------------------|------|
| **AA** | **Truncation continuation** (`finish_reason=length` → авто-retry с continuation) | LLM обрывает ответ молча на длинных правках | ~50 LOC |
| **AB** | **Reactive compaction** на `prompt_too_long` ошибке провайдера | Без — агент **умирает** на длинной сессии при первом overflow | ~100 LOC, поверх P1-L |
| **AC** | **Preflight prompt-length check** (counter + soft warn / hard block) | Экономит деньги: ловим overflow до API call. Эвристика char/4 без тяжёлого tokenizer'а | ~80 LOC |
| **AD** | **File-tool safety guards**: binary detection, max read/write size, workspace boundary, symlink escape | Без — агент читает `/etc/passwd` через симлинк или 5GB бинарник в контекст | ~150 LOC |
| **AE** | **Bash destructive-command warning** (regex: `rm -rf`, `git push --force`, `drop database`, `dd of=`) | Без — агент сам затирает workspace. Лёгкий guard, не Claude-Code-style 18-submodule матрица | ~80 LOC |

##### Self-verification / feedback loops (AF–AH)

| ID | Что | Почему (LLM-brain-to-max) | Цена |
|----|-----|---------------------------|------|
| **AF** | **`diagnostics` tool** — generic shell-out к project-linter/type-checker (auto-detect: `pyproject.toml` → `ruff`/`ty`, `package.json` → `tsc --noEmit`/`eslint`, `Cargo.toml` → `cargo check`, `go.mod` → `go vet`). Output: `[{file, line, col, severity, message}]` | **THE feedback loop** для code-агента. После edit агент сам вызывает `diagnostics()`, видит свои ошибки, исправляется. Без него LLM пишет вслепую. Замещает full LSP в minimal | ~150 LOC |
| **AG** | **`question` tool + `on_question` callback** — агент спрашивает SDK-консьюмера в середине run'а в неоднозначной ситуации. Default = «no answer, use best judgment» (LLM свободен) | LLM не должен **гадать** и **не должен застревать**. opencode `question.ts`, HarnessLab `ask-user-runtime` | ~50 LOC |
| **AH** | **Smart tool-output truncation** — head/tail с маркером `[N more lines truncated, use offset=X to see more]`, configurable per-tool | `grep "TODO"` на большом репо забивает контекст и LLM глупеет. С truncation — LLM видит сигнал, не шум, может продолжить через `offset`. pi `truncate.ts` + `output-accumulator` | ~80 LOC |

##### Session lifecycle minimum (K1–K3)

Code-agent — это работа на часы/дни, не curl call. Без сессий после первого крэша теряется вся работа; без `reset()` нельзя начать заново внутри той же логической сессии. Все 4 reference-проекта (pi-coding-agent, opencode, claw-code-agent, ultraworkers/claw) имеют сессии как P0.

| ID | Что | Почему P0 | Цена |
|----|-----|-----------|------|
| **K1** | **Session lifecycle minimum**: `agent.session_id` (auto UUID), `agent.save()`, **auto-save после каждого turn** в `~/.swarmline/sessions/<id>/`, `CodeAgent.resume(id)`. Storage поверх существующего `swarmline.memory.sqlite` | После крэша агент восстанавливает работу с того же turn. Минимум для жизни code-agent'а | ~150 LOC, поверх существующего `MessageStore`/`SessionStateStore` |
| **K2** | **`agent.reset()` + `agent.clear_history(keep=["system", "agents_md"])`** | Без — чтобы начать заново нужно `del agent; agent = CodeAgent(...)`, теряя session_id и cwd. С — чистый контекст внутри той же логической сессии | ~30 LOC |
| **K3** | **Метаданные сессии**: title (auto из первого prompt — первые 60 символов), cwd, git branch (auto-detect если репо), created_at, last_used_at, status (`active`/`paused`/`done`), turn_count | Без — sessions это безымянные UUIDs, искать невозможно. С — `list_sessions()` имеет смысл (P1-U) | ~50 LOC |

#### P1 — сильные дифференциаторы (12 пунктов)

##### Базовый набор (I, J, L, N, O, R)

| ID | Что | Зачем |
|----|-----|-------|
| **I** | Atomic file-mutation queue | pi `file-mutation-queue.ts`: защита от partial-write между batched edits |
| **J** | Snapshot + revert | `agent.snapshot()` → откат файлов и истории. opencode `session/revert.ts` |
| **L** | Pluggable compaction strategy | `compaction_strategy: CompactionStrategy` в config (база для AB и X) |
| **N** | `AGENTS.md` loader | Авто-merge `cwd/AGENTS.md` (+ `.claude/rules/*.md` опционально) в system prompt |
| **O** | Cost / budget guard как event | `BudgetExceededEvent` в потоке; soft/hard limits в config (есть в `cost.py`) |
| **R** | **`tool_output_chunk` event** — streaming tool output как first-class event. SDK видит progress длинной команды, может оборвать через `abort_signal` | pi: «agent sees output as it appears, can decide to abort». Часть инфраструктуры в `stream_parser.py` уже есть, нужно дотащить как event |

> **Note**: бывшая P1-K (session save/resume одной строчкой) расщеплена на **P0-K1/K2/K3** — это слишком central для code-agent SDK, чтобы быть P1.

##### Multi-session UX (U–W)

| ID | Что | Зачем |
|----|-----|-------|
| **U** | **`CodeAgent.list_sessions(cwd=None, status=None)`** — табличный обзор: id, title, cwd, last_used, status, turn_count | Daily UX: «что я делал на прошлой неделе?» |
| **V** | **`CodeAgent.fork(session_id, title=...)`** — копия истории + cwd + текущего snapshot, новый id. «Попробовать альтернативный подход без потери оригинала» | pi и opencode имеют |
| **W** | **`CodeAgent.delete(session_id)` / `archive(session_id)`** | Гигиена: удалять/архивировать накопленные эксперименты |

##### Продвинутая работа с контекстом (X–Z)

| ID | Что | Зачем |
|----|-----|-------|
| **X** | **Proactive compaction trigger** — при превышении threshold (например, 80% context window) — авто-summarize старых turns в compact note. **Превентивно**, не реактивно как P0-AB | P0-AB ловит overflow когда уже поздно. X — упреждает. У HarnessLab `auto-compact` отдельно от reactive |
| **Y** | **Microcompact** — компактация **отдельных** длинных сообщений (особенно tool-outputs) с сохранением структуры. Например: длинный `grep` → «matched 423 files; first 10: ...; structure: ...» | HarnessLab: `microcompact.py` отдельный модуль. Без — один длинный grep съедает 50% контекста |
| **Z** | **File-history journal** per session — список всех write/edit/shell с snapshot IDs. На resume агент видит «ранее редактировал X.py на turn 5, snapshot snap-7» | HarnessLab: `file-history` с replay. Усиливает P1-J snapshot |

#### Сознательно отложено (post-minimal)

- ~~Per-tool prompt sidecar~~ — cosmetic
- ~~Full LSP-client~~ — `diagnostics` tool через `ruff`/`tsc` решает 80% за 5% работы. Реальный LSP — когда нужны `find references` / `hover`
- ~~Worktree-aware execution~~ — полезно в CI, не нужно для «простейшего»
- ~~HTTP-server + OpenAPI~~ — opencode-стиль over-engineering для Python SDK
- ~~Plugin entry-points~~ — `local_tools=` параметр покрывает кейсы
- ~~Skills discovery directory~~ — орто к thin
- ~~Read-after-write автохук~~ — спамит контекст; LLM сам решит вызвать read
- ~~Test-runner tool~~ — это just `bash("pytest")`, отдельный tool не нужен
- ~~Custom agent profiles из `~/.claude/agents/*.md`~~ — swarmline уже имеет skills/subagents
- ~~Manifest plugins~~ — claw-code-уровень сложности

**DoD умбреллы (P0)**:
- [ ] `from swarmline import CodeAgent` работает
- [ ] `CodeAgent(model="sonnet", cwd=tmpdir).run("...")` без явной сборки stack
- [ ] CLI: `python -m swarmline.code_agent "<prompt>"` запускается
- [ ] Все 4263+ существующих тестов проходят (обратная совместимость)
- [ ] Покрытие нового модуля ≥ 90% (core SDK)
- [ ] `examples/code_agent_quickstart.py` прогоняется в CI
- [ ] Документация: `docs/code_agent_sdk.md` с примерами
- [ ] **Self-verification loop работает E2E**: edit→diagnostics→fix без вмешательства пользователя (P0-AF + P0-C edit)
- [ ] **Long-session survival test**: агент переживает > 50 turns без падения (P0-AA + AB + AC)
- [ ] **Safety test**: `rm -rf $HOME` блокируется (AE), symlink-escape блокируется (AD)
- [ ] **Session resume E2E**: kill agent → `CodeAgent.resume(id)` → продолжает с того же turn без потери истории (P0-K1)
- [ ] **Auto-save invariant**: после каждого turn в `~/.swarmline/sessions/<id>/` появляется persisted state (P0-K1)
- [ ] **`agent.reset()` works**: чистит history но сохраняет session_id, cwd, и AGENTS.md контекст (P0-K2)

**Roadmap первого подхода (~3.5 недели для P0)**:
1. **Спайк** (1 день): прототип `CodeAgent` фасада, найти Optional-defaults choke-points
2. **P0-A, B, H** (2-3 дня): фасад + default stack + CLI
3. **P0-C** (2 дня): `apply_patch` + `todo` tools, аудит существующих
4. **P0-E** (1 день): `on_permission_request` API
5. **P0-K1, K2, K3** (2-3 дня): session lifecycle (auto-save / resume / reset / metadata) поверх `swarmline.memory.sqlite`
6. **P0-AA, AB, AC** (2-3 дня): truncation continuation + reactive compact + preflight check
7. **P0-AD, AE** (1-2 дня): file safety + bash destructive warning
8. **P0-AF, AG, AH** (2-3 дня): diagnostics tool + question tool + smart truncation
9. **P0-D, F, G** (3-4 дня): AgentMessage + convertToLlm + mid-run hooks (Strangler Fig — самое инвазивное)
10. **Docs + example** (1-2 дня)

**Связано с**: thin/, IDEA-068 (Project Instructions Loading) ↔ N, IDEA-070 (Session Resume) ↔ K, IDEA-076 (Conversation Compaction) ↔ L+AB, IDEA-077 (Web Tools) ✓ done in P0-C.

**План**: *(не создан, ждёт promotion через `/mb plan feature minimal-code-agent-sdk` после согласования приоритета)*

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
