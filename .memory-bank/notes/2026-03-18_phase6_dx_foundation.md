# Phase 6: DX Foundation

**Дата:** 2026-03-18
**Статус:** завершено

## Обзор

Phase 6 добавляет четыре независимых DX-улучшения поверх v0.5.0:

| Код | Фича | Проблема |
|-----|------|---------|
| 6A | Structured Output helpers | Portable parse/validate для thin+deepagents |
| 6B | `@tool` decorator | Регистрация инструментов без boilerplate |
| 6C | RuntimeRegistry | Extensible plugin registry для runtimes |
| 6D | Core DX | CancellationToken, typed event accessors, context manager |

---

## 6A: Structured Output

**Файл:** `src/swarmline/runtime/structured_output.py`

Набор stateless функций для portable разбора JSON-ответов LLM.

### API

```python
from swarmline.runtime.structured_output import (
    validate_structured_output,
    resolve_structured_output,
    try_resolve_structured_output,
    append_structured_output_instruction,
    extract_structured_output,
    extract_pydantic_schema,
)
```

| Функция | Назначение |
|---------|-----------|
| `validate_structured_output(text, output_type)` | Parse JSON + validate против Pydantic-модели. Raises `ValueError` / `ValidationError`. |
| `resolve_structured_output(text, output_format, output_type)` | Роутер: если `output_type` — Pydantic, иначе raw JSON dict. |
| `try_resolve_structured_output(text, output_format, output_type)` | Возвращает `(result, error_str)` — никогда не бросает. |
| `append_structured_output_instruction(system_prompt, output_format)` | Добавляет JSON Schema инструкцию в system prompt. |
| `extract_structured_output(text, output_format)` | Извлекает первый валидный JSON без Pydantic. |
| `extract_pydantic_schema(output_type)` | Возвращает `model_json_schema()` как dict. |

### Retry logic

Retry — вне этого модуля. `try_resolve_structured_output` возвращает `(None, error_str)` при провале — runtime решает делать ли повтор.

### Пример

```python
from pydantic import BaseModel
from swarmline.runtime.structured_output import try_resolve_structured_output

class Answer(BaseModel):
    value: int
    confidence: float

result, err = try_resolve_structured_output(
    text='{"value": 42, "confidence": 0.9}',
    output_format=None,
    output_type=Answer,
)
# result = Answer(value=42, confidence=0.9), err = None
```

### RuntimeConfig integration

```python
from swarmline.runtime.types import RuntimeConfig

config = RuntimeConfig(
    runtime_name="thin",
    output_type=Answer,          # auto-sets output_format из model_json_schema()
)
# config.output_format заполняется автоматически в __post_init__
```

---

## 6B: @tool Decorator

**Файл:** `src/swarmline/agent/tool.py`

Регистрация инструментов через декоратор без ручного JSON Schema.

### API

```python
from swarmline.agent.tool import tool, ToolDefinition
```

**Декоратор `tool(name, description=None, *, schema=None)`:**
- `name` — уникальный идентификатор инструмента
- `description` — описание для LLM; если `None`, берётся первая строка docstring
- `schema` — явная JSON Schema; если `None`, auto-infer из type hints

**Результат:** функция получает атрибут `__tool_definition__: ToolDefinition`.

### Type mapping (auto-infer)

| Python | JSON Schema |
|--------|-------------|
| `str` | `string` |
| `int` | `integer` |
| `float` | `number` |
| `bool` | `boolean` |
| `list[T]` | `array` с `items` |
| `dict` | `object` |
| `Optional[T]` / `T \| None` | unwrap inner type, не required |
| `Enum` subclass | `string` + `enum` values |
| `BaseModel` subclass | `model_json_schema()` |
| без аннотации | `string` |

Описания параметров берутся из Google-style docstring (`Args:` секция).

Sync-функции автоматически оборачиваются в async wrapper.

### Пример

```python
from swarmline.agent.tool import tool
from enum import Enum

class Priority(Enum):
    HIGH = "high"
    LOW = "low"

@tool("set_priority", "Set task priority")
async def set_priority(task_id: str, priority: Priority, note: str | None = None) -> str:
    """Set task priority.

    Args:
        task_id: Unique task identifier.
        priority: Task priority level.
        note: Optional note.
    """
    return f"Done: {task_id} -> {priority.value}"

tool_def = set_priority.__tool_definition__
spec = tool_def.to_tool_spec()  # -> ToolSpec(name="set_priority", is_local=True, ...)
```

---

## 6C: Runtime Registry

**Файл:** `src/swarmline/runtime/registry.py`

Thread-safe extensible registry для runtime factories с plugin discovery через entry points.

### Встроенные runtimes

Автоматически регистрируются при первом вызове `get_default_registry()`:

| Имя | Класс |
|-----|-------|
| `thin` | `ThinRuntime` |
| `claude_sdk` | `ClaudeCodeRuntime` |
| `deepagents` | `DeepAgentsRuntime` |

### API

```python
from swarmline.runtime.registry import (
    RuntimeRegistry,
    get_default_registry,
    reset_default_registry,
    get_valid_runtime_names,
)

registry = get_default_registry()

registry.register("my_runtime", factory_fn, capabilities=caps)
factory = registry.get("my_runtime")
names = registry.list_available()       # ["thin", "claude_sdk", "deepagents", "my_runtime"]
caps = registry.get_capabilities("thin")
exists = registry.is_registered("my_runtime")
registry.unregister("my_runtime")       # returns bool
```

### Plugin через entry points

