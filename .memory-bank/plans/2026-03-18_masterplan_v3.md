# Master Plan v3.2 — Swarmline Roadmap

> Обновлён: 2026-03-18 (v3.2 — retry/cancel/RAG/DX improvements)
> Базовая версия: 0.5.0 (multi-provider ThinRuntime + upstream middleware)
> 27 идей + OpenAI Agents SDK
> Принцип: **простая библиотека** с optional enterprise layers

---

## Философия

**Swarmline — это библиотека, не фреймворк.**

1. **Simple by default** — `pip install swarmline` даёт core: multi-runtime, structured output, budget, sessions. Работает за 5 минут.
2. **Opt-in complexity** — tasks, hierarchy, scheduler, MCP = optional extras (`swarmline[tasks]`, `swarmline[scheduler]`).
3. **Protocol-first** — все компоненты через Protocol. Замени любой на свой.
4. **Thin wrappers** — не дублируем SDK, оборачиваем. Когда SDK обновляется, новые фичи доступны через pass-through.
5. **Docs-first delivery** — каждая фаза завершается документацией. Код без документации = не сделано.

---

## Требование к документации (обязательно для каждой фазы)

Каждая фаза/sub-phase **ОБЯЗАТЕЛЬНО** завершается документацией. Без документации фаза НЕ считается завершённой.

### Что включает документация:

| Тип | Что | Формат | Когда |
|-----|-----|--------|-------|
| **API Reference** | Все public Protocols, classes, functions | Docstrings (Google style) + mkdocs auto-gen | Каждая фаза |
| **Getting Started** | Минимальный пример для начала работы | Markdown guide в `docs/` | Phase 6 (первый), обновлять при новых фичах |
| **How-to Guide** | Конкретная задача: "как добавить guardrail" | Markdown с рабочим примером кода | Каждая фича |
| **Code Examples** | Рабочие примеры в `examples/` | Python файлы, запускаемые | Каждая фича |
| **CHANGELOG** | Что изменилось, migration notes | Markdown, append | Каждый релиз |
| **Architecture Decision** | Почему так, а не иначе | ADR в memory-bank | Значимые решения |

### DoD документации (добавляется к каждой фазе):

```
- [ ] Docstrings: все public API (Protocols, classes, functions) — Google style
- [ ] How-to guide: `docs/guides/<feature>.md` с рабочим примером
- [ ] Code example: `examples/<feature>/` — запускаемый скрипт
- [ ] CHANGELOG entry
```

### Документация по фазам:

| Phase | Документация |
|-------|-------------|
| **6** | Getting Started guide (первый!), @tool guide, structured output guide, adapter registry guide |
| **7** | Cost budget guide, guardrails guide (с custom guardrail примером), input filter guide |
| **8** | Session backends guide (SQLite, Redis), tracing guide (Console + OTel), memory scopes guide |
| **9 MVP** | Agent-as-tool guide, task queue guide, agent registry guide |
| **9 Full** | Enterprise tasks guide, hierarchy guide, delegation guide, scheduler guide |
| **10** | CLI runtime guide (Claude Code + custom), MCP guide, credential proxy guide |
| **11** | OpenAI Agents SDK migration guide, bridges guide |
| **v1.0-core** | **Full documentation site** (mkdocs-material): Getting Started, Concepts, API Reference, Guides, Examples |

---

## Обзор

```
CORE (swarmline):
  Phase 6: DX Foundation      ← structured output, @tool, adapter registry, legacy cleanup
  Phase 7: Production Safety  ← cost budget, guardrails, input filters
  Phase 8: Persistence        ← session backends (extend existing), tracing

ENTERPRISE (optional extras):
  Phase 9: Multi-Agent        ← task queue → task store, agent registry → hierarchy, delegation, scheduler
  Phase 10: Platform          ← CLI runtime, MCP, credential proxy, RTK, OAuth

ECOSYSTEM:
  Phase 11: OpenAI Agents SDK ← 4-й runtime + bridges (when SDK ≥ v1.0)
```

---

## Разделение: Core vs Enterprise

| Layer | Пакет | Что входит | Цель |
|-------|-------|-----------|------|
| **Core** | `swarmline` | Phases 6-8 | Быстрый старт, production-ready single agent |
| **Tasks** | `swarmline[tasks]` | 9B full | Enterprise task store |
| **Multi-Agent** | `swarmline[multi-agent]` | 9A, 9C, 9D | Agent hierarchy + delegation |
| **Scheduler** | `swarmline[scheduler]` | 9E | Heartbeat / cron agents |
| **CLI** | `swarmline[cli]` | 10A | Subprocess CLI agents |
| **MCP** | `swarmline[mcp]` | 10B, 10C | MCP multi-transport |
| **OpenAI SDK** | `swarmline[openai-agents]` | Phase 11 | OpenAI Agents runtime |

---

## Граф зависимостей (исправленный)

```
IDEA-016 (tool decorator) ─────────────────────────────────────────┐
IDEA-011 (structured output) ─→ IDEA-008 (guardrails) ─────────────┤
IDEA-002 (adapter registry) ──→ IDEA-003 (CLI runtime) ────────────┤
IDEA-004 (cost budget) ────────────────────────────────────────────┤
IDEA-013 (input filter) ───────────────────────────────────────────┤
IDEA-010 (session backends) ──→ IDEA-018 (task backlog) ───────────┤
                                IDEA-019 (agent registry) ─────────┤
IDEA-009 (agent-as-tool) + IDEA-019 → IDEA-006 (delegation) ──────┤
IDEA-006 (delegation) ───────→ IDEA-007 (scheduler) ──────────────┘
IDEA-015 (tracing) ────────────────────────────────────────────────
IDEA-023 (UI projection) ← зависит от RuntimeEvent (уже есть)
IDEA-014 (MCP multi-transport) → IDEA-012 (MCP approval)

Независимы: IDEA-001 (OAuth), IDEA-017 (RTK), IDEA-020 (cred proxy), IDEA-023 (projection)
Merged into parent: IDEA-021 (memory scopes → 8A), IDEA-022 (caller policy → 7B)
```

