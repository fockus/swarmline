# Phase 7: Production Safety (v0.7.0)

## Обзор

Phase 7 добавляет production-ready механизмы безопасности и надёжности в ThinRuntime:
бюджетирование стоимости, guardrails (проверки входа/выхода), input filters (трансформация
контекста) и retry/fallback политики. Все компоненты подключаются через `RuntimeConfig` —
обратная совместимость сохраняется (все поля опциональны, по умолчанию функциональность отключена).

**Тест-покрытие Phase 7:** unit + integration тесты для каждого модуля, контрактные тесты
через `isinstance(impl, Protocol)`.

---

## Модуль: `runtime/cost.py` + `runtime/pricing.json`

### Назначение

Отслеживание накопленной стоимости LLM-вызовов и проверка бюджетных лимитов.
Поддерживает лимиты по USD и по количеству токенов с двумя режимами реакции на превышение.

### Public API

| Сущность | Тип | Описание |
|---|---|---|
| `ModelPricing` | frozen dataclass | Цены модели в USD за 1M токенов (`input_per_1m`, `output_per_1m`) |
| `CostBudget` | frozen dataclass | Конфигурация лимитов (`max_cost_usd`, `max_total_tokens`, `action_on_exceed`) |
| `CostTracker` | class | Накапливает usage, вычисляет стоимость, проверяет бюджет |
| `BudgetStatus` | Literal | `"ok"` / `"warning"` / `"exceeded"` |
| `load_pricing()` | function | Загружает `pricing.json` через `importlib.resources` |

**`CostBudget` defaults:** `max_cost_usd=None`, `max_total_tokens=None`, `action_on_exceed="error"`.

**`CostTracker` методы:**

- `record(model, input_tokens, output_tokens)` — записывает вызов; если модель неизвестна, берёт `_default` pricing
- `check_budget() -> BudgetStatus` — `"ok"` / `"exceeded"` / `"warning"` в зависимости от `action_on_exceed`
- `reset()` — обнуляет все счётчики
- `total_cost_usd: float` (property)
- `total_tokens: int` (property)

**Формула стоимости:**
```
cost = pricing.input_per_1m * input_tokens / 1_000_000
     + pricing.output_per_1m * output_tokens / 1_000_000
```

### pricing.json (bundled)

| Модель | Input USD/1M | Output USD/1M |
|---|---|---|
| claude-sonnet-4-20250514 | 3.0 | 15.0 |
| claude-haiku-3-20240307 | 0.25 | 1.25 |
| gpt-4o | 2.5 | 10.0 |
| gpt-4o-mini | 0.15 | 0.6 |
| gemini-2.0-flash | 0.1 | 0.4 |
| `_default` | 3.0 | 15.0 |

### Пример использования

```python
from cognitia.runtime.cost import CostBudget, CostTracker, load_pricing
from cognitia.runtime.types import RuntimeConfig

budget = CostBudget(max_cost_usd=5.0, action_on_exceed="warn")
config = RuntimeConfig(runtime_name="thin", cost_budget=budget)

# Внутри ThinRuntime:
tracker = CostTracker(budget=budget, pricing=load_pricing())
tracker.record("gpt-4o", input_tokens=1000, output_tokens=500)
status = tracker.check_budget()  # "ok" | "warning" | "exceeded"
```

### Интеграция с ThinRuntime

- `RuntimeConfig.cost_budget: CostBudget | None` — если `None`, трекинг отключён
- ThinRuntime создаёт `CostTracker` при старте, записывает usage после каждого LLM-вызова
- При `"exceeded"` эмитирует `RuntimeEvent` с `kind="budget_exceeded"`, при `"warn"` продолжает
- Final event включает `total_cost_usd` при включённом трекинге

### Архитектурные решения

- `ModelPricing` и `CostBudget` — frozen dataclasses (domain objects, неизменяемы)
- `load_pricing()` использует `importlib.resources` (не `__file__`), корректно работает в wheel/zip
- `_default` ключ в pricing.json — fallback для незнакомых моделей (не падает с KeyError)
- Thread safety: single-threaded async, блокировки не нужны

---

## Модуль: `guardrails.py`

### Назначение

Pre- и post-LLM проверки безопасности контента. Input guardrails выполняются перед LLM-вызовом,
output guardrails — после получения ответа. Провал guardrail эмитирует error event с
`kind="guardrail_tripwire"` (зарегистрирован в `RUNTIME_ERROR_KINDS`).