```toml
# pyproject.toml
[project.entry-points."swarmline.runtimes"]
my_runtime = "my_package.runtime:get_runtime"
```

Entry point должен возвращать `tuple[factory_fn, RuntimeCapabilities]`. Невалидные entry points пропускаются с `logger.warning`.

### Пример кастомного runtime

```python
from swarmline.runtime.registry import get_default_registry
from swarmline.runtime.capabilities import RuntimeCapabilities

def my_factory(config, **kwargs):
    return MyRuntime(config=config, **kwargs)

caps = RuntimeCapabilities(streaming=True, tools=True)
get_default_registry().register("my_runtime", my_factory, capabilities=caps)

# Теперь доступно:
config = RuntimeConfig(runtime_name="my_runtime", ...)
```

---

## 6D: Core DX

### CancellationToken

**Файл:** `src/swarmline/runtime/cancellation.py`

Cooperative cancellation для async runtime loops.

```python
from swarmline.runtime.cancellation import CancellationToken

token = CancellationToken()
token.on_cancel(lambda: print("cancelled"))
token.cancel()        # idempotent, invoices callbacks once
token.is_cancelled    # True

# Использование в RuntimeConfig:
config = RuntimeConfig(runtime_name="thin", cancellation_token=token)
```

Особенности:
- Thread-safe (Lock внутри)
- `on_cancel()` после `cancel()` вызывает callback немедленно
- Ошибки в callbacks логируются, не бросаются

### Typed event accessors (RuntimeEvent)

**Файл:** `src/swarmline/runtime/types.py`

```python
event: RuntimeEvent = ...

event.text           # str — текст для assistant_delta, status, final
event.tool_name      # str — имя инструмента для tool_call_started/finished
event.structured_output  # Any — из final event
event.is_final       # bool
event.is_error       # bool
event.is_text        # bool — True для assistant_delta
```

Static factory methods для создания событий:

```python
RuntimeEvent.assistant_delta("chunk")
RuntimeEvent.tool_call_started("my_tool", args={"x": 1})
RuntimeEvent.tool_call_finished("my_tool", correlation_id="abc123", ok=True)
RuntimeEvent.final(text="done", metrics=metrics, structured_output=model_instance)
RuntimeEvent.error(error_data)
RuntimeEvent.approval_required("tool_name", args={}, interrupt_id="id1")
RuntimeEvent.user_input_requested("Enter value:", interrupt_id="id2")
RuntimeEvent.native_notice("text", metadata={})
RuntimeEvent.status("Working...")
```

### AgentRuntime context manager

**Файл:** `src/swarmline/runtime/base.py`

`AgentRuntime` Protocol теперь включает `cancel()` и async context manager:

```python
async with runtime as r:
    async for event in r.run(messages=..., system_prompt=..., active_tools=...):
        ...
# __aexit__ вызывает cleanup() автоматически

runtime.cancel()  # cooperative cancel текущей операции
```

### Protocols split (ISP)

Монолитный `protocols.py` разбит на модули в `src/swarmline/protocols/`:

| Файл | Протоколы |
|------|----------|
| `memory.py` | `MessageStore`, `FactStore`, `GoalStore`, `SummaryStore`, `SummaryGenerator`, `SessionStateStore`, `ToolEventStore`, `UserStore`, `PhaseStore` |
| `session.py` | `SessionManager`, `SessionFactory`, `SessionLifecycle`, `SessionRehydrator` |
| `routing.py` | `RoleRouter`, `ContextBuilder`, `ModelSelector`, `RoleSkillsProvider` |
| `tools.py` | `LocalToolResolver`, `ToolIdCodec` |
| `runtime.py` | `RuntimePort` (deprecated), re-export `AgentRuntime` |

Backward-compatible: `from swarmline.protocols import MessageStore` работает как раньше через `__init__.py`.

`RuntimePort` помечен deprecated — новый код использует `AgentRuntime` из `swarmline.runtime.base`.

---

## Тесты

| Файл | Тестов |
|------|--------|
| `tests/unit/test_structured_output_coverage.py` | 21 |
| `tests/unit/test_structured_output_pydantic.py` | 15 |
| `tests/integration/test_structured_output_integration.py` | 4 |
| `tests/unit/test_tool_decorator.py` | 21 |
| `tests/unit/test_runtime_registry.py` | 21 |
| `tests/integration/test_runtime_registry_integration.py` | 3 |
| `tests/unit/test_cancellation.py` | 17 |
| **Итого Phase 6** | **102** |

---

## Breaking changes

Нет. Все изменения обратно совместимы:
- `swarmline.protocols` re-exports не изменились
- `RuntimePort` deprecated, но не удалён
- `AgentRuntime` расширен новыми методами (`cancel`, `__aenter__`/`__aexit__`) с дефолтными no-op реализациями в Protocol

---

## Migration guide

### Добавить output_type в конфиг

```python
# До:
config = RuntimeConfig(runtime_name="thin", output_format=MyModel.model_json_schema())

# После (эквивалентно, короче):
config = RuntimeConfig(runtime_name="thin", output_type=MyModel)
```

### Определить инструмент через @tool

```python
# До (manual ToolSpec):
spec = ToolSpec(name="search", description="...", parameters={...}, is_local=True)

# После:
@tool("search", "Search the web")
async def search(query: str) -> str: ...

spec = search.__tool_definition__.to_tool_spec()
```

### Использовать typed accessors вместо dict

```python
# До:
text = event.data.get("text", "")
is_done = event.type == "final"

# После:
text = event.text
is_done = event.is_final
```
