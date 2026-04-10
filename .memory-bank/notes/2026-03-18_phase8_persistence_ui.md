# Phase 8: Persistence & UI (v1.0.0-core)

## Обзор

Phase 8 добавляет четыре ортогональных слоя поверх ядра ThinRuntime:

1. **Session Backends** — pluggable persistence для session state (InMemory / SQLite)
2. **EventBus + Tracer** — pub-sub шина событий и структурированный трейсинг спанов
3. **UI Projection** — трансформация `RuntimeEvent` stream в `UIState` для фронтенда
4. **RAG** — retrieval-augmented generation через `InputFilter` протокол

Все компоненты подключаются через `RuntimeConfig` и/или используются независимо.
Обратная совместимость сохраняется (все поля опциональны).

---

## Модуль: `session/backends.py`

### Назначение

Pluggable хранилище session state с поддержкой изоляции через namespace-префиксы (`MemoryScope`).
Заменяет предыдущий InMemorySessionManager без внешних зависимостей (SQLite встроен в stdlib).

### Public API

| Сущность | Тип | Описание |
|---|---|---|
| `SessionBackend` | Protocol | 4 метода: `save`, `load`, `delete`, `list_keys` |
| `MemoryScope` | str Enum | `GLOBAL` / `AGENT` / `SHARED` |
| `scoped_key(scope, key)` | function | Создаёт namespace-префиксированный ключ |
| `InMemorySessionBackend` | class | Dict-based, без external deps, не персистирует |
| `SqliteSessionBackend` | class | SQLite-based, file-based, персистирует между запусками |

**`SessionBackend` Protocol:**
```python
async def save(self, key: str, state: dict[str, Any]) -> None
async def load(self, key: str) -> dict[str, Any] | None
async def delete(self, key: str) -> bool   # True если запись существовала
async def list_keys(self) -> list[str]
```

**`MemoryScope` значения и prefix-формат:**

| Scope | Prefix | Пример ключа |
|---|---|---|
| `GLOBAL` | `global:` | `global:session:user1` |
| `AGENT` | `agent:` | `agent:session:user1` |
| `SHARED` | `shared:` | `shared:session:user1` |

**`SqliteSessionBackend`:**
- DDL создаётся при первом подключении: `CREATE TABLE IF NOT EXISTS sessions (key TEXT PRIMARY KEY, state TEXT NOT NULL)`
- State сериализуется как JSON (`json.dumps` / `json.loads`)
- `INSERT OR REPLACE` — save всегда перезаписывает
- `close()` — явное закрытие соединения (нужно вызывать в тестах и при завершении)

### Пример использования

```python
from cognitia.session.backends import (
    SqliteSessionBackend, MemoryScope, scoped_key
)

backend = SqliteSessionBackend(db_path="sessions.db")

# Изолированные ключи для разных агентов
key = scoped_key(MemoryScope.AGENT, "user:42:session:abc")  # "agent:user:42:session:abc"
await backend.save(key, {"role": "coach", "turn": 7})

state = await backend.load(key)  # {"role": "coach", "turn": 7}
backend.close()
```

### Архитектурные решения

- `MemoryScope` наследует `str` + `Enum` — значение работает как обычная строка (удобен в f-strings)
- `scoped_key` — чистая функция, не метод класса (тестируется независимо)
- SQLite соединение создаётся в `__init__` (не lazy) — ошибки конфигурации fail-fast
- Async API с синхронной SQLite реализацией внутри — допустимо для single-threaded async (SQLite I/O минимальный)
- Swap pattern: данные можно скопировать из InMemory в SQLite через `list_keys` + `load` + `save`

### Интеграция с SessionManager

`InMemorySessionManager` принимает опциональный `backend: SessionBackend` аргумент.
При `register()` и `close()` SessionManager синхронизирует состояние с backend.
Без backend аргумента — работает как раньше (backward compat).

---

## Модуль: `observability/event_bus.py`

### Назначение

Легковесная pub-sub шина для внутренних runtime событий. Позволяет подписчикам (tracing, metrics,
UI) получать события от ThinRuntime без прямой связи с ним. Fire-and-forget: ошибки в callback
не прерывают выполнение.

### Public API