**Исправлено vs v2**:
- ❌ 9C (hierarchy) больше НЕ зависит от 9B (tasks) — агенты существуют без задач
- ❌ 9E (scheduler) больше НЕ зависит от 10A (CLI) — scheduler работает через AgentRuntime Protocol
- ❌ 9A (agent-as-tool) больше НЕ зависит от 7A (budget) — budget attribution = enhancement
- ✅ 10A (CLI) можно делать параллельно с Phase 7-8 (зависит только от 6C)

---

## Phase 6: DX Foundation

**Цель**: Удобство разработки + cleanup legacy.

### 6A: Structured Output via Pydantic (IDEA-011)

**Приоритет**: High | **Сложность**: Low | **~2-3 дня**

> **Важно**: это ДОРАБОТКА существующего кода (structured_output.py, RuntimeConfig.output_format), не написание с нуля.

**Scope**:
1. Переименовать `output_format` → `output_type: type[BaseModel] | None` (backward compat через alias)
2. Использовать существующий `append_structured_output_instruction()` + добавить Pydantic `model_json_schema()`
3. Post-validation через `model_validate_json()` + retry (до `max_model_retries`, default 3)
4. `RuntimeEvent.final(structured_output=parsed_model)` — уже есть поле, формализовать
5. Обновить существующие тесты structured output

**DoD**:
- [ ] Migrate existing `output_format` → `output_type` (backward compat)
- [ ] Unit: validation pass/fail, retry logic, schema extraction — 10+ тестов
- [ ] Integration: Anthropic + OpenAI + Google — 6+ тестов
- [ ] Coverage 95%+
- [ ] Docs: structured output guide + code example + docstrings

### 6B: Tool Schema Auto-generation (IDEA-016)

**Приоритет**: Medium | **Сложность**: Low | **~1-2 дня**

**Scope**: `@tool` декоратор, type hints → JSON Schema, docstring → descriptions. Совместим с `ToolSpec`.

**DoD**:
- [ ] Unit: type mapping, docstring parsing, edge cases — 15+ тестов
- [ ] Integration: tool через runtime — 3+ тестов
- [ ] Docs: @tool decorator guide + code example + docstrings

### 6C: Extensible Adapter Registry (IDEA-002)

**Приоритет**: High | **Сложность**: Low | **~2-3 дня**

> **Важно**: рефакторинг существующего `RuntimeFactory` (if/elif → register/get), не новая система.

**Scope**:
1. `RuntimeFactory.register(name, factory_fn)` / `list_available()`
2. Entry points для auto-discovery плагинов
3. Встроенные runtime'ы через тот же механизм
4. Миграция: существующий RuntimeFactory → новый API (backward compat)

**DoD**:
- [ ] Unit: registration, discovery, validation — 12+ тестов
- [ ] Integration: plugin entry point — 3+ тестов
- [ ] Backward compat: `RuntimeFactory.create()` работает как раньше
- [ ] Docs: adapter registry guide (как зарегистрировать custom runtime) + docstrings

### 6D: Legacy Cleanup + Core DX (RuntimePort removal, typed events, cancel, context manager) (IDEA-024, IDEA-025)

**Приоритет**: High | **Сложность**: Medium | **~3-4 дня**

> Объединяет legacy cleanup с фундаментальными DX улучшениями, которые нужны ДО Phase 7+.

**Scope — Legacy Cleanup**:
1. Мигрировать `SessionManager.stream_reply()` → использовать `AgentRuntime` напрямую
2. Убрать `SessionState.adapter: RuntimePort` → заменить на `runtime: AgentRuntime`
3. Удалить `runtime/ports/` (BaseRuntimePort, ThinRuntimePort, DeepAgentsRuntimePort)
4. Убрать `RuntimePort` из `protocols.py` и `__init__.py`
5. **Strangler Fig**: сначала добавить новый path, потом удалить старый
6. Split `protocols.py` по domain: `protocols/memory.py`, `protocols/session.py`, etc. (re-export для compat)
7. Error messages → English (user-facing runtime errors)
8. Fix version mismatch: `__init__.py` → dynamic from `importlib.metadata`

**Scope — Cancellation (IDEA-024)**:
1. `AgentRuntime.cancel()` method в Protocol
2. `CancellationToken` dataclass: `cancelled: bool`, `cancel()`, `on_cancel(callback)`
3. `RuntimeConfig.cancellation_token: CancellationToken | None`
4. При cancel: CLI runtime → SIGTERM, SDK runtime → cancel HTTP request
5. `RuntimeEvent.error(kind="cancelled")` при отмене

**Scope — AsyncContextManager (IDEA-025)**:
1. `AgentRuntime` supports `async with runtime:` (cleanup on exit)
2. `Agent` supports `async with Agent(...) as agent:` (cleanup on exit)
3. Default `__aenter__` = noop, `__aexit__` = cleanup()

**Scope — Typed RuntimeEvent accessors**:
1. `event.text` property → `event.data.get("text", "")` (для assistant_delta)
2. `event.tool_name` property → `event.data.get("name", "")` (для tool_call)
3. `event.is_final` / `event.is_error` / `event.is_text` — boolean helpers
4. Backward compat: `event.data` dict остаётся, accessors = sugar

