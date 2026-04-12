# OpenAI Agents SDK — Research Report

**Дата**: 2026-03-17
**Версия SDK на момент исследования**: 0.12.3 (released 2026-03-16)
**PyPI**: `openai-agents`
**Репозиторий**: https://github.com/openai/openai-agents-python
**Документация**: https://openai.github.io/openai-agents-python/

---

## Обзор

OpenAI Agents SDK — "lightweight yet powerful framework for building multi-agent workflows" от OpenAI. Позиционируется как Python-first фреймворк с минимальным набором примитивов. Первый релиз — март 2025 (v0.0.1), активная разработка: 13+ релизов за последние 3 недели, частота ~1-2 релиза в неделю.

Ключевые характеристики:
- Три базовых примитива: **Agent**, **Handoff**, **Guardrail**
- Встроенный agent loop (не нужно писать самому)
- Нативная поддержка MCP (5 transport вариантов)
- Multi-provider через LiteLLM (100+ провайдеров)
- Structured output через Pydantic
- Сессии с несколькими backend (SQLite, Redis, PostgreSQL, Dapr, OpenAI API)
- Встроенный tracing (OpenAI Traces dashboard)

---

## Архитектура и абстракции

### Основные классы

**`Agent[TContext]`** — центральная единица. Параметры:

| Параметр | Назначение |
|----------|-----------|
| `name` | Человекочитаемое имя |
| `instructions` | System prompt (статический или `callable(context, agent) -> str`) |
| `model` | Модель (строка или Model объект) |
| `model_settings` | `ModelSettings(temperature, top_p, tool_choice, ...)` |
| `tools` | Список `FunctionTool` / hosted tools |
| `mcp_servers` | Список MCP-серверов (инструменты из них автодобавляются) |
| `handoffs` | Список агентов или `Handoff` объектов для делегирования |
| `input_guardrails` | Валидация входа (параллельно или блокирующий режим) |
| `output_guardrails` | Валидация выхода |
| `output_type` | Pydantic модель / TypedDict / dataclass для структурированного вывода |
| `hooks` | Lifecycle callbacks (`AgentHooks`) |
| `tool_use_behavior` | `"run_llm_again"` (default) / `"stop_on_first_tool"` / `StopAtTools([...])` |

**`Runner`** — запускает агентный loop:
- `Runner.run(agent, input, ...)` — async, возвращает `RunResult`
- `Runner.run_sync(...)` — sync wrapper
- `Runner.run_streamed(...)` — async streaming, возвращает `RunResultStreaming`

**`RunConfig`** — глобальные настройки run: model defaults, tracing, guardrails на уровне run, error handlers.

**`Handoff`** — делегирование задачи другому агенту. Представляется LLM как tool (`transfer_to_<agent_name>`). Поддерживает:
- `input_type` — Pydantic модель для structured input при передаче
- `on_handoff` — callback при активации
- `input_filter` — фильтрация истории для принимающего агента
- `is_enabled` — динамическое включение/отключение

**`Guardrail`** — функция `async (context, agent, input) -> GuardrailFunctionOutput`. Имеет tripwire механизм: если `tripwire_triggered=True`, бросается исключение (`InputGuardrailTripwireTriggered` / `OutputGuardrailTripwireTriggered`). Типичный паттерн — использовать быструю/дешёвую модель для проверки.

**Tools:**
- `@function_tool` — декоратор, автогенерация JSON schema из Python signature + docstring (griffe)
- `FunctionTool` — ручное создание
- `WebSearchTool`, `FileSearchTool`, `CodeInterpreterTool`, `ImageGenerationTool` — hosted на OpenAI
- `HostedMCPTool` — MCP через OpenAI infrastructure
- `ComputerTool`, `ShellTool`, `ApplyPatchTool` — локальное выполнение
- `agent.as_tool()` — агент как инструмент без handoff (оркестрация через tool-calling)

**`RunContextWrapper[T]`** — обёртка для передачи контекста в tools:
- `wrapper.context` — пользовательский объект (mutable state, DI)
- `wrapper.usage` — агрегированные метрики токенов
- `wrapper.approve_tool()` / `wrapper.reject_tool()` — HITL approval

---

## Runtime Model

### Agent Loop

```
Input → [Input Guardrails] → LLM call
                                 ↓
                     ┌─── Final text output → [Output Guardrails] → RunResult
                     ├─── Tool calls → execute tools → back to LLM
                     └─── Handoff → switch agent → back to LLM
```