### Public API

| Сущность | Тип | Описание |
|---|---|---|
| `GuardrailContext` | frozen dataclass | Контекст проверки (`session_id`, `model`, `turn`) |
| `GuardrailResult` | dataclass | Результат (`passed: bool`, `reason: str\|None`, `tripwire: bool`) |
| `Guardrail` | Protocol | `async def check(ctx, text) -> GuardrailResult` |
| `InputGuardrail` | Protocol | Маркер: проверяется до LLM-вызова |
| `OutputGuardrail` | Protocol | Маркер: проверяется после LLM-ответа |
| `ContentLengthGuardrail` | class | Отклоняет текст длиннее `max_length` символов (default: 100_000) |
| `RegexGuardrail` | class | Отклоняет текст, совпадающий с любым из `patterns` |
| `CallerAllowlistGuardrail` | class | Отклоняет запросы от `session_id` не из allowlist |

**`tripwire=True`** — hard stop, non-recoverable. Используется `CallerAllowlistGuardrail`
при `session_id=None` (идентификатор звонящего отсутствует — нарушение безопасности).

**Структурные протоколы:** все три builtin guardrails удовлетворяют одновременно `InputGuardrail`
и `OutputGuardrail` (протоколы маркерные, не добавляют методов).

### Пример использования

```python
from cognitia.guardrails import ContentLengthGuardrail, RegexGuardrail
from cognitia.runtime.types import RuntimeConfig

config = RuntimeConfig(
    runtime_name="thin",
    input_guardrails=[
        ContentLengthGuardrail(max_length=8000),
        RegexGuardrail(patterns=[r"ignore previous instructions"]),
    ],
    output_guardrails=[
        RegexGuardrail(patterns=[r"SECRET_\d+"], reason="Sensitive data in response"),
    ],
)
```

### Интеграция с ThinRuntime

- `RuntimeConfig.input_guardrails: list[Guardrail]` — default `[]`
- `RuntimeConfig.output_guardrails: list[Guardrail]` — default `[]`
- ThinRuntime запускает все guardrails через `asyncio.gather` (параллельно)
- Первый провал останавливает выполнение, эмитирует error event с `kind="guardrail_tripwire"`

### Архитектурные решения

- Параллельное выполнение через `asyncio.gather` — N guardrails не увеличивают latency линейно
- `tripwire` флаг разделяет мягкие и жёсткие ошибки (будущее: `tripwire=False` может позволить fallback)
- `CallerAllowlistGuardrail` хранит allowlist как `frozenset` (immutable, потокобезопасно)

---

## Модуль: `input_filters.py`

### Назначение

Трансформация `messages` и `system_prompt` перед каждым LLM-вызовом. Позволяет ограничивать
размер контекста и динамически модифицировать системный промпт. Фильтры применяются
последовательно в порядке списка.

### Public API

| Сущность | Тип | Описание |
|---|---|---|
| `InputFilter` | Protocol | `async def filter(messages, system_prompt) -> tuple[list[Message], str]` |
| `MaxTokensFilter` | class | Усекает старые сообщения, сохраняя последнее (`max_tokens`, `chars_per_token=4.0`) |
| `SystemPromptInjector` | class | Добавляет текст к system prompt (`extra_text`, `position="append"\|"prepend"`) |

**`MaxTokensFilter` логика:**
- Токены оцениваются как `len(text) / chars_per_token` (эвристика, без tokenizer)
- System prompt не усекается никогда
- Последнее сообщение сохраняется даже при превышении бюджета

**Цепочка фильтров** — применяются последовательно:
```python
for f in config.input_filters:
    messages, system_prompt = await f.filter(messages, system_prompt)
```

### Пример использования

```python
from cognitia.input_filters import MaxTokensFilter, SystemPromptInjector
from cognitia.runtime.types import RuntimeConfig

config = RuntimeConfig(
    runtime_name="thin",
    input_filters=[
        SystemPromptInjector(extra_text="Reply in English only.", position="prepend"),
        MaxTokensFilter(max_tokens=64_000),
    ],
)
```

### Интеграция с ThinRuntime