| Сущность | Тип | Описание |
|---|---|---|
| `EventBus` | Protocol | `subscribe`, `unsubscribe`, `emit` |
| `InMemoryEventBus` | class | Default реализация, fire-and-forget async callbacks |

**`EventBus` Protocol:**
```python
def subscribe(self, event_type: str, callback: Callable[..., Any]) -> str  # sub_id
def unsubscribe(self, subscription_id: str) -> None
async def emit(self, event_type: str, data: dict[str, Any]) -> None
```

**`InMemoryEventBus` поведение:**
- Callbacks поддерживают sync и async (определяется через `asyncio.iscoroutine`)
- Ошибки в callback перехватываются и игнорируются (`except Exception: pass`)
- Subscription ID — строки вида `sub_0`, `sub_1`, ... (счётчик)
- `unsubscribe` с несуществующим ID — no-op

**События ThinRuntime (emitted автоматически при `event_bus` в RuntimeConfig):**

| event_type | Когда | Поля data |
|---|---|---|
| `llm_call_start` | Перед LLM запросом | `model`, ... |
| `llm_call_end` | После LLM ответа | `model`, `tokens`, ... |
| `tool_call_start` | Перед вызовом tool | `name`, ... |
| `tool_call_end` | После вызова tool | `name`, `ok`, ... |

### Пример использования

```python
from cognitia.observability.event_bus import InMemoryEventBus
from cognitia.runtime.types import RuntimeConfig

bus = InMemoryEventBus()
metrics: list[dict] = []
bus.subscribe("llm_call_end", lambda d: metrics.append(d))

config = RuntimeConfig(runtime_name="thin", event_bus=bus)
```

### Архитектурные решения

- Protocol вместо ABC — позволяет сторонним реализациям (OpenTelemetry bridge, etc.) без наследования
- Fire-and-forget семантика — ошибки в subscribers не ломают основной runtime flow
- Итерация по `list(subscribers.values())` при emit — защита от модификации dict во время итерации

---

## Модуль: `observability/tracer.py`

### Назначение

Структурированный трейсинг выполнения через span-based интерфейс. `TracingSubscriber` служит
bridge между `EventBus` и `Tracer`, превращая runtime events в spans автоматически.

### Public API

| Сущность | Тип | Описание |
|---|---|---|
| `Tracer` | Protocol | `start_span`, `end_span`, `add_event` |
| `NoopTracer` | class | Заглушка, возвращает dummy span IDs |
| `ConsoleTracer` | class | Логирует через structlog, хранит spans в `_spans` dict |
| `TracingSubscriber` | class | Bridge EventBus → Tracer |

**`Tracer` Protocol:**
```python
def start_span(self, name: str, attrs: dict[str, Any] | None = None) -> str  # span_id
def end_span(self, span_id: str) -> None
def add_event(self, span_id: str, name: str, attrs: dict[str, Any] | None = None) -> None
```

**`ConsoleTracer` детали:**
- Span ID: `span_{counter}_{uuid_hex6}` — уникальны в рамках экземпляра
- Хранит spans в `self._spans` dict (для introspection в тестах)
- Логирует через structlog: `span_start`, `span_end` (с `duration_ms`), `span_event`
- `duration_ms` вычисляется через `time.monotonic()`

**`TracingSubscriber` подписки:**

| Event | Action |
|---|---|
| `llm_call_start` | `start_span("llm_call", data)` |
| `llm_call_end` | `add_event(...) + end_span(...)` |
| `tool_call_start` | `start_span("tool_call", data)`, ключ `tool_call:{name}` |
| `tool_call_end` | `add_event(...) + end_span(...)` |

### Пример использования

```python
from cognitia.observability.event_bus import InMemoryEventBus
from cognitia.observability.tracer import ConsoleTracer, TracingSubscriber
from cognitia.runtime.types import RuntimeConfig

bus = InMemoryEventBus()
tracer = ConsoleTracer()
subscriber = TracingSubscriber(bus, tracer)
subscriber.attach()  # подписывается на bus

config = RuntimeConfig(runtime_name="thin", event_bus=bus, tracer=tracer)
# После выполнения: tracer._spans содержит все created spans
subscriber.detach()  # снимает подписку
```