Условие завершения: LLM возвращает текстовый ответ нужного типа без tool calls. При превышении `max_turns` бросается `MaxTurnsExceeded`.

### Streaming Events

`Runner.run_streamed()` возвращает `RunResultStreaming` с методом `.stream_events()`. События: дельты текста, tool calls, handoffs, guardrail tripwires, финальный результат.

Для WebSocket транспорта (Realtime): `responses_websocket_session()` — переиспользование соединения между run'ами.

### Context Management

Контекст (`contextvar` на уровне Python) передаётся через `RunContextWrapper[T]`. Строго типизированный: все агенты, tools и hooks в одном run должны использовать один тип контекста. Контекст НЕ отправляется в LLM — только локальный объект для кода.

### State Management (4 стратегии)

| Стратегия | Хранение | Применение |
|-----------|---------|-----------|
| `result.to_input_list()` | Память приложения | Ручной контроль |
| `session=...` | Custom backend | Persistent chat |
| `conversation_id` | OpenAI API | Named conversations |
| `previous_response_id` | OpenAI API | Lightweight chaining |

### Hooks / Lifecycle

- `call_model_input_filter` — редактирует подготовленный input непосредственно перед LLM вызовом (trimming истории, prompt injection)
- `error_handlers` — словарь: тип ошибки → fallback output вместо исключения
- `AgentHooks` — per-agent lifecycle: on_start, on_tool_call, on_handoff, on_end

---

## Provider Support (multi-provider?)

### Поддерживаемые провайдеры

**Нативно (OpenAI):**
- `OpenAIResponsesModel` (рекомендуемый) — OpenAI Responses API
- `OpenAIChatCompletionsModel` — Chat Completions API
- Default модель: `gpt-4.1` (рекомендуется `gpt-5.4` когда доступна)

**Через LiteLLM** (`pip install "openai-agents[litellm]"`):
- Anthropic: `litellm/anthropic/claude-3-5-sonnet-20240620`
- Google: `litellm/gemini/gemini-2.5-flash-preview-04-17`
- 100+ провайдеров через единый интерфейс

**Через OpenAI-совместимые API** (`set_default_openai_client()` с кастомным `base_url`):
- Ollama, vLLM, Together AI, Groq и другие

**`MultiProvider`** — prefix-based routing: `openai/gpt-4.1`, `anthropic/claude-3-5-sonnet` и т.д.

### Ограничения non-OpenAI провайдеров

При использовании не-OpenAI провайдеров недоступно:
- Responses API (только Chat Completions)
- Structured outputs / JSON schema validation (зависит от провайдера)
- Multimodal inputs
- Hosted tools: FileSearch, WebSearch, CodeInterpreter
- `ToolSearchTool` (deferred tool loading)

### Tracing с non-OpenAI

Tracing отправляется на OpenAI Traces. При отсутствии OpenAI ключа: либо `set_tracing_disabled(True)`, либо отдельный ключ только для трейсинга через `set_tracing_export_api_key()`.

---

## MCP Integration

5 вариантов подключения MCP серверов:

| Класс | Transport | Применение |
|-------|-----------|-----------|
| `HostedMCPTool` | OpenAI infrastructure | Публичные серверы через OpenAI |
| `MCPServerStreamableHttp` | HTTP Streamable | Self-hosted, рекомендуемый |
| `MCPServerSse` | SSE (deprecated) | Legacy интеграции |
| `MCPServerStdio` | stdin/stdout | Локальные процессы, POC |
| `MCPServerManager` | Unified | Управление несколькими серверами |

Добавляются в `Agent(mcp_servers=[...])`. Инструменты из MCP-серверов работают идентично function tools.

**Возможности:**
- `list_tools()` с кешированием (`cache_tools_list=True`)
- Статические фильтры: allow/block lists (`create_static_tool_filter()`)
- Динамические фильтры: `callable(ToolFilterContext) -> bool`
- Approval policies: per-tool "always"/"never" или callback
- Metadata injection: `tool_meta_resolver` — вставка `_meta` в каждый вызов (tenant ID, trace context)
- Prompt support: `list_prompts()` / `get_prompt()` для динамических инструкций
- Автоматический tracing MCP вызовов

---

## Extensibility

### LLM Client подмена

Три уровня:
1. Глобально: `set_default_openai_client(AsyncOpenAI(base_url=..., api_key=...))`
2. На уровне Runner: `ModelProvider` через `RunConfig(model_provider=...)`
3. На уровне Agent: `Agent(model=CustomModelInstance)` — реализовать `Model` interface