**DoD**:
- [ ] SessionManager работает через AgentRuntime
- [ ] RuntimePort удалён из public API
- [ ] `AgentRuntime.cancel()` + CancellationToken работает
- [ ] AsyncContextManager для Agent и AgentRuntime
- [ ] Typed event accessors (text, tool_name, is_final, etc.)
- [ ] protocols.py split по domain
- [ ] Error messages на английском
- [ ] Version dynamic from importlib.metadata
- [ ] Все существующие тесты проходят
- [ ] Unit: cancellation, context manager, typed accessors — 12+ тестов
- [ ] **Phase 6 завершение**: Getting Started guide + `examples/` directory + CHANGELOG v0.6.0

---

## Phase 7: Production Safety

**Цель**: Контроль расходов, валидация контента.

### 7A: Cost Budget Tracking (IDEA-004)

**Приоритет**: High | **Сложность**: Medium | **~3-4 дня**

> **Naming**: `CostBudget` (не `BudgetPolicy`) — чтобы отличить от существующего `ContextBudget` (context window management).

**Scope**:
1. `CostBudget`: `max_cost_usd`, `max_total_tokens`, `action_on_exceed` (pause/error/warn)
2. `CostTracker` — аккумулирует usage per-session (не путать с ContextBudget)
3. `RuntimeConfig.cost_budget: CostBudget | None`
4. Pricing table: JSON, обновляемая
5. Coexistence: `ContextBudget` (window size) + `CostBudget` (money) — разные concerns

**DoD**:
- [ ] Contract: `CostBudget` + `CostTracker`
- [ ] Unit: tracking, limits, pricing — 15+ тестов
- [ ] Integration: budget exceeded → error — 4+ тестов
- [ ] Docs: cost budget guide (ContextBudget vs CostBudget) + code example + docstrings

### 7B: Guardrails (IDEA-008 + IDEA-022 CallerPolicy)

**Приоритет**: High | **Сложность**: Medium | **~4-5 дней**

**Зависит от**: 6A

**Scope**:
1. `Guardrail` Protocol: `async (context, input) -> GuardrailResult`
2. Input/Output guardrails, tripwire, parallel execution
3. CallerPolicy как builtin guardrail (не отдельная система)
4. Builtin: `ContentLengthGuardrail`, `RegexGuardrail`, `CallerAllowlistGuardrail`

**DoD**:
- [ ] Contract: `Guardrail`, `InputGuardrail`, `OutputGuardrail` Protocols
- [ ] Unit: 15+ тестов
- [ ] Integration: 4+ тестов
- [ ] Docs: guardrails guide (builtin + custom guardrail example) + docstrings

### 7C: Pre-LLM Input Filter (IDEA-013)

**Приоритет**: Medium | **Сложность**: Low | **~1-2 дня**

**Scope**: `InputFilter` Protocol, chain, builtin MaxTokensFilter + SystemPromptInjector.

**DoD**:
- [ ] Unit: 10+ | Integration: 3+
- [ ] Docs: input filter guide + docstrings

### 7D: Retry / Fallback Policy (IDEA-026) — NEW

**Приоритет**: High | **Сложность**: Medium | **~2-3 дня**

> Rate limits у Anthropic/OpenAI — реальность. Без retry production невозможен. Ни у LangChain, ни у CrewAI нет retry как first-class Protocol.

**Scope**:
1. `RetryPolicy` Protocol: `should_retry(error, attempt) -> (bool, delay_seconds)`
2. `ExponentialBackoff` builtin: base=1s, max=60s, jitter=True
3. `ModelFallbackChain`: при rate limit / error → следующая модель в цепочке
   - Пример: `["claude-sonnet-4-20250514", "claude-haiku-4-20250514"]` — если Sonnet rate limited → Haiku
4. `ProviderFallback`: при provider outage → другой provider
   - Пример: Anthropic down → OpenAI (если модель совместима)
5. `RuntimeConfig.retry_policy: RetryPolicy | None`
6. Интеграция: retry wrapper вокруг adapter.call() в ThinRuntime
7. Events: `RuntimeEvent.warning(kind="retry", attempt=2, reason="rate_limit")`

**DoD**:
- [ ] Contract: `RetryPolicy`, `ExponentialBackoff`, `ModelFallbackChain`
- [ ] Unit: retry logic, backoff calc, jitter, fallback chain — 12+ тестов
- [ ] Integration: rate limit → retry → success — 3+ тестов
- [ ] Docs: retry/fallback guide + code example + docstrings
- [ ] **Phase 7 завершение**: CHANGELOG v0.7.0

---

## Phase 8: Persistence & Observability

**Цель**: Сессии persistent, всё трейсится.

### 8A: Session Backends + Memory Scopes (IDEA-010 + IDEA-005 + IDEA-021)

**Приоритет**: High | **Сложность**: Medium | **~5-6 дней**

> **Важно**: это РАСШИРЕНИЕ существующего `SessionManager`, не замена.
> Существующие: `SessionManager`, `SessionState`, `SessionKey`, memory stores (inmemory, sqlite, postgres).
> Новое: pluggable `SessionBackend` Protocol как storage layer ПОД существующий manager.
> Memory Scopes (IDEA-021) merged here — namespace prefixes в SessionBackend.