### Архитектурные решения

- `TracingSubscriber.attach()` / `detach()` — явный lifecycle, не в `__init__` (можно переиспользовать)
- Concurrent spans поддерживаются: `tool_call:{name}` как ключ позволяет параллельные tool spans
- `NoopTracer` — для production без трейсинга, нет overhead
- `RuntimeConfig.tracer: Tracer | None` — default `None`; если задан без `event_bus`, TracingSubscriber
  не создаётся автоматически (нужен явный `attach`)

---

## Модуль: `ui/projection.py`

### Назначение

Трансформация потока `RuntimeEvent` в `UIState` — сериализуемый снапшот состояния UI.
Реализует паттерн Event Sourcing: состояние UI строится путём последовательного применения событий.
Пригоден для chat UI, dashboards, логирования.

### Public API

**UIBlock — union type (все frozen dataclass):**

| Тип | Поля | Когда |
|---|---|---|
| `TextBlock` | `text: str` | Ответ ассистента (накапливается из deltas) |
| `ToolCallBlock` | `name`, `args`, `correlation_id` | Инициация вызова tool |
| `ToolResultBlock` | `name`, `ok`, `summary`, `correlation_id` | Результат tool |
| `ErrorBlock` | `kind`, `message` | Ошибка в процессе |

**Контейнеры:**

| Сущность | Тип | Описание |
|---|---|---|
| `UIMessage` | dataclass | `role: str`, `blocks: list[UIBlock]`, `timestamp: float\|None` |
| `UIState` | dataclass | `messages: list[UIMessage]`, `status: str`, `metadata: dict` |

**`UIState` методы:**
- `to_dict() -> dict` — JSON-сериализуемый dict с type discriminator в каждом block
- `UIState.from_dict(d)` — десериализация обратно

**Протокол и реализация:**

| Сущность | Тип | Описание |
|---|---|---|
| `EventProjection` | Protocol | `def apply(event: RuntimeEvent) -> UIState` |
| `ChatProjection` | class | Builtin реализация для chat-style UI |
| `project_stream` | async generator | `(events, projection) -> AsyncIterator[UIState]` |

**`ChatProjection` маппинг событий:**

| RuntimeEvent.type | Действие |
|---|---|
| `assistant_delta` | Накапливает текст в последний `TextBlock` или создаёт новый |
| `tool_call_started` | Добавляет `ToolCallBlock` |
| `tool_call_finished` | Добавляет `ToolResultBlock` |
| `error` | Добавляет `ErrorBlock` |
| `status` | Обновляет `UIState.status` |
| `final` | Устанавливает `status="done"`, копирует metadata (`session_id`, `total_cost_usd`, etc.) |

### Пример использования

```python
from cognitia.ui.projection import ChatProjection, project_stream

projection = ChatProjection()

# Вариант 1: применять события по одному
for event in events:
    state = projection.apply(event)

# Вариант 2: async stream
async for state in project_stream(runtime.run(...), projection):
    print(state.status, state.messages)

# Сериализация для фронтенда
payload = state.to_dict()  # JSON-ready
restored = UIState.from_dict(payload)
```

### Архитектурные решения

- Handler dispatch через dict `_EVENT_HANDLERS` (не if/elif цепочка — OCP-friendly, легко расширить)
- `TextBlock` frozen, но накапливается через замену: `msg.blocks[-1] = TextBlock(old.text + delta)`
- `ChatProjection` мутирует внутренний `UIState` — намеренно, для эффективного накопления
- `project_stream` — чистая функция-генератор, работает с любой `EventProjection` реализацией
- Сериализация с type discriminator (`"type": "text"` и т.д.) — стандартный tagged union pattern

---

## Модуль: `rag.py`

### Назначение

Retrieval-Augmented Generation — инъекция релевантных документов в system prompt перед LLM-вызовом.
`RagInputFilter` реализует `InputFilter` Protocol и встраивается в input_filters цепочку.
`SimpleRetriever` — builtin реализация для разработки/тестирования на основе word overlap.

### Public API