### Custom Tools

- `@function_tool` + любая async Python функция
- `FunctionTool(name, description, params_json_schema, on_invoke_tool)` — ручное создание
- `agent.as_tool()` — агент как инструмент

### Middleware / Hooks

- `call_model_input_filter` в `RunConfig` — pre-LLM трансформация
- `AgentHooks` — lifecycle callbacks per agent
- `error_handlers` — custom fallbacks
- `handoff_input_filter` — фильтрация истории при handoff
- `output_guardrails` / `input_guardrails` — валидационные цепочки

### Memory / Sessions

Pluggable backends через `Session` interface:
- SQLiteSession / AsyncSQLiteSession
- RedisSession
- SQLAlchemySession (PostgreSQL, MySQL)
- DaprSession (30+ cloud state stores)
- EncryptedSession (overlay поверх любого backend)
- OpenAIConversationsSession / OpenAIResponsesCompactionSession
- AdvancedSQLiteSession (branching, analytics)

---

## Зависимости и размер

**Wheel**: 449 KB, **sdist**: 2.6 MB

**Обязательные зависимости:**
```
openai>=2.26.0,<3
pydantic>=2.12.2,<3
griffe>=1.5.6,<2          # docstring parsing для tool schemas
typing-extensions>=4.12.2
requests>=2.0
types-requests>=2.0
mcp>=1.19.0,<2            # MCP protocol (Python 3.10+)
```

**Опциональные extras:**
```
[litellm]    litellm>=1.81.0    # 100+ LLM провайдеров
[redis]      redis>=7
[sqlalchemy] SQLAlchemy>=2.0, asyncpg>=0.29.0
[realtime]   websockets>=15.0
[voice]      numpy>=2.2, websockets>=15.0
[encrypt]    cryptography>=45.0
[dapr]       dapr>=1.16.0, grpcio>=1.60.0
[viz]        graphviz>=0.17
```

**Python**: 3.10+

**Вес в сравнении**: Базовая установка (без extras) тянет `openai`, `pydantic`, `mcp`. Это умеренно — нет LangChain, нет тяжёлого граф-фреймворка. С `[litellm]` добавляется тяжёлый litellm (~100+ транзитивных зависимостей).

---

## Зрелость и стабильность

**Версия**: 0.12.3 (pre-1.0, нет SemVer гарантий стабильности API)
**Первый релиз**: Март 2025 (v0.0.1)
**Возраст**: ~1 год
**Активность**: ~1-2 релиза в неделю (высокая)
**Лицензия**: MIT

**Оценка стабильности:**
- API активно меняется: за последние 3 недели (v0.10.2 → v0.12.3) было 13+ релизов
- Значительные изменения: `ComputerTool` перешёл в GA только в v0.11.0, `ToolSearchTool` добавлен в v0.11.0
- Pre-1.0 — breaking changes возможны между minor версиями
- Официальный продукт OpenAI → хорошая поддержка, но привязка к OpenAI экосистеме

**Признаки зрелости:**
- Полная документация с примерами
- 9 session backends из коробки
- Production-ready features: retry, compaction, encryption, distributed state (Dapr)
- Активное сообщество

---

## Сравнение с deepagents

**deepagents 0.4.11** — LangChain/LangGraph-based agent harness, используется в swarmline как `DeepAgentsRuntime`.

### Табличное сравнение

| Критерий | openai-agents 0.12.x | deepagents 0.4.11 |
|----------|---------------------|-------------------|
| **Базовый фреймворк** | Собственный (Python-first) | LangChain + LangGraph |
| **Multi-agent** | Handoffs + as_tool() | LangGraph граф |
| **Orchestration модель** | Декларативный (конфиг агентов) | Граф с явными рёбрами |
| **Provider support** | OpenAI + LiteLLM (100+) | Любой LangChain LLM |
| **MCP** | Нативный (5 транспортов) | Через community packages |
| **Guardrails** | Встроенные (input/output/tool) | Нет (нужно вручную) |
| **Structured output** | Pydantic out-of-the-box | Через output parsers |
| **Tracing** | Встроенный (OpenAI Traces) | LangSmith / сторонний |
| **Session backends** | 9 вариантов из коробки | Нет (нужно вручную) |
| **Streaming** | Первоклассная поддержка | Через LangChain callbacks |
| **Зависимости** | Лёгкие (без LangChain) | Тяжёлые (весь LangChain стек) |
| **Стабильность API** | Pre-1.0, активно меняется | 0.4.x, более стабильный |
| **Привязка к OpenAI** | Умеренная (Tracing → OpenAI) | Нет привязки |
| **Кастомизация графа** | Нет (flat handoffs) | Полный LangGraph |
| **Python версия** | 3.10+ | Зависит от deepagents |
| **Размер** | ~450 KB wheel | Тяжелее (LangChain) |