**Scope**:
1. `SessionBackend` Protocol: `save(key, state)` / `load(key)` / `delete(key)` / `list()`
2. `SqliteSessionBackend` — zero-config (расширение существующего sqlite memory store)
3. `RedisSessionBackend` (optional `swarmline[redis]`)
4. `EncryptedSessionBackend` — overlay
5. **Migration**: существующий `SessionManager` получает `backend` parameter, in-memory = default
6. **Memory Scopes**: `MemoryScope` enum → prefix keys (`global:`, `agent:{id}:`, `shared:{group}:`)
7. Scope enforcement: agent isolation по namespace

**DoD**:
- [ ] Contract: `SessionBackend` Protocol
- [ ] Unit: save/load/delete, encryption, scopes — 18+ тестов
- [ ] Integration: session resume + scope isolation — 6+ тестов
- [ ] Backward compat: SessionManager без backend = in-memory (как сейчас)
- [ ] Docs: session backends guide (SQLite + Redis) + memory scopes guide + docstrings

### 8B: Event Bus + Tracing (IDEA-015, IDEA-027) — ENHANCED

**Приоритет**: Medium | **Сложность**: Medium | **~4-5 дней**

> **Event Bus** (IDEA-027) — фундамент для tracing. Universal callbacks для всех runtime, не только claude_sdk HookRegistry.

**Scope — Event Bus (IDEA-027)**:
1. `EventBus` Protocol: `subscribe(event_type, callback)` / `emit(event)`
2. Event types: `llm_call_start`, `llm_call_end`, `tool_call_start`, `tool_call_end`, `error`, `final`
3. Callbacks: `async (event) -> None` — fire-and-forget, не блокируют pipeline
4. `RuntimeConfig.event_bus: EventBus | None`
5. Builtin `InMemoryEventBus` — default
6. Replaces claude_sdk-specific HookRegistry как universal mechanism

**Scope — Tracing (поверх Event Bus)**:
1. `Tracer` Protocol: `start_span(name, attrs)` / `end_span()` / `add_event()`
2. Tracer = EventBus subscriber (не отдельный механизм)
3. `ConsoleTracer`, `OpenTelemetryTracer`, `LangfuseTracer` (reference), `NoopTracer`
4. Auto-instrumentation через EventBus подписки

**DoD**:
- [ ] Contract: `EventBus`, `Tracer` Protocols
- [ ] Unit: event bus subscribe/emit, tracer spans — 15+ тестов
- [ ] Integration: full turn with tracing — 4+ тестов
- [ ] Docs: event bus guide + tracing guide (Console + OTel + Langfuse) + docstrings

### 8D: RAG / Retriever Protocol (IDEA-028) — NEW

**Приоритет**: Medium | **Сложность**: Low | **~2-3 дня**

> 80% production AI agents используют RAG. Не нужна реализация vector store — нужен Protocol + integration point.

**Scope**:
1. `Retriever` Protocol: `async retrieve(query: str, top_k: int = 5) -> list[Document]`
2. `Document` dataclass: `content: str`, `metadata: dict`, `score: float | None`
3. `RagInputFilter` — реализация `InputFilter` (Phase 7C): перед LLM call → retrieve → inject context
4. `RuntimeConfig.retriever: Retriever | None` (shortcut для RagInputFilter)
5. **НЕ включает**: vector store, embedding adapter, chunking — это user's concern
6. Builtin example: `SimpleRetriever` (in-memory, TF-IDF, для dev/testing)

**Пример**:
```python
# Пользователь приносит свой retriever:
class ChromaRetriever:
    async def retrieve(self, query: str, top_k: int = 5) -> list[Document]:
        results = self.collection.query(query_texts=[query], n_results=top_k)
        return [Document(content=doc, metadata=meta) for doc, meta in zip(results["documents"][0], results["metadatas"][0])]

config = RuntimeConfig(model="claude-sonnet-4-20250514", retriever=ChromaRetriever(collection))
```

**DoD**:
- [ ] Contract: `Retriever`, `Document`
- [ ] `RagInputFilter` — inject retrieved docs into prompt
- [ ] Unit: retriever protocol, rag filter, document — 8+ тестов
- [ ] Integration: retriever + LLM call — 3+ тестов
- [ ] Docs: RAG integration guide + Chroma/Pinecone examples + docstrings

### 8C: UI Event Projection (IDEA-023) — NEW

**Приоритет**: High | **Сложность**: Medium | **~3-4 дня**

> **Источник**: UI Event Projection pattern (stream.md). UI не должен интерпретировать сырые RuntimeEvent — UI получает готовое состояние.

**Проблема**: Сейчас swarmline стримит `RuntimeEvent` (token, tool_call, tool_result, final, error). Каждый frontend должен сам собирать UI state из этих событий — парсить токены в текст, собирать tool results, отслеживать lifecycle. Это:
- Дублирование логики в каждом UI
- Трудно менять event model backend'а
- Невозможно replay/debug UI

**Архитектура**:
```
AgentRuntime.run()
      │
      ▼
RuntimeEvent stream (token, tool_call, tool_result, final, error)
      │
      ▼
EventProjection (NEW — swarmline layer)
      │
      ▼
UIState stream (ready-to-render state updates)
      │
      ▼
Frontend (просто render(state))
```

**Scope**:
1. `EventProjection` Protocol: `apply(event: RuntimeEvent) -> UIState`
2. `ChatProjection` — builtin: собирает RuntimeEvent → messages с text blocks, tool blocks, status
3. `UIState` dataclass: `messages: list[UIMessage]`, `status: str`, `metadata: dict`
4. `UIMessage`: `role, blocks: list[UIBlock]` где UIBlock = TextBlock | ToolCallBlock | ToolResultBlock | ErrorBlock
5. Streaming: `project_stream(events) -> AsyncIterator[UIState]` — стрим готового state
6. **Snapshot**: `UIState` сериализуем → reconnect без replay всех событий
7. **Replay**: прогнать сохранённые events через projection → восстановить UI
8. **Custom projections**: пользователь может написать свой (dashboard projection, analytics projection)