| Сущность | Тип | Описание |
|---|---|---|
| `Document` | frozen dataclass | `content: str`, `metadata: dict`, `score: float\|None` |
| `Retriever` | Protocol | `async def retrieve(query, top_k=5) -> list[Document]` |
| `SimpleRetriever` | class | In-memory retrieval по word overlap (для dev/test) |
| `RagInputFilter` | class | InputFilter: извлекает запрос из last user message, инжектирует `<context>` в system prompt |

**`SimpleRetriever` алгоритм:**
- Query и document content приводятся к lowercase, разбиваются по пробелам
- Relevance score = сумма `min(query_count[w], doc_count[w])` для пересекающихся слов
- Результаты sorted по score descending, ограничены `top_k`
- Пустой query → пустой список

**`RagInputFilter` поведение:**
- Query = текст последнего сообщения с `role="user"`
- Если нет user messages или нет совпадений — возвращает без изменений
- Инжектирует как `<context>\n...\n</context>\n{system_prompt}`
- Messages не изменяются (возвращает тот же объект)

**ThinRuntime auto-wrap:**
- Если `RuntimeConfig.retriever` задан и в `input_filters` нет `RagInputFilter` —
  ThinRuntime автоматически prepend-ит `RagInputFilter(retriever)` в цепочку фильтров
- Если `RagInputFilter` уже есть — дубликат не создаётся

### Пример использования

```python
from cognitia.rag import Document, SimpleRetriever, RagInputFilter
from cognitia.runtime.types import RuntimeConfig

docs = [
    Document(content="Paris is the capital of France", metadata={"src": "geo"}),
    Document(content="Python was created by Guido van Rossum"),
]
retriever = SimpleRetriever(documents=docs)

# Вариант 1: через RuntimeConfig.retriever (auto-wrap)
config = RuntimeConfig(runtime_name="thin", retriever=retriever)

# Вариант 2: явный InputFilter
rag_filter = RagInputFilter(retriever=retriever, top_k=3)
config = RuntimeConfig(runtime_name="thin", input_filters=[rag_filter])
```

### Архитектурные решения

- `Retriever` — Protocol (не ABC), позволяет подключить Pinecone, Weaviate, pgvector без наследования
- `Document` — frozen dataclass с `score=None` по умолчанию; retriever устанавливает score при возврате
- `SimpleRetriever` не подходит для production (нет TF-IDF, нет embeddings) — явно документировано как dev/test
- Формат `<context>...</context>` — XML-тег для явного разделения retrieved content от system prompt

---

## Взаимодействие Phase 8 компонентов

```
                    RuntimeConfig
                   /             \
      event_bus=bus          retriever=...
           |                      |
    InMemoryEventBus        auto-wrap into
           |                 RagInputFilter
    TracingSubscriber              |
    (attach/detach)       input_filters chain
           |                      |
     ConsoleTracer           ThinRuntime
           |                      |
      _spans dict          RuntimeEvent stream
                                  |
                          ChatProjection.apply()
                                  |
                            UIState.to_dict()
                                  |
                           Frontend / API
```

**Session lifecycle:**
```
SessionManager.register(state)
        |
        ▼
SqliteSessionBackend.save(scoped_key(AGENT, key), state)
        |
  [process turns]
        |
SessionManager.close(key)
        |
        ▼
SqliteSessionBackend.delete(key) + evict from memory
```

---

## Связь с другими модулями

- **`runtime/types.py`** — `RuntimeConfig` содержит поля Phase 8:
  `event_bus`, `tracer`, `retriever`
- **`runtime/thin/runtime.py`** — эмитирует `llm_call_start/end`, `tool_call_start/end` через `event_bus`;
  auto-wraps `retriever` в `input_filters`
- **`session/manager.py`** — `InMemorySessionManager` принимает `backend: SessionBackend | None`
- **`input_filters.py`** — `RagInputFilter` реализует `InputFilter` Protocol (Phase 7 Protocol, Phase 8 impl)
- **`observability/`** — `event_bus` и `tracer` — независимые модули, связанные через `TracingSubscriber`

## Заметки по статусу

По данным `STATUS.md` на 2026-03-18: Phase 7 в статусе `in progress`, Phase 8 — `todo`.
Все описанные модули присутствуют в коде и покрыты тестами — фактически реализованы.
Статус в STATUS.md может отставать от фактического состояния кода.