### Плюсы openai-agents vs deepagents

1. **Меньше зависимостей**: нет LangChain/LangGraph, проще деплой
2. **Нативный MCP**: 5 transport вариантов, фильтрация, approval policies — у deepagents нет
3. **Встроенные guardrails**: tripwire механизм из коробки
4. **Session management**: 9 backend вариантов, deepagents требует кастомной реализации
5. **Structured output**: через Pydantic нативно, не через output parsers
6. **Hosted tools**: WebSearch, FileSearch, CodeInterpreter на стороне OpenAI
7. **Retry settings**: `ModelSettings` с retry из коробки (v0.12.0)

### Минусы openai-agents vs deepagents

1. **Graф-оркестрация отсутствует**: handoffs — flat, нет циклов с условиями как в LangGraph. Для сложных workflow нужен ручной control flow
2. **Tracing привязан к OpenAI**: для не-OpenAI моделей нужен отдельный ключ или отключать
3. **Pre-1.0 API нестабильность**: breaking changes возможны
4. **Возраст**: 1 год vs deepagents с более длинной историей
5. **Не подходит для LangChain экосистемы**: нельзя переиспользовать LangChain инструменты напрямую
6. **Ограничения non-OpenAI**: structured outputs, multimodal — только с OpenAI моделями

---

## Выводы: пригодность для интеграции

### Контекст swarmline

Swarmline уже имеет:
- `AgentRuntime` Protocol (base.py) — абстракция, за которой может жить любой runtime
- `DeepAgentsRuntime` через `RuntimeFactory`
- `ThinRuntime` — собственный loop
- `ClaudeCodeRuntime` — основной path
- Middleware chain, hooks, HITL, session management (своя реализация)

### Сценарии интеграции

**Вариант A: Добавить `OpenAIAgentsRuntime` как 4-й runtime**

Плюсы:
- Получаем нативный MCP с approval policies, кеширование tool list
- Guardrails out-of-the-box
- 9 session backends (при необходимости)
- Hosted tools (WebSearch, FileSearch)

Минусы:
- Дублирует часть функционала ThinRuntime/DeepAgentsRuntime
- Tracing идёт в OpenAI Traces (не наш backend)
- API меняется быстро (pre-1.0) — maintenance burden
- Зависимость от `openai>=2.26.0` — возможен конфликт с текущим `openai` пакетом

**Вариант B: Использовать только отдельные компоненты**

Например, только `MCPServerStdio/MCPServerStreamableHttp` для улучшения MCP интеграции в ThinRuntime, или `@function_tool` schema generation вместо ручных ToolSpec.

Минусы: тянем зависимость ради части функционала.

**Вариант C: Ждать 1.0 и изучить повторно**

Учитывая темп изменений (13 релизов за 3 недели), API стабилизируется к 1.0. Текущий риск adoption — высокий.

### Рекомендация

**Не интегрировать openai-agents как runtime сейчас** по следующим причинам:

1. **Архитектурный конфликт**: swarmline уже решила задачи guardrails, sessions, MCP через свои абстракции. openai-agents дублирует их с другим API.

2. **Нестабильность API**: pre-1.0 с 13+ релизами за 3 недели — высокий риск breaking changes при апгрейде.

3. **Tracing lock-in**: встроенный трейсинг завязан на OpenAI Traces — не вписывается в multi-provider архитектуру swarmline.

4. **Граф-оркестрация**: openai-agents не заменяет LangGraph для сложных workflow. deepagents остаётся лучше для graph-based orchestration.

**Что стоит рассмотреть точечно:**

- **Session backends** (RedisSession, DaprSession) — если понадобится production-grade persistence без написания своего
- **MCP transport классы** (`MCPServerStreamableHttp`, `MCPServerStdio`) — как reference реализации при улучшении MCP слоя в swarmline
- **Schema generation** из `griffe` (docstring parsing) — если захочется улучшить автогенерацию ToolSpec

**Переоценить в**: после выхода v1.0 или когда deepagents 0.5.0 окажется недостаточным для требуемых сценариев.