**Пример использования**:
```python
# Без projection (сейчас) — frontend парсит сам:
async for event in runtime.run("Проверь цену SBER"):
    if event.type == "text":
        append_text(event.content)
    elif event.type == "tool_call":
        show_tool(event.tool_name)
    elif event.type == "tool_result":
        show_result(event.result)
    # ... много логики в UI

# С projection (новое) — frontend получает готовый state:
projection = ChatProjection()
async for state in project_stream(runtime.run("Проверь цену SBER"), projection):
    render(state.messages)  # UI просто рендерит
```

**Use cases**:
- Web UI: SSE/WebSocket → UIState → React render
- Mobile: тот же UIState → native render
- Debug console: специальная DebugProjection с трейсингом
- Analytics: MetricsProjection считает tokens/cost/duration
- Multi-client: один event stream → несколько projections для разных UI

**DoD**:
- [ ] Contract: `EventProjection`, `UIState`, `UIMessage`, `UIBlock` Protocols/dataclasses
- [ ] `ChatProjection` builtin — собирает messages из RuntimeEvent stream
- [ ] Unit: all event types → correct UIState — 12+ тестов
- [ ] Unit: snapshot serialization, replay — 6+ тестов
- [ ] Integration: full agent run → ChatProjection → correct final state — 4+ тестов
- [ ] Docs: UI Event Projection guide + React integration example + docstrings
- [ ] Code example: `examples/ui_projection/` (FastAPI + SSE + ChatProjection)
- [ ] **Phase 8 завершение**: CHANGELOG v1.0.0-core, **Full docs site** (mkdocs-material)

---

## Phase 9: Multi-Agent & Task System

> **Layered**: каждый sub-phase имеет **MVP** (в core / simple extra) и **Full** (enterprise extra).
> Пользователь может взять только MVP и это работает.

### 9A: Agent-as-Tool (IDEA-009)

**Приоритет**: Medium | **Сложность**: Medium | **~3-4 дня**

**Зависимости**: нет hard deps (budget attribution — enhancement, добавляется после 7A)

**Scope**:
1. `AgentRuntime.as_tool(name, description) -> ToolSpec`
2. Sub-agent execution, isolation, timeout
3. Budget attribution → optional (если `RuntimeConfig.cost_budget` задан)

**DoD**:
- [ ] Unit: 12+ | Integration: 4+
- [ ] Docs: agent-as-tool guide + code example + docstrings

### 9B: Task System (IDEA-018)

**Приоритет**: High | **Сложность**: Medium → High

> **Два уровня**: MVP в core, Full как `swarmline[tasks]`.

#### 9B-MVP: Simple Task Queue (~2-3 дня)

**В core** — минимальная очередь задач. Достаточно для 80% use cases.

```python
# Всё что нужно для простого агента с задачами:
queue = TaskQueue()
queue.put(Task(title="Review PR #42", priority="high"))
task = queue.get()  # returns highest priority unassigned task
task.status = "done"
queue.complete(task.id)
```

**Scope**:
1. `Task` dataclass: `id, title, description, status, priority, assignee_agent_id, metadata`
2. `TaskStatus`: `todo → in_progress → done | cancelled` (4 статуса, не 7)
3. `TaskQueue`: `put(task)` / `get(filters)` / `complete(id)` / `cancel(id)` / `list(filters)`
4. In-memory backend (default), SQLite backend (optional)
5. Priority sort: critical > high > medium > low
6. Simple assignment: `queue.get(assignee="agent-1")`

**DoD**:
- [ ] Contract: `TaskQueue`, `Task`, `TaskStatus`
- [ ] Unit: CRUD, priority sort, assignment, filtering — 12+ тестов
- [ ] Integration: agent gets task → completes — 3+ тестов
- [ ] Docs: task queue guide + code example + docstrings

#### 9B-Full: Enterprise Task Store (~5-7 дней) — `swarmline[tasks]`

**Optional extra** — для тех, кому нужен Paperclip-level control.

**Scope** (поверх MVP):
1. `CheckoutEngine` — atomic claim, stale adoption, conflict detection
2. Расширенные статусы: + `backlog`, `in_review`, `blocked`
3. `TaskSession` — persistent context per task (not per agent)
4. `parent_id` — дерево подзадач
5. `TaskEvents` — append-only audit log
6. Fulltext search по title + description
7. `created_by_agent_id` — агент создаёт задачи

**DoD**:
- [ ] Unit: checkout, sessions, subtasks, events — 20+ тестов
- [ ] Integration: concurrent checkout, task session handoff — 5+ тестов
- [ ] Docs: enterprise task store guide + docstrings

### 9C: Agent Registry & Hierarchy (IDEA-019)

**Приоритет**: High | **Сложность**: Medium

**Зависимости**: 7A (cost budget) — optional. **НЕ зависит от 9B** (агенты существуют без задач).

> **Два уровня**: MVP simple registry + Full hierarchy.

#### 9C-MVP: Agent Registry (~2-3 дня)

**Scope**:
```python
@dataclass
class AgentConfig:
    id: str
    name: str
    role: str                    # "manager", "engineer", "reviewer"
    parent_id: str | None        # простая иерархия
    runtime_name: str            # "thin", "deepagents", "cli"
    runtime_config: dict         # per-agent settings
    status: AgentStatus          # idle / running / stopped (3 состояния)
    budget_limit_usd: float | None
    metadata: dict
```