- `RuntimeConfig.input_filters: list[InputFilter]` — default `[]`
- Если задан `RuntimeConfig.retriever`, ThinRuntime автоматически добавляет `RagInputFilter`
  в начало цепочки (не дублирует, если `RagInputFilter` уже присутствует)

---

## Модуль: `retry.py`

### Назначение

Pluggable политики повтора и fallback для LLM-вызовов в ThinRuntime. Позволяет автоматически
повторять запросы при ошибках и переключаться между моделями или провайдерами.

### Public API

| Сущность | Тип | Описание |
|---|---|---|
| `RetryPolicy` | Protocol | `def should_retry(error, attempt) -> tuple[bool, float]` |
| `ExponentialBackoff` | frozen dataclass | Экспоненциальная задержка с jitter |
| `ModelFallbackChain` | frozen dataclass | Переключение на следующую модель по цепочке |
| `ProviderFallback` | frozen dataclass | Альтернативный провайдер при outage (`fallback_model: str`) |

**`ExponentialBackoff` параметры:**

| Параметр | Default | Описание |
|---|---|---|
| `max_retries` | 3 | Максимум попыток повтора (не считая первую) |
| `base_delay` | 1.0 | Базовая задержка в секундах |
| `max_delay` | 60.0 | Максимальная задержка (cap) |
| `jitter` | True | Случайный множитель uniform(0.5, 1.5) |

**Формула задержки:** `min(base_delay * 2^attempt, max_delay) * jitter_factor`

**`ModelFallbackChain.next_model(current)`** — возвращает следующую модель или `None`
если текущая последняя или не найдена в цепочке.

### Пример использования

```python
from cognitia.retry import ExponentialBackoff, ModelFallbackChain
from cognitia.runtime.types import RuntimeConfig

config = RuntimeConfig(
    runtime_name="thin",
    retry_policy=ExponentialBackoff(max_retries=3, base_delay=1.0, jitter=True),
)

chain = ModelFallbackChain(models=["gpt-4o", "claude-sonnet-4-20250514", "gemini-2.0-flash"])
next_model = chain.next_model("gpt-4o")  # -> "claude-sonnet-4-20250514"
```

### Интеграция с ThinRuntime

- `RuntimeConfig.retry_policy: RetryPolicy | None` — default `None` (без повтора)
- При ошибке ThinRuntime вызывает `policy.should_retry(error, attempt)`
- `should_retry=True` → `asyncio.sleep(delay)` + status event "Retry N/M"
- Попытки считаются от 0 (attempt=0 = первый повтор, т.е. вторая попытка вызова)
- При исчерпании — error event с исходным сообщением ошибки
- `"retry"` зарегистрирован в `RUNTIME_ERROR_KINDS`

### Архитектурные решения

- `RetryPolicy` — Protocol (не ABC): duck typing, любой класс с `should_retry` подходит
- `ExponentialBackoff` — frozen dataclass: конфигурация неизменяема после создания
- `ModelFallbackChain` и `ProviderFallback` — отдельные data objects, не реализуют `RetryPolicy`;
  логика смены модели — ответственность ThinRuntime, не политики

---

## Общий data flow Phase 7

```
User Input
    │
    ▼
InputFilter chain (sequential: MaxTokensFilter, SystemPromptInjector, RagInputFilter)
    │
    ▼
InputGuardrail checks (parallel asyncio.gather)
    │  fail → RuntimeEvent error, kind=guardrail_tripwire
    ▼  pass
LLM call
    │  error → RetryPolicy.should_retry → retry loop or error event
    ▼  success
OutputGuardrail checks
    │  fail → RuntimeEvent error, kind=guardrail_tripwire
    ▼  pass
CostTracker.record → check_budget
    │  exceeded + action=error → RuntimeEvent budget_exceeded
    ▼  ok | warn
Final RuntimeEvent (includes total_cost_usd if budget configured)
```

## Связь с другими модулями

- **`runtime/types.py`** — `RuntimeConfig` содержит все поля Phase 7:
  `cost_budget`, `input_guardrails`, `output_guardrails`, `input_filters`, `retry_policy`, `retriever`
- **`runtime/thin/runtime.py`** — точка интеграции всех Phase 7 механизмов
- **`rag.py`** — `RagInputFilter` реализует `InputFilter`, входит в состав Phase 8 (см. отдельную заметку)
  но используется через `RuntimeConfig.retriever` + `input_filters`
