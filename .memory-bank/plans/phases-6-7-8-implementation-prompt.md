# Prompt: Phases 6–8 Full Implementation (DX Foundation → Production Safety → Persistence)

> **Использование**: скопировать весь блок ниже как промт для новой сессии Claude Code.
> **Ожидаемый результат**: полностью реализованные Phases 6, 7, 8 с тестами, ревью и исправлениями.

---

```
# ЗАДАЧА: Реализовать Phases 6, 7, 8 мастер-плана Swarmline (v0.5.0 → v1.0.0-core)

Ты — senior engineer, реализующий core roadmap библиотеки Swarmline.
Перед тобой три фазы. Каждая содержит sub-phases. Работу делаешь строго по порядку,
каждую sub-phase завершая полностью (код + тесты + ревью + исправления) прежде чем перейти к следующей.

## КОНТЕКСТ ПРОЕКТА

**Swarmline** — Python-библиотека (не фреймворк) для AI-агентов. Multi-runtime, protocol-first.
- Версия: 0.5.0. Python ≥3.10. Pydantic ≥2.0.
- Пакет: `src/swarmline/`. Тесты: `tests/{unit,integration,e2e}/`.
- 3 runtime'а: `claude_sdk`, `deepagents`, `thin` (ThinRuntime — собственный loop с 3 LLM адаптерами).
- Ключевые файлы:
  - `src/swarmline/protocols.py` — все Protocol'ы (ISP ≤5 методов)
  - `src/swarmline/runtime/base.py` — `AgentRuntime` Protocol (run + cleanup)
  - `src/swarmline/runtime/types.py` — `RuntimeConfig`, `RuntimeEvent`, `ToolSpec`, `Message`, `TurnMetrics`
  - `src/swarmline/runtime/factory.py` — `RuntimeFactory` (if/elif → будет register/get)
  - `src/swarmline/runtime/structured_output.py` — existing helpers (append instruction, extract JSON)
  - `src/swarmline/runtime/thin/` — ThinRuntime, llm_providers.py (3 адаптера), strategies
  - `src/swarmline/runtime/ports/` — deprecated RuntimePort (удаляем в 6D)
  - `src/swarmline/session/manager.py` — SessionManager (in-memory)
  - `pyproject.toml` — hatchling build, deps: structlog, pyyaml, pydantic

## ПРИНЦИПЫ (ОБЯЗАТЕЛЬНО)

1. **Contract-First + TDD**: Protocol/ABC → contract-тесты → реализация. Тесты ПЕРВЫМИ.
2. **Clean Architecture**: Domain → Application → Infrastructure. Domain = 0 внешних deps.
3. **SOLID**: SRP >300 строк → разделить. ISP ≤5 методов. DIP: конструктор принимает абстракцию.
4. **DRY/KISS/YAGNI**: дубль >2 → извлечь. Не писать код «на будущее».
5. **Testing Trophy**: интеграционные > unit > e2e. Mock только внешние. >5 mock → кандидат на интеграционный.
6. **Coverage**: общий 85%+, core/business 95%+, infrastructure 70%+.
7. **Без placeholder'ов**: никаких TODO, `...`, псевдокода. Код copy-paste ready.
8. **Strangler Fig**: поэтапно, тесты проходят на КАЖДОМ шаге.
9. **Новые библиотеки**: НЕ добавлять без явного разрешения. Использовать stdlib + pydantic.
10. **Защищённые файлы**: `.env`, `ci/**`, Docker/K8s/Terraform — не трогать.
11. **Backward compat**: существующие тесты ДОЛЖНЫ проходить после каждого изменения.

## WORKFLOW КАЖДОЙ SUB-PHASE

Для каждой sub-phase (6A, 6B, ... 8D) выполни строго по порядку:

### Шаг 1: PLAN (2-3 мин)
- Прочитай мастер-план: `.memory-bank/plans/2026-03-18_masterplan_v3.md`
- Прочитай существующий код, который будешь менять
- Составь краткий план: какие файлы создаёшь/меняешь, какие Protocol'ы, какие тесты
- Запиши план в `.memory-bank/checklist.md` (⬜ пункты)

### Шаг 2: CONTRACT (Protocol + types)
- Создай/обнови Protocol'ы и dataclass'ы
- Это public API — продумай naming, типы, docstrings (Google style)
- Размести в правильном месте по Clean Architecture

### Шаг 3: RED (тесты первыми)
- Напиши тесты ДО реализации
- Unit: `tests/unit/test_<feature>.py` — минимум по DoD мастер-плана
- Integration: `tests/integration/test_<feature>.py` — реальные компоненты вместе
- Naming: `test_<что>_<условие>_<результат>`
- Arrange-Act-Assert. `@pytest.mark.parametrize` вместо копипасты
- Запусти — убедись что ВСЕ новые тесты FAIL (red phase)

### Шаг 4: GREEN (минимальная реализация)
- Напиши минимальный код чтобы тесты прошли
- Не добавляй ничего сверх того, что требуют тесты
- Запусти ВСЕ тесты (не только новые) — убедись что ничего не сломал:
  ```bash
  python -m pytest tests/unit/ tests/integration/ -x -q
  ```

### Шаг 5: REFACTOR
- Убери дублирование, улучши naming, проверь SRP/ISP
- Тесты всё ещё зелёные

### Шаг 6: VERIFY (соответствие плану)
- Сверь реализацию с DoD из мастер-плана (`plans/2026-03-18_masterplan_v3.md`)
- Проверь: все ли пункты DoD закрыты? Количество тестов ≥ указанного?
- Coverage ≥ порогов? Backward compat?
- Если нет — вернись к шагу 3 или 4

### Шаг 7: CODE REVIEW
Проведи самостоятельное ревью своего кода. Чеклист:
- [ ] Все Protocol'ы ≤5 методов (ISP)
- [ ] Конструкторы принимают абстракции, не конкретные классы (DIP)
- [ ] Нет файлов >300 строк (SRP) — если есть, разбей
- [ ] Нет дублирования (DRY)
- [ ] Нет unused imports, dead code
- [ ] Error messages на английском
- [ ] Docstrings Google style на все public API
- [ ] Type hints полные (mypy-compatible)
- [ ] Нет security issues (injection, secrets in code)
- [ ] Нет TODO/FIXME/placeholder
- [ ] Backward compat сохранён
Запиши найденные проблемы.

### Шаг 8: FIX
- Исправь все проблемы из ревью
- Запусти тесты снова — всё зелёное
- Обнови checklist.md: ⬜ → ✅

### Шаг 9: ПЕРЕХОД К СЛЕДУЮЩЕЙ SUB-PHASE
- Только после полного завершения текущей

---

## PHASE 6: DX FOUNDATION (~9-12 дней)

### 6A: Structured Output via Pydantic (IDEA-011)

**Что делать**: ДОРАБОТКА существующего кода (`structured_output.py`, `RuntimeConfig.output_format`).

1. Добавить `RuntimeConfig.output_type: type[BaseModel] | None = None`
   - Backward compat: `output_format` остаётся как alias, `output_type` приоритетнее
2. Если `output_type` задан — `model_json_schema()` → передача в LLM (через существующий `append_structured_output_instruction`)
3. Post-validation: `model_validate_json()` в финале + retry до `max_model_retries` (default 3) при невалидном JSON
4. `RuntimeEvent.final(structured_output=parsed_model)` — уже есть поле, формализовать
5. Обновить ThinRuntime и adapter'ы для поддержки нового flow

**Тесты (unit 10+, integration 6+)**:
- Pydantic schema extraction из разных моделей (nested, optional, enum)
- Validation pass (корректный JSON)
- Validation fail + retry (невалидный → retry → success)
- Validation fail exhausted retries → error event
- backward compat: output_format dict всё ещё работает
- Integration: через ThinRuntime с mock adapter — полный flow

**DoD**:
- [ ] `output_type` в RuntimeConfig, backward compat `output_format`
- [ ] Pydantic schema → LLM instruction
- [ ] Post-validation + retry
- [ ] Unit: 10+ тестов
- [ ] Integration: 6+ тестов
- [ ] Coverage 95%+

---

### 6B: Tool Schema Auto-generation (IDEA-016)

**Что делать**: `@tool` декоратор → auto `ToolSpec`.

1. `@tool` декоратор в новом файле `src/swarmline/tools/decorator.py`
2. Type hints → JSON Schema: `str→string`, `int→integer`, `float→number`, `bool→boolean`, `list[X]→array`, `dict→object`, `Optional[X]→nullable`
3. Docstring parsing (Google style) → parameter descriptions
4. Return: `ToolSpec(name=func.__name__, description=first_line_of_docstring, parameters=schema, is_local=True)`
5. Без новых зависимостей: `inspect` + `typing.get_type_hints` + `docstring_parser` из stdlib-стиля парсинга

**Тесты (unit 15+, integration 3+)**:
- Каждый тип маппинга (str, int, float, bool, list, dict, Optional, Union)
- Nested Pydantic model as param
- Default values → не required
- Docstring parsing: Google style, no docstring, partial docstring
- Edge: no type hints, *args, **kwargs → error
- Integration: tool через ThinRuntime

**DoD**:
- [ ] `@tool` декоратор работает
- [ ] Type mapping полный (все Python builtin types + Pydantic)
- [ ] Docstring parsing
- [ ] Unit: 15+ тестов
- [ ] Integration: 3+ тестов

---

### 6C: Extensible Adapter Registry (IDEA-002)

**Что делать**: рефакторинг `RuntimeFactory` (if/elif → register/get).

1. `RuntimeFactory.register(name: str, factory_fn: Callable)` — регистрация
2. `RuntimeFactory.unregister(name: str)` — удаление
3. `RuntimeFactory.list_available() -> list[str]` — список
4. Entry points: `[project.entry-points."swarmline.runtimes"]` для plugin auto-discovery
5. Встроенные (claude_sdk, deepagents, thin) через тот же `register()` при import
6. `create()` → lookup в registry вместо if/elif
7. Backward compat: `RuntimeFactory().create(config)` работает как раньше

**Тесты (unit 12+, integration 3+)**:
- register + create по имени
- unregister → create fails
- list_available содержит builtin'ы
- Duplicate register → raise или overwrite (выбери стратегию)
- create несуществующего → ValueError
- Entry point mock discovery
- Backward compat: старый код без изменений работает

**DoD**:
- [ ] Register/get/list API
- [ ] Entry points discovery
- [ ] Builtin через register
- [ ] Unit: 12+ тестов
- [ ] Integration: 3+ тестов
- [ ] Backward compat

---

### 6D: Legacy Cleanup + Core DX (IDEA-024, IDEA-025)

**Что делать**: самая объёмная sub-phase. Порядок важен (Strangler Fig).

**Порядок работ**:

1. **Typed RuntimeEvent accessors** (безопасно, не ломает ничего):
   - `event.text` → `self.data.get("text", "")`
   - `event.tool_name` → `self.data.get("name", "")`
   - `event.is_final` / `event.is_error` / `event.is_text` → bool helpers
   - `event.data` dict остаётся, accessors = sugar

2. **CancellationToken + cancel()**:
   - `CancellationToken` dataclass: `cancelled: bool`, `cancel()`, `on_cancel(callback)`
   - `AgentRuntime` Protocol: добавить `cancel()` method (с default noop)
   - `RuntimeConfig.cancellation_token: CancellationToken | None`
   - `RuntimeEvent.error(kind="cancelled")` — добавить `"cancelled"` в RUNTIME_ERROR_KINDS
   - ThinRuntime: проверять token на каждой итерации loop

3. **AsyncContextManager**:
   - `AgentRuntime`: добавить `__aenter__`/`__aexit__` в Protocol (default: noop/cleanup)
   - ThinRuntime, ClaudeCodeRuntime, DeepAgentsRuntime: реализовать
   - `async with runtime:` pattern

4. **protocols.py split** (рефакторинг, Strangler Fig):
   - Создать `src/swarmline/protocols/` package
   - Разнести: `memory.py`, `session.py`, `routing.py`, `tools.py`, `runtime.py`
   - `protocols/__init__.py` — re-export всего для backward compat
   - Удалить старый `protocols.py`

5. **RuntimePort removal** (Strangler Fig):
   - Проверить все usages: `runtime/ports/`, `protocols.py`, `session/manager.py`
   - `SessionManager.stream_reply()` → использовать `AgentRuntime` напрямую
   - `SessionState.adapter: RuntimePort` → `runtime: AgentRuntime`
   - Удалить `runtime/ports/` directory
   - Удалить `RuntimePort` из protocols

6. **Version dynamic** + **Error messages English**:
   - `__init__.py`: version из `importlib.metadata.version("swarmline")`
   - Все RuntimeConfig/Factory error messages → English

**Тесты (unit 12+)**:
- Typed event accessors: text, tool_name, is_final, is_error, is_text
- CancellationToken: cancel, callback, check
- cancel() через ThinRuntime → cancelled error event
- AsyncContextManager: enter/exit, cleanup called
- protocols split: все imports работают через старый и новый путь
- RuntimePort removal: SessionManager работает через AgentRuntime

**DoD**:
- [ ] Typed event accessors
- [ ] CancellationToken + AgentRuntime.cancel()
- [ ] AsyncContextManager
- [ ] protocols.py split
- [ ] RuntimePort удалён
- [ ] Version dynamic
- [ ] Error messages English
- [ ] ВСЕ существующие тесты проходят
- [ ] Unit: 12+ новых тестов

---

## PHASE 7: PRODUCTION SAFETY (~10-14 дней)

### 7A: Cost Budget Tracking (IDEA-004)

1. `CostBudget` dataclass: `max_cost_usd`, `max_total_tokens`, `action_on_exceed` (pause/error/warn)
2. `CostTracker`: аккумулирует usage per-session из `TurnMetrics`
3. Pricing table: JSON файл `src/swarmline/runtime/pricing.json` (model → cost per 1M input/output)
4. `RuntimeConfig.cost_budget: CostBudget | None`
5. Pre-call check в ThinRuntime: budget exceeded → `RuntimeEvent.error(kind="budget_exceeded")`
6. Coexistence с существующим `ContextBudget` — разные concerns
7. `RuntimeEvent.final(total_cost_usd=tracker.total_cost)`

**Naming**: `CostBudget` (не `BudgetPolicy`) — отличие от `ContextBudget`.

**Тесты (unit 15+, integration 4+)**:
- CostTracker: accumulate, reset, per-model pricing
- Budget exceeded → error event
- Budget warn → warning event (не блокирует)
- Pricing table load/lookup
- Unknown model → fallback pricing
- Integration: ThinRuntime с budget → exceeded → stops

---

### 7B: Guardrails (IDEA-008 + IDEA-022)

**Зависит от 6A** (structured output для guardrail result validation).

1. `Guardrail` Protocol: `async check(context: GuardrailContext, input: str) -> GuardrailResult`
2. `GuardrailResult`: `passed: bool`, `reason: str | None`, `tripwire: bool = False`
3. `InputGuardrail` / `OutputGuardrail` — маркерные подклассы
4. `RuntimeConfig.input_guardrails: list[InputGuardrail]`, `output_guardrails: list[OutputGuardrail]`
5. Parallel execution: `asyncio.gather(*[g.check(...) for g in guardrails])`
6. Tripwire → `RuntimeEvent.error(kind="guardrail_tripwire")` — добавить в RUNTIME_ERROR_KINDS
7. CallerPolicy как builtin guardrail: `CallerAllowlistGuardrail`
8. Builtins: `ContentLengthGuardrail`, `RegexGuardrail`

**Тесты (unit 15+, integration 4+)**

---

### 7C: Pre-LLM Input Filter (IDEA-013)

1. `InputFilter` Protocol: `async filter(messages, system_prompt, config) -> tuple[messages, system_prompt]`
2. `RuntimeConfig.input_filters: list[InputFilter]`
3. Chain execution: filters applied sequentially before each LLM call
4. Builtins: `MaxTokensFilter`, `SystemPromptInjector`
5. Интеграция в ThinRuntime: после compaction, перед adapter.call()

**Тесты (unit 10+, integration 3+)**

---

### 7D: Retry / Fallback Policy (IDEA-026)

1. `RetryPolicy` Protocol: `should_retry(error: Exception, attempt: int) -> tuple[bool, float]`
2. `ExponentialBackoff`: base=1s, max=60s, jitter=True
3. `ModelFallbackChain`: list of models, при rate limit → next
4. `ProviderFallback`: при provider outage → другой provider
5. `RuntimeConfig.retry_policy: RetryPolicy | None`
6. Wrapper вокруг `adapter.call()` / `adapter.stream()` в ThinRuntime
7. `RuntimeEvent` warning: `kind="retry"`, `attempt=N`, `reason="rate_limit"`

**Тесты (unit 12+, integration 3+)**

---

## PHASE 8: PERSISTENCE & OBSERVABILITY (~14-18 дней)

### 8A: Session Backends + Memory Scopes (IDEA-010 + IDEA-005 + IDEA-021)

**Что делать**: РАСШИРЕНИЕ существующего `SessionManager`, не замена.

1. `SessionBackend` Protocol: `save(key, state)` / `load(key)` / `delete(key)` / `list()`
2. `InMemorySessionBackend` — default (wrap existing behavior)
3. `SqliteSessionBackend` — zero-config, файловый
4. `RedisSessionBackend` — optional `swarmline[redis]`
5. `EncryptedSessionBackend` — overlay (AES-256 через `cryptography` optional dep)
6. `SessionManager(backend=...)` — inject, default = InMemory
7. `MemoryScope` enum: `global_`, `agent`, `shared` — namespace prefix keys
8. Scope enforcement: agent isolation by namespace
9. Backward compat: `SessionManager()` без backend = in-memory как сейчас

**Тесты (unit 18+, integration 6+)**

---

### 8B: Event Bus + Tracing (IDEA-015, IDEA-027)

1. `EventBus` Protocol: `subscribe(event_type, callback)` / `emit(event)` / `unsubscribe()`
2. Event types: `llm_call_start/end`, `tool_call_start/end`, `error`, `final`
3. `InMemoryEventBus` — default, fire-and-forget callbacks
4. `RuntimeConfig.event_bus: EventBus | None`
5. `Tracer` Protocol: `start_span(name, attrs)` / `end_span()` / `add_event()`
6. Tracer = EventBus subscriber
7. `ConsoleTracer`, `OpenTelemetryTracer` (optional otel dep), `NoopTracer`
8. Auto-instrumentation: каждый LLM call, tool call → span через EventBus

**Тесты (unit 15+, integration 4+)**

---

### 8C: UI Event Projection (IDEA-023)

1. `EventProjection` Protocol: `apply(event: RuntimeEvent) -> UIState`
2. `UIState` dataclass: `messages: list[UIMessage]`, `status: str`, `metadata: dict`
3. `UIMessage`: `role: str`, `blocks: list[UIBlock]`
4. `UIBlock` = `TextBlock | ToolCallBlock | ToolResultBlock | ErrorBlock` (dataclasses)
5. `ChatProjection` builtin — собирает RuntimeEvent → messages
6. `project_stream(events: AsyncIterator[RuntimeEvent], projection) -> AsyncIterator[UIState]`
7. Snapshot: `UIState` сериализуем (to_dict/from_dict)
8. Replay: events → projection → UIState

**Тесты (unit 12+ + snapshot 6+, integration 4+)**

---

### 8D: RAG / Retriever Protocol (IDEA-028)

**Зависит от 7C** (InputFilter).

1. `Retriever` Protocol: `async retrieve(query: str, top_k: int = 5) -> list[Document]`
2. `Document` dataclass: `content: str`, `metadata: dict`, `score: float | None`
3. `RagInputFilter` — реализация `InputFilter`: retrieve → inject into messages
4. `RuntimeConfig.retriever: Retriever | None` (shortcut, auto-wraps в RagInputFilter)
5. `SimpleRetriever` builtin: in-memory, TF-IDF-like scoring (для dev/testing)

**Тесты (unit 8+, integration 3+)**

---

## ФИНАЛИЗАЦИЯ PHASE 8

После завершения ВСЕХ sub-phases (8A-8D):

1. **Полный тест-прогон**:
   ```bash
   python -m pytest tests/ -x -q --tb=short
   ```
   Все тесты GREEN. Ноль failures.

2. **Coverage check**:
   ```bash
   python -m pytest tests/ --cov=swarmline --cov-report=term-missing -q
   ```
   Общий ≥85%, core ≥95%.

3. **Финальное ревью всех фаз**:
   - Прочитай КАЖДЫЙ новый/изменённый файл
   - Проверь ISP/DIP/SRP/DRY
   - Проверь backward compat
   - Проверь English error messages
   - Проверь docstrings

4. **Plan verification**:
   - Открой `.memory-bank/plans/2026-03-18_masterplan_v3.md`
   - Пройди КАЖДЫЙ пункт DoD КАЖДОЙ sub-phase
   - Если что-то не закрыто — закрой

5. **Checklist update**:
   - `.memory-bank/checklist.md`: все ⬜ Phase 6-8 → ✅
   - `.memory-bank/STATUS.md`: обновить версию, roadmap, тесты

6. **Version bump**: `pyproject.toml` version → `"1.0.0-core"`

---

## ВАЖНЫЕ ОГРАНИЧЕНИЯ

- **НЕ трогай**: `.env`, `ci/`, Docker, Terraform, `.github/`
- **НЕ добавляй библиотеки** без явной необходимости (stdlib + pydantic + structlog + pyyaml уже есть)
- **НЕ ломай** существующие тесты — проверяй после КАЖДОГО изменения
- **НЕ пиши TODO/FIXME** — код должен быть готов
- **НЕ рефактори** код, не связанный с текущей sub-phase
- **НЕ делай** Phase 9+ — только 6, 7, 8
- **Коммиты**: после каждой sub-phase делай git commit с описательным сообщением
- При ЛЮБОМ сомнении — сначала прочитай существующий код, потом действуй
```

---

**Примечания к промту:**

- Промт самодостаточен: содержит все пути, контракты, DoD, workflow
- Порядок sub-phases учитывает зависимости (7B→6A, 8D→7C)
- Каждая sub-phase проходит полный цикл TDD + review + fix
- Финализация Phase 8 включает cross-phase verification
- Ограничения предотвращают scope creep и случайные поломки