1. `AgentRegistry` Protocol: `register(config)` / `get(id)` / `list(filters)` / `update(id, patch)` / `remove(id)`
2. `parent_id` → simple tree (не matrix)
3. Lifecycle: idle ↔ running → stopped (3 состояния)
4. In-memory + SQLite backends

**DoD**:
- [ ] Contract: `AgentRegistry`, `AgentConfig`
- [ ] Unit: CRUD, tree, lifecycle — 12+ тестов
- [ ] Integration: register + lookup — 3+ тестов
- [ ] Docs: agent registry guide + code example + docstrings

#### 9C-Full: Enterprise Hierarchy (~3-4 дня) — `swarmline[multi-agent]`

**Scope** (поверх MVP):
1. `AgentPermissions` — can_create_agents, can_assign_tasks, max_sub_agents
2. Agent creation by agent (with budget inheritance)
3. Cycle detection (max depth)
4. `get_org_chart()` / `get_chain_of_command()`
5. Config versioning + rollback
6. Event hooks: `on_created`, `on_status_changed`

**DoD**:
- [ ] Unit: permissions, agent-creates-agent, cycle detection, versioning — 15+ тестов
- [ ] Integration: parent creates child → assigns task → completes — 4+ тестов
- [ ] Docs: enterprise hierarchy guide + org chart example + docstrings

### 9D: Multi-Agent Delegation (IDEA-006) — `swarmline[multi-agent]`

**Приоритет**: High | **Сложность**: High | **~8-12 дней**

**Зависит от**: 6C (registry), 9A (agent-as-tool), 9C-MVP (agent registry)
**Enhanced by** (optional): 7A (budget), 7B (guardrails), 9B (tasks)

**Scope**:
1. `AgentOrchestrator` — координатор нескольких runtime'ов
2. `DelegationTool` — агент делегирует подзадачу
3. Routing: по имени, по capability, round-robin
4. Result aggregation
5. **Optional**: если TaskStore доступен → delegation создаёт Task. Если нет → inline execution
6. `ConcurrencyGroup` — max_concurrent per group
7. **Error handling strategy**:
   - Sub-agent failure → `DelegationResult(success=False, error=...)` → parent decides
   - Timeout → configurable (retry/fail/fallback)
   - Partial results → `AggregatedResult(completed=[], failed=[])`

**DoD**:
- [ ] Contract: `Orchestrator`, `DelegationTool`, `DelegationResult`
- [ ] Unit: routing, concurrency, aggregation, error handling — 20+ тестов
- [ ] Integration: 2 agents, разные runtime'ы — 4+ тестов
- [ ] E2E: full delegation flow — 2+ тестов
- [ ] Docs: multi-agent delegation guide + error handling guide + code example + docstrings

### 9E: Scheduled / Heartbeat Agents (IDEA-007) — `swarmline[scheduler]`

**Приоритет**: High | **Сложность**: Medium

**Зависит от**: 8A (session backends). **НЕ зависит от 10A (CLI)** — scheduler работает через AgentRuntime Protocol.

> **Два уровня**: MVP simple scheduler + Full production scheduler.

#### 9E-MVP: Simple Scheduler (~3-4 дня)

**Scope**:
1. `AgentScheduler` — asyncio event loop
2. Triggers: `cron(expression)`, `interval(seconds)`, `one_shot(datetime)`, `on_demand()`, `webhook(path)`
3. Run history: simple list (in-memory) или JSONL (persistent)
4. `WakeupContext`: trigger_type, last_run_at, run_number
5. Session: isolated (fresh per run) или named (persistent)
6. Simple loop: trigger → create AgentRuntime → execute → log result

**DoD**:
- [ ] Contract: `Scheduler`, `Trigger`
- [ ] Unit: cron parsing, interval, one-shot — 10+ тестов
- [ ] Integration: scheduled agent wakes up and works — 4+ тестов
- [ ] Docs: scheduler guide + cron examples + docstrings

#### 9E-Full: Production Scheduler (~3-4 дня)

**Scope** (поверх MVP):
1. `WakeupQueue` + `CoalescingEngine` — merge concurrent wakeups
2. `JitterPolicy` — deterministic per-job offset
3. Orphan detection при restart
4. `maxConcurrentRuns` per agent
5. `ContextSinceLastRun` — events catch-up

**DoD**:
- [ ] Unit: coalescing, jitter, orphan detection — 12+ тестов
- [ ] Integration: concurrent wakeups + coalescing — 4+ тестов
- [ ] Docs: production scheduler guide + docstrings

---

## Phase 10: Platform

> 10A (CLI) can start as early as Phase 6C is done — parallel with 7/8.
> 10B-10E are independent.

### 10A: CLI Agent Runtime (IDEA-003)

**Приоритет**: High | **Сложность**: Medium | **~5-7 дней**

**Зависит от**: 6C (adapter registry). **Можно начать параллельно с Phase 7-8**.

**Scope**:
1. `CliAgentRuntime` implements `AgentRuntime`
2. Process lifecycle: spawn, cancel (SIGTERM→SIGKILL), timeout, 4MB cap
3. Stdin-as-prompt, env isolation
4. `NdjsonParser` — pluggable per CLI
5. Session: `--resume <sid>`, compaction, handoff markdown

**Presets: MVP = 2, остальные = community**:
1. **Claude Code**: `claude --print - --output-format stream-json` — primary, полная поддержка
2. **Custom**: user-defined command + args + parser — universal fallback

**Community presets** (docs + examples, не в core):
3. Codex, DeepAgents CLI, Gemini CLI, OpenCode

> **Rationale**: CLI API нестабильны, каждый инструмент меняет формат. Поддержка 6 parser'ов = maintenance burden. Custom preset позволяет пользователю подключить любой CLI. Community contributions для популярных CLI.

**DoD**:
- [ ] Contract: `CliAgentRuntime`, `NdjsonParser`, `SessionCodec`
- [ ] Unit: NDJSON parsing (claude + custom) — 10+ тестов
- [ ] Unit: process lifecycle — 8+ тестов
- [ ] Unit: session codec — 6+ тестов
- [ ] Integration: subprocess mock + full flow — 4+ тестов
- [ ] Docs: CLI runtime guide (Claude Code + custom CLI) + code example + docstrings

### 10B: MCP Multi-Transport (IDEA-014)

**Приоритет**: Medium | **Сложность**: Medium | **~3-4 дня**

**Можно начать параллельно с Phase 8**.

**Scope**: StdioTransport + StreamableHttpTransport + tool list caching.

**DoD**: Unit 12+ | Integration 4+

### 10C: MCP Approval Policies (IDEA-012)

**Приоритет**: Medium | **Сложность**: Low | **~1-2 дня** | Зависит от 10B

### 10D: Credential Proxy (IDEA-020)

**Приоритет**: Medium | **Сложность**: Low | **~2-3 дня**

> Перенесено из Phase 7 (v2) в Phase 10 — это platform feature, не core safety.

**Scope**: `CredentialInjector` Protocol, placeholder → real key, multi-tenant isolation.

**DoD**: Unit 10+ | Integration 3+

### 10E: OAuth Subscription Auth (IDEA-001)

**Приоритет**: Low | **Сложность**: Medium | **~3-4 дня**

> Plugin-level feature. Не в core.

**Scope**: AuthProvider Protocol, token refresh, Bearer auth, CLI flow.

### 10F: RTK Token Optimization (IDEA-017)

**Приоритет**: Low | **Сложность**: Low | **~1-2 дня**

> Plugin-level. Полезно для dev workflow, не core.

**Scope**: `TokenOptimizer` Protocol, `RtkOptimizer` wrapper, toggleable, graceful fallback.

### 10G: `swarmline init` CLI (IDEA-029) — NEW

**Приоритет**: Medium | **Сложность**: Low | **~1-2 дня**

> Mastra: `npx create-mastra@latest`. CrewAI: `crewai create`. У нас — ничего.

**Scope**:
1. `swarmline init [project-name]` — генерирует minimal project
2. Template: `main.py`, `tools.py`, `config.py`, `.env.example`, `pyproject.toml`
3. Интерактивный выбор: runtime (thin/claude_sdk/cli), provider (anthropic/openai/google)
4. Jinja2 templates (встроенные, не external dependency)

**DoD**:
- [ ] CLI command работает: `swarmline init my-agent`
- [ ] Unit: template rendering — 5+ тестов
- [ ] Docs: getting started guide ссылается на `swarmline init`

### 10H: LiteLLM Adapter (IDEA-030) — NEW

**Приоритет**: Low | **Сложность**: Low | **~1-2 дня**

> 100+ LLM providers через один adapter. Не замена собственных, а fallback для exotic providers.

**Scope**:
1. `LiteLLMAdapter` implements `LlmAdapter` — wrapper вокруг `litellm.completion()`
2. Optional extra: `swarmline[litellm]`
3. Все модели доступные через litellm → доступны в swarmline
4. Fallback: если native adapter не найден → попробовать litellm

**DoD**:
- [ ] Unit: adapter creation, model routing — 6+ тестов
- [ ] Integration: litellm call через ThinRuntime — 3+ тестов

---

## Сводная таблица (исправленная)

| Phase | Layer | Идеи | Оценка | Результат |
|-------|-------|------|--------|-----------|
| **6** | Core | 011, 016, 002, 024, 025, cleanup | ~9-12 дн | Structured output + @tool + registry + cancel + ctx manager + typed events |
| **7** | Core | 004, 008+022, 013, 026 | ~10-14 дн | Cost budget + guardrails + input filters + retry/fallback |
| **8** | Core | 010+005+021, 015+027, 023, 028 | ~14-18 дн | Sessions + event bus + tracing + UI projection + RAG + **docs site** |
| **9 MVP** | Core + extras | 009, 018mvp, 019mvp | ~8-10 дн | Agent-as-tool + simple tasks + simple registry |
| **9 Full** | Enterprise | 018full, 019full, 006, 007 | ~20-28 дн | Enterprise tasks + hierarchy + delegation + scheduler |
| **10** | Platform | 003, 014, 012, 020, 001, 017, 029, 030 | ~18-26 дн | CLI + MCP + cred proxy + OAuth + RTK + init + LiteLLM |
| **11** | Ecosystem | OpenAI Agents SDK | ~11-15 дн | 4-й runtime + bridges |

| | | | | |
|--|--|--|--|--|
| **Core total** | | | **~33-44 дн** | **Production-ready library + docs site** |
| **Full total** | | | **~90-123 дн** | **Full platform** |
| **Realistic total** | | | **~115-155 дн** | **С учётом интеграции + docs** |

---

## Критические пути

1. **Core path**: 6A → 7B → 8A → release v1.0-core (~23-31 дн)
2. **Multi-agent path**: 6C → 9A → 9C-MVP → 9D
3. **CLI path**: 6C → 10A (параллелится с 7-8)
4. **Tasks path**: 8A → 9B-MVP → 9B-Full
5. **Scheduler path**: 8A → 9E-MVP → 9E-Full

## Параллелизация (оптимизированная)

```
Week 1-2:   6A + 6B + 6C + 6D (параллельно) + Getting Started doc
Week 3-5:   7A + 7C (параллельно) | 7B после 6A | 10A после 6C ← EARLIER
Week 5-7:   8A + 8B + 8C(projection) (параллельно) | 10B ← EARLIER
Week 7-8:   v1.0-core docs site (mkdocs-material) + release candidate
Week 9-11:  9A + 9B-MVP + 9C-MVP (параллельно)
Week 11-14: 9B-Full + 9C-Full + 9D (9D после 9C-MVP)
Week 14-16: 9E-MVP + 9E-Full + 10C-10F
Week 17-19: Phase 11 (если SDK ≥ v1.0 И Phase 6-8 done)
```

**Ключевое отличие от v2**: 10A и 10B стартуют на 8 недель раньше.

---

## Phase 11: OpenAI Agents SDK Integration

**Условие старта**: OpenAI Agents SDK ≥ v1.0 **И** Phase 6-8 done (не ИЛИ).

### 11A: OpenAI Agents Runtime (~4-5 дн)
### 11B: Session Backends Bridge (~2-3 дн)
### 11C: Structured Output & Guardrails Bridge (~2-3 дн)
### 11D: MCP & Advanced (~3-4 дн)

(Scope не изменился от v2)

---

## API Stability Plan

| Milestone | Что фиксируется | Версия |
|-----------|-----------------|--------|
| Phase 6 done | `AgentRuntime` Protocol, `RuntimeConfig`, `RuntimeEvent`, `ToolSpec` | v0.6.0 |
| Phase 7 done | `Guardrail`, `CostBudget`, `InputFilter` Protocols | v0.7.0 |
| Phase 8 done | `SessionBackend`, `Tracer` Protocols | **v1.0.0-core** |
| Phase 9 MVP done | `TaskQueue`, `AgentRegistry` Protocols | v1.1.0 |
| Phase 9 Full done | `Orchestrator`, `Scheduler` Protocols | v1.2.0 |

> **Rule**: Protocol additions (new optional fields) = minor version. Protocol breaking changes = major version. После v1.0 — semver строго.

---

## RuntimeConfig Evolution Strategy

> **Проблема** (из review): RuntimeConfig растёт с каждой фазой. К Phase 9D — 20+ полей.

**Решение**: Composition через typed config groups, не монолитный dataclass.

```python
# Вместо:
RuntimeConfig(model="...", guardrails=[...], budget=..., tracer=..., ...)

# Используем:
RuntimeConfig(
    model="claude-sonnet-4-20250514",
    safety=SafetyConfig(guardrails=[...], input_filters=[...]),
    budget=CostBudget(max_cost_usd=1.0),
    observability=ObservabilityConfig(tracer=ConsoleTracer()),
)
```

Typed groups: `SafetyConfig`, `CostBudget`, `ObservabilityConfig`, `SessionConfig`.
Flat access: `config.budget.max_cost_usd` (не `config.max_cost_usd`).
Backward compat: top-level aliases для часто используемых полей.

---

## Migration Plan: Existing Code

| Что | Текущее | Целевое | Когда | Подход |
|-----|---------|---------|-------|--------|
| `RuntimePort` | deprecated, 6 файлов | удалён | Phase 6D | Strangler Fig |
| `RuntimeFactory` | hardcoded if/elif | register/get | Phase 6C | Extend, then flip |
| `SessionManager` | in-memory only | pluggable backend | Phase 8A | Add `backend` param, default=InMemory |
| `output_format` | dict JSON Schema | `output_type: BaseModel` | Phase 6A | Add new, alias old |
| `ContextBudget` | context window | coexists with CostBudget | Phase 7A | Different names, different concerns |
| `memory/` stores | inmemory, sqlite, postgres | scoped via SessionBackend | Phase 8A | Adapter pattern |

---

## Multi-Agent Error Handling Strategy

> **Пропущено в v1/v2**, добавлено в v3.

```python
@dataclass
class DelegationResult:
    success: bool
    output: str | None           # result if success
    error: str | None            # error message if failed
    agent_id: str
    tokens_used: int
    cost_usd: float

@dataclass
class AggregatedResult:
    completed: list[DelegationResult]
    failed: list[DelegationResult]
    partial: bool                 # True if some failed
```

**Error policies** (configurable per delegation):
1. `fail_fast` — первый failed sub-agent → abort all, return partial
2. `continue_on_error` — собрать все результаты, failed в `AggregatedResult.failed`
3. `retry_on_error(max_retries=2)` — retry failed sub-agents
4. `fallback(agent_name)` — при failure переключить на fallback agent

---

## Блокеры и риски (обновлённые)

| Риск | Impact | Mitigation |
|------|--------|-----------|
| RuntimeConfig bloat | High | Composition (typed config groups) — Phase 6 |
| SessionManager ↔ SessionBackend conflict | Medium | Migration plan: backend as param |
| Circular imports (orchestration 36 files) | Medium | Strict layering: Domain → App → Infra |
| CLI API instability (Codex, Gemini, etc.) | Medium | Only Claude Code + Custom in core, rest = community |
| OpenAI Agents SDK pre-1.0 | High | Phase 11 gated on v1.0 AND Phase 6-8 |
| Task system overengineering | Medium | MVP-first: TaskQueue → TaskStore layered |
| Multi-agent concurrency | High | Error policies + timeouts + ConcurrencyGroup |
| Test pyramid inversion | Medium | Integration tests для concurrency, не unit с mock |
| Documentation gap | High | Getting Started doc обязателен при v1.0-core |
| Total timeline underestimate | High | Realistic: 100-130 дн (не 75-104) |
