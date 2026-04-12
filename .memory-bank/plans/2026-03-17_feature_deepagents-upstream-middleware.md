# План: Глубокая интеграция upstream middleware deepagents + multi-provider

**Тип:** feature
**Дата:** 2026-03-17
**Цель:** Пробросить upstream middleware (memory, summarization, todo) через `create_deep_agent()`, портировать ключевые фичи в portable path, сделать ThinRuntime multi-provider. swarmline = универсальный фреймворк: любой runtime, любой провайдер, одинаковые фичи.

---

## Контекст

### Что имеем

- `create_deep_agent()` вызывается с минимумом параметров — НЕ передаём `memory`, `subagents`, `skills`, `middleware`
- Portable path (`_stream_langchain`) — голый LLM вызов без upstream middleware
- ThinRuntime — только Anthropic SDK (хардкод в `llm_client.py`), хотя `ModelRegistry` уже знает OpenAI/Google/DeepSeek
- Наша compaction — примитив (порог 20 сообщений, нет token-aware, нет offloading)
- Cross-session memory отсутствует

### Что хотим

- **DeepAgents native path**: upstream middleware (memory, compaction, todo) через `create_deep_agent()`
- **DeepAgents portable path**: те же фичи, но наша lightweight реализация (без backend)
- **ThinRuntime**: multi-provider (OpenAI, Google, OpenRouter, Ollama, vLLM, local) + те же фичи
- **Shared ProviderResolver**: единый резолвер провайдеров для всех рунтаймов
- Разработчик не думает о том, какой runtime выбрать — всё работает одинаково

### Архитектура после

```
┌──────────────────────────────────────────────────────┐
│                     swarmline                          │
│                                                       │
│  Shared: ProviderResolver, MCP, Memory (portable),    │
│          Compaction (token-aware), Todo, StructuredOut │
│                                                       │
│  ┌──────────────┐ ┌───────────────┐ ┌──────────────┐ │
│  │ ThinRuntime  │ │ DeepAgents    │ │ ClaudeCode   │ │
│  │              │ │ Runtime       │ │ Runtime      │ │
│  │ Multi-       │ │               │ │              │ │
│  │ provider     │ │ Native path   │ │ Claude SDK   │ │
│  │ (openai SDK  │ │ (upstream MW) │ │              │ │
│  │  anthropic   │ │               │ │              │ │
│  │  google)     │ │ Portable path │ │              │ │
│  │              │ │ (наши фичи)   │ │              │ │
│  │ Lightweight  │ │               │ │ Full-featured│ │
│  │ agent loop   │ │ LangChain eco │ │              │ │
│  └──────────────┘ └───────────────┘ └──────────────┘ │
└──────────────────────────────────────────────────────┘
```

---

## Порядок выполнения

```
Phase 0C (ProviderResolver) → Phase 0B (ThinRuntime multi-provider) → Phase 1 (upstream параметры) → Phase 5 (deepagents 0.5.0) → Phase 2 (compaction) → Phase 0A (portable фичи) → Phase 3 (memory) → Phase 4 (capabilities)
```

**Почему так:**

- Phase 0C первая — shared инфраструктура, от которой зависят 0B и всё остальное
- Phase 0B — ThinRuntime multi-provider, используя новый ProviderResolver
- Phase 1 — пробросить upstream параметры в native path
- Phase 5 — обновить deepagents до 0.5.0, пока код простой
- Phase 2 — compaction: отключить нашу для native, улучшить для portable
- Phase 0A — портировать memory и compaction в portable path
- Phase 3 — cross-session memory через upstream MemoryMiddleware
- Phase 4 — capabilities, валидация, финализация

---

## Phase 0C: Shared ProviderResolver

### Контекст

Сейчас провайдеры резолвятся в трёх местах по-разному:

- `ModelRegistry.get_provider()` — по models.yaml, знает все провайдеры
- `deepagents_models.py` — парсит `"openai:gpt-4o"` prefix, свой список провайдеров
- `llm_client.py` — хардкод `anthropic.AsyncAnthropic`, base_url только для Anthropic

Нужен единый `ProviderResolver` который:

1. Резолвит модель через `ModelRegistry`
2. Определяет провайдера
3. Определяет base_url (стандартный или custom)
4. Возвращает всё в одном объекте

### Задачи

- 0C.1. Создать `src/swarmline/runtime/provider_resolver.py`
- 0C.2. Dataclass `ResolvedProvider(model_id, provider, base_url, sdk_type)` где `sdk_type` = "anthropic" | "openai_compat" | "google"
- 0C.3. Функция `resolve_provider(raw_model, base_url=None) -> ResolvedProvider`
- 0C.4. Маппинг провайдер → sdk_type:
  - anthropic → "anthropic"
  - openai, openrouter, ollama, local, together, groq, fireworks, deepseek → "openai_compat"
  - google → "google"
- 0C.5. Обновить `models.yaml` — добавить `base_url` defaults для провайдеров (openrouter, ollama)
- 0C.6. Тесты

### DoD

- [ ] `resolve_provider("openai:gpt-4o")` → `ResolvedProvider(model_id="gpt-4o", provider="openai", base_url=None, sdk_type="openai_compat")`
- [ ] `resolve_provider("openrouter:meta-llama/llama-3-70b")` → `sdk_type="openai_compat"`, `base_url="https://openrouter.ai/api/v1"`
- [ ] `resolve_provider("ollama:llama3")` → `sdk_type="openai_compat"`, `base_url="http://localhost:11434/v1"`
- [ ] `resolve_provider("claude-sonnet")` → `sdk_type="anthropic"` (через alias в registry)
- [ ] `resolve_provider("gpt-4o", base_url="https://custom.proxy/v1")` → custom base_url перезаписывает default
- [ ] `resolve_provider("gemini")` → `sdk_type="google"`
- [ ] Unit-тесты на все провайдеры и edge cases
- [ ] Существующие тесты не сломаны (ProviderResolver пока не интегрирован)

### Тесты (TDD)

```python
# test_provider_resolver.py

def test_resolve_anthropic_by_alias():
    r = resolve_provider("sonnet")
    assert r.provider == "anthropic"
    assert r.sdk_type == "anthropic"
    assert r.model_id == "claude-sonnet-4-20250514"

def test_resolve_openai_with_prefix():
    r = resolve_provider("openai:gpt-4o")
    assert r.provider == "openai"
    assert r.sdk_type == "openai_compat"
    assert r.model_id == "gpt-4o"
    assert r.base_url is None  # standard OpenAI endpoint

def test_resolve_openrouter_auto_base_url():
    r = resolve_provider("openrouter:meta-llama/llama-3-70b")
    assert r.sdk_type == "openai_compat"
    assert r.base_url == "https://openrouter.ai/api/v1"

def test_resolve_ollama_auto_base_url():
    r = resolve_provider("ollama:llama3")
    assert r.sdk_type == "openai_compat"
    assert r.base_url == "http://localhost:11434/v1"

def test_resolve_custom_base_url_overrides_default():
    r = resolve_provider("openrouter:llama3", base_url="https://my-proxy.com/v1")
    assert r.base_url == "https://my-proxy.com/v1"

def test_resolve_google():
    r = resolve_provider("gemini")
    assert r.provider == "google"
    assert r.sdk_type == "google"

def test_resolve_deepseek_uses_openai_compat():
    r = resolve_provider("deepseek-chat")
    assert r.sdk_type == "openai_compat"

def test_resolve_unknown_model_raises():
    with pytest.raises(ValueError):
        resolve_provider("nonexistent-model-xyz")
```

### Edge cases

- `"provider:model"` prefix → explicit provider, model_id=остаток
- Без prefix → ModelRegistry.resolve() + get_provider()
- Неизвестный провайдер → ValueError с подсказкой
- `base_url` от пользователя → перезаписывает auto-detected
- `base_url` env variables → fallback: `OPENAI_BASE_URL`, `ANTHROPIC_BASE_URL`

---

## Phase 0B: ThinRuntime multi-provider

### Контекст

`llm_client.py` использует `anthropic.AsyncAnthropic` хардкод. ModelRegistry уже знает все провайдеры, но llm_client их не использует.

### Задачи

- 0B.1. Создать `src/swarmline/runtime/thin/llm_providers.py` — provider adapters
- 0B.2. `AnthropicAdapter` — обёртка над текущим кодом `default_llm_call()`
- 0B.3. `OpenAICompatAdapter` — через `openai.AsyncOpenAI` SDK (покрывает OpenAI, OpenRouter, Ollama, vLLM, LMStudio, Together, Groq, Fireworks, DeepSeek)
- 0B.4. `GoogleAdapter` — через `google-genai` SDK (optional dep)
- 0B.5. `create_llm_adapter(resolved: ResolvedProvider) -> LlmAdapter` — factory
- 0B.6. Обновить `default_llm_call()` → использовать `ProviderResolver` + `create_llm_adapter()`
- 0B.7. Streaming support для каждого адаптера
- 0B.8. Обновить `pyproject.toml` — optional deps для новых провайдеров
- 0B.9. Тесты

### LlmAdapter Protocol

```python
@runtime_checkable
class LlmAdapter(Protocol):
    async def call(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> str: ...

    async def stream(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> AsyncIterator[str]: ...
```

### Provider dispatch

```python
def create_llm_adapter(resolved: ResolvedProvider) -> LlmAdapter:
    if resolved.sdk_type == "anthropic":
        return AnthropicAdapter(model=resolved.model_id, base_url=resolved.base_url)
    elif resolved.sdk_type == "openai_compat":
        return OpenAICompatAdapter(model=resolved.model_id, base_url=resolved.base_url)
    elif resolved.sdk_type == "google":
        return GoogleAdapter(model=resolved.model_id)
    raise ValueError(f"Unsupported sdk_type: {resolved.sdk_type}")
```

### DoD

- [ ] `AnthropicAdapter` — обёртка над текущим `default_llm_call()` (call + stream)
- [ ] `OpenAICompatAdapter` — через `openai.AsyncOpenAI(base_url=...)` (call + stream)
- [ ] `GoogleAdapter` — через `google.genai` (call + stream)
- [ ] `create_llm_adapter()` — factory по `ResolvedProvider.sdk_type`
- [ ] `default_llm_call()` обновлён: `resolve_provider()` → `create_llm_adapter()` → `adapter.call()`
- [ ] `try_stream_llm_call()` обновлён: `adapter.stream()`
- [ ] Streaming работает для всех трёх адаптеров
- [ ] `pyproject.toml`: `openai` + `google-genai` входят в canonical `thin` extra
- [ ] Lazy imports: `openai` и `google-genai` импортируются только при использовании
- [ ] Anthropic path не сломан (регрессия)
- [ ] Unit-тест: `AnthropicAdapter.call()` вызывает `client.messages.create()`
- [ ] Unit-тест: `OpenAICompatAdapter.call()` вызывает `client.chat.completions.create()`
- [ ] Unit-тест: `OpenAICompatAdapter` с custom base_url → передаёт в конструктор
- [ ] Unit-тест: `GoogleAdapter.call()` вызывает `genai` API
- [ ] Unit-тест: missing provider package → понятная ошибка "pip install swarmline[thin]"
- [ ] Интеграционный тест: ThinRuntime + `model="openai:gpt-4o"` → корректный вызов
- [ ] Интеграционный тест: ThinRuntime + `model="ollama:llama3"` + `base_url` → корректный вызов

### Тесты (TDD)

```python
# test_llm_providers.py

async def test_anthropic_adapter_calls_anthropic_sdk(mock_anthropic):
    adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
    result = await adapter.call(messages=[{"role": "user", "content": "hi"}], system_prompt="test")
    mock_anthropic.messages.create.assert_called_once()
    assert "model" in mock_anthropic.messages.create.call_args.kwargs

async def test_openai_adapter_calls_openai_sdk(mock_openai):
    adapter = OpenAICompatAdapter(model="gpt-4o")
    result = await adapter.call(messages=[{"role": "user", "content": "hi"}], system_prompt="test")
    mock_openai.chat.completions.create.assert_called_once()

async def test_openai_adapter_with_custom_base_url(mock_openai_cls):
    adapter = OpenAICompatAdapter(model="llama3", base_url="http://localhost:11434/v1")
    mock_openai_cls.assert_called_with(base_url="http://localhost:11434/v1")

async def test_openai_adapter_streaming(mock_openai):
    adapter = OpenAICompatAdapter(model="gpt-4o")
    chunks = []
    async for chunk in adapter.stream(messages=[...], system_prompt="test"):
        chunks.append(chunk)
    assert len(chunks) > 0

async def test_missing_openai_package_error():
    """Понятная ошибка при отсутствии openai пакета."""
    with mock.patch.dict("sys.modules", {"openai": None}):
        with pytest.raises(RuntimeError, match="pip install"):
            OpenAICompatAdapter(model="gpt-4o")

async def test_default_llm_call_dispatches_to_anthropic():
    """default_llm_call с anthropic моделью → AnthropicAdapter."""
    config = RuntimeConfig(model="claude-sonnet-4-20250514")
    # Verify Anthropic SDK called
    ...

async def test_default_llm_call_dispatches_to_openai():
    """default_llm_call с openai моделью → OpenAICompatAdapter."""
    config = RuntimeConfig(model="openai:gpt-4o")
    # Verify OpenAI SDK called
    ...

# test_thin_runtime.py (регрессия)

async def test_thin_runtime_anthropic_unchanged():
    """ThinRuntime с Anthropic моделью работает как раньше."""
    runtime = ThinRuntime(config=RuntimeConfig(model="claude-sonnet-4-20250514"))
    # Verify same behavior as before
    ...
```

### Message format adaptation

Anthropic и OpenAI используют разные форматы system prompt:

```python
# Anthropic SDK:
client.messages.create(system="prompt", messages=[...])

# OpenAI SDK:
client.chat.completions.create(messages=[
    {"role": "system", "content": "prompt"},  # system в messages
    {"role": "user", "content": "..."},
])

# Google SDK:
model.generate_content(contents=[...], system_instruction="prompt")
```

Каждый адаптер инкапсулирует эту разницу — ThinRuntime передаёт `(messages, system_prompt)`, адаптер конвертирует.

### Edge cases

- OpenAI streaming: `stream=True` → `async for chunk in response` → `chunk.choices[0].delta.content`
- Anthropic streaming: `async with client.messages.stream()` → `async for text in stream.text_stream`
- Google streaming: `model.generate_content(stream=True)` → `for chunk in response`
- Tool calling: OpenAI tool format ≠ Anthropic tool format → адаптер конвертирует
- Timeout/error handling: каждый SDK свои исключения → маппинг в общие RuntimeError

### Новые optional dependencies (pyproject.toml)

```toml
[project.optional-dependencies]
openai-provider = ["openai>=1.0"]
google-provider = ["google-genai>=1.0"]
all-providers = ["openai>=1.0", "google-genai>=1.0", "anthropic>=0.40"]
```

---

## Phase 0A: Portable path — портировать memory и compaction

### Контекст

Portable path (DeepAgentsRuntime LangChain) и ThinRuntime не имеют upstream middleware. Нужны наши lightweight реализации.

### Задачи

- 0A.1. Улучшить compaction в `BaseRuntimePort._maybe_summarize()`:
  - Token-aware trigger вместо message count (используем `tiktoken` или approximate: ~4 chars/token)
  - Configurable trigger: `("tokens", 100000)` | `("messages", 20)` | `("fraction", 0.85)`
  - Argument truncation: обрезать длинные tool_calls.args в старых сообщениях
- 0A.2. Создать `src/swarmline/runtime/portable_memory.py` — lightweight AGENTS.md support:
  - `load_agents_md(paths: list[str]) -> str` — читает файлы, возвращает merged content
  - `inject_memory_into_prompt(system_prompt, memory_content) -> str` — добавляет `<agent_memory>` блок
  - Не требует backend — прямой `pathlib.Path.read_text()`
- 0A.3. Интегрировать portable memory в `BaseRuntimePort._build_system_prompt()`
- 0A.4. Тесты

### DoD

- [ ] `_maybe_summarize()` использует token-aware trigger (не только message count)
- [ ] Configurable: `BaseRuntimePort(compaction_trigger=("tokens", 100000))`
- [ ] Argument truncation: tool_calls.args > 2000 chars → обрезаны в старых сообщениях
- [ ] `load_agents_md(["./AGENTS.md", "~/.swarmline/AGENTS.md"])` → merged string
- [ ] `inject_memory_into_prompt()` добавляет `<agent_memory>...</agent_memory>` блок
- [ ] Несуществующие AGENTS.md → silently skipped (аналогично upstream)
- [ ] `BaseRuntimePort(memory_sources=["./AGENTS.md"])` → memory injected в system prompt
- [ ] Unit-тест: token-aware trigger срабатывает при достижении лимита
- [ ] Unit-тест: message-count trigger работает как раньше (регрессия)
- [ ] Unit-тест: load_agents_md с несуществующим файлом → skip
- [ ] Unit-тест: inject_memory_into_prompt добавляет XML блок
- [ ] ThinRuntime и portable DeepAgents path получают memory через BaseRuntimePort

### Тесты (TDD)

```python
# test_portable_memory.py

def test_load_agents_md_reads_files(tmp_path):
    p = tmp_path / "AGENTS.md"
    p.write_text("# My project\nPrefer snake_case")
    content = load_agents_md([str(p)])
    assert "snake_case" in content

def test_load_agents_md_skips_missing():
    content = load_agents_md(["/nonexistent/AGENTS.md"])
    assert content == ""

def test_load_agents_md_merges_multiple(tmp_path):
    (tmp_path / "global.md").write_text("Global rules")
    (tmp_path / "project.md").write_text("Project rules")
    content = load_agents_md([str(tmp_path / "global.md"), str(tmp_path / "project.md")])
    assert "Global rules" in content
    assert "Project rules" in content

def test_inject_memory_into_prompt():
    result = inject_memory_into_prompt("You are helpful", "Use snake_case")
    assert "<agent_memory>" in result
    assert "Use snake_case" in result
    assert result.startswith("You are helpful")

def test_inject_memory_empty_content():
    result = inject_memory_into_prompt("You are helpful", "")
    assert "<agent_memory>" not in result
    assert result == "You are helpful"

# test_base_port.py

async def test_compaction_token_aware_trigger():
    port = SomeRuntimePort(
        system_prompt="test",
        compaction_trigger=("tokens", 1000),
        summarizer=mock_summarizer,
    )
    # Добавить сообщения до 1000 токенов
    for i in range(50):
        port._append_to_history("user", "x" * 100)  # ~25 tokens each
    await port._maybe_summarize()
    mock_summarizer.asummarize.assert_called_once()

async def test_compaction_message_count_regression():
    """Старый формат message count всё ещё работает."""
    port = SomeRuntimePort(
        system_prompt="test",
        compaction_trigger=("messages", 20),
        summarizer=mock_summarizer,
    )
    for i in range(25):
        port._append_to_history("user", "msg")
    await port._maybe_summarize()
    mock_summarizer.asummarize.assert_called_once()

async def test_memory_injected_into_system_prompt():
    port = SomeRuntimePort(
        system_prompt="You are helpful",
        memory_sources=["./AGENTS.md"],
    )
    prompt = port._build_system_prompt()
    # Should contain memory content if file exists
    ...
```

### Edge cases

- Token counting: approximate `len(text) / 4` для быстрого подсчёта (точный tiktoken — optional)
- Fraction trigger: требует знать max_input_tokens модели → fallback на tokens
- AGENTS.md с binary content → skip
- AGENTS.md > 10KB → truncate с warning
- Memory write: portable path НЕ пишет в AGENTS.md (read-only, запись — через native path или вручную)

---

## Phase 1: Пробросить новые параметры в create_deep_agent()

### Задачи

- 1.1. Расширить `native_config` — ключи `memory`, `subagents`, `skills`, `middleware`, `agent_name`
- 1.2. Обновить `build_deepagents_graph()` в `deepagents_native.py` — пробросить новые kwargs
- 1.3. Обновить `DeepAgentsRuntime._stream_native()` — передать из config
- 1.4. Тесты

### DoD

- [ ] `native_config["memory"]` → `create_deep_agent(memory=...)`
- [ ] `native_config["subagents"]` → `create_deep_agent(subagents=...)`
- [ ] `native_config["skills"]` → `create_deep_agent(skills=...)`
- [ ] `native_config["middleware"]` → `create_deep_agent(middleware=...)`
- [ ] `native_config["agent_name"]` → `create_deep_agent(name=...)`
- [ ] Все Optional — None = не передаём kwargs (backward compatible)
- [ ] Unit-тест: каждый параметр пробрасывается
- [ ] Unit-тест: без параметров — поведение не меняется (регрессия)
- [ ] Существующие тесты зелёные

### Тесты (TDD)

```python
# test_deepagents_native.py

def test_build_graph_passes_memory(mock_create):
    build_deepagents_graph(model="sonnet", system_prompt="t", tools=[], tool_executors={}, memory=["./AGENTS.md"])
    assert mock_create.call_args.kwargs["memory"] == ["./AGENTS.md"]

def test_build_graph_passes_subagents(mock_create):
    sa = [{"name": "r", "description": "d", "system_prompt": "s"}]
    build_deepagents_graph(model="sonnet", system_prompt="t", tools=[], tool_executors={}, subagents=sa)
    assert mock_create.call_args.kwargs["subagents"] == sa

def test_build_graph_no_new_params(mock_create):
    build_deepagents_graph(model="sonnet", system_prompt="t", tools=[], tool_executors={})
    kwargs = mock_create.call_args.kwargs
    assert "memory" not in kwargs
    assert "subagents" not in kwargs
```

---

## Phase 5: Обновить deepagents до 0.5.0

### Задачи

- 5.1. `pyproject.toml`: `deepagents>=0.5.0`
- 5.2. Проверить backend return types — адаптировать парсинг
- 5.3. Проверить `Sequence` vs `list` для subagents
- 5.4. Проверить multimodal `FileData`
- 5.5. Полный прогон тестов

### DoD

- [ ] `deepagents>=0.5.0` в pyproject.toml
- [ ] `pip install -e ".[deepagents]"` успешно
- [ ] Все тесты deepagents зелёные
- [ ] Нет deprecation warnings

---

## Phase 2: Compaction — upstream для native, улучшенная для portable

### Задачи

- 2.1. `DeepAgentsRuntimePort` native path — override `_maybe_summarize()` → noop (upstream compaction)
- 2.2. `BaseRuntimePort._maybe_summarize()` — уже улучшена в Phase 0A (token-aware)
- 2.3. Тесты: native path не вызывает нашу compaction, portable/thin — вызывает

### DoD

- [ ] Native DeepAgents path: `_maybe_summarize()` = noop
- [ ] Portable DeepAgents path: token-aware compaction (из Phase 0A)
- [ ] ThinRuntime: token-aware compaction (из Phase 0A)
- [ ] `BaseRuntimePort._maybe_summarize()` НЕ удалена
- [ ] Unit-тест: native path не вызывает summarizer
- [ ] Unit-тест: portable path вызывает token-aware summarizer

### Тесты (TDD)

```python
async def test_native_deepagents_skips_compaction():
    port = DeepAgentsRuntimePort(system_prompt="t", config=RuntimeConfig(
        runtime_name="deepagents", feature_mode="native_first", allow_native_features=True,
    ))
    for i in range(50):
        port._append_to_history("user", "x" * 1000)
    await port._maybe_summarize()
    # No summarizer called — upstream handles it

async def test_portable_deepagents_uses_compaction():
    port = DeepAgentsRuntimePort(system_prompt="t", config=RuntimeConfig(
        runtime_name="deepagents", feature_mode="portable",
    ), summarizer=mock_summarizer)
    for i in range(50):
        port._append_to_history("user", "x" * 1000)
    await port._maybe_summarize()
    mock_summarizer.asummarize.assert_called_once()
```

---

## Phase 3: Cross-session memory через upstream MemoryMiddleware

### Задачи

- 3.1. `DeepAgentsRuntimePort(memory_sources=["./AGENTS.md"])` → `native_config["memory"]`
- 3.2. Если memory + no backend → auto-create `FilesystemBackend(root_dir=".")`
- 3.3. Portable path: memory через `portable_memory.py` (read-only, из Phase 0A)
- 3.4. Native path: upstream MemoryMiddleware (read + write через edit_file)
- 3.5. Тесты

### DoD

- [ ] Native path: `create_deep_agent(memory=[...])` → upstream MemoryMiddleware
- [ ] Portable path: `load_agents_md()` → inject в system prompt (read-only)
- [ ] Auto-backend: memory + no backend → FilesystemBackend
- [ ] Unit-тесты на оба path
- [ ] Интеграционный тест: агент видит memory content

### Тесты (TDD)

```python
async def test_native_memory_passed_to_upstream():
    port = DeepAgentsRuntimePort(
        system_prompt="t",
        config=RuntimeConfig(runtime_name="deepagents", feature_mode="native_first"),
        memory_sources=["./AGENTS.md"],
    )
    await port.connect()
    assert port._config.native_config["memory"] == ["./AGENTS.md"]

async def test_portable_memory_injected_into_prompt():
    port = DeepAgentsRuntimePort(
        system_prompt="You are helpful",
        config=RuntimeConfig(runtime_name="deepagents", feature_mode="portable"),
        memory_sources=["./AGENTS.md"],
    )
    prompt = port._build_system_prompt()
    assert "<agent_memory>" in prompt
```

---

## Phase 4: Capabilities, RuntimeConfig, финализация

### Задачи

- 4.1. `capabilities.py`: `hitl` остаётся native-only и не advertised на runtime-level; `builtin_memory` / `builtin_compaction` для deepagents не advertised runtime-level до отдельного factory/default-path alignment
- 4.2. ThinRuntime capabilities: `supports_provider_override=True` (уже есть)
- 4.3. Добавить `"builtin_compaction"` в capability flags
- 4.4. Обновить `pyproject.toml` финальные зависимости
- 4.5. Тесты

### DoD

- [ ] `get_runtime_capabilities("deepagents").supports_builtin_memory == False`
- [ ] `get_runtime_capabilities("deepagents").supports_builtin_compaction == False`
- [ ] `get_runtime_capabilities("deepagents").supports_hitl == False`
- [ ] `RuntimeConfig(runtime_name="deepagents", feature_mode="portable", required_capabilities=CapabilityRequirements(flags=("hitl",)))` fail-fast
- [ ] `RuntimeConfig(runtime_name="deepagents", required_capabilities=CapabilityRequirements(flags=("builtin_memory",)))` fail-fast
- [ ] `RuntimeConfig(runtime_name="deepagents", required_capabilities=CapabilityRequirements(flags=("builtin_compaction",)))` fail-fast
- [ ] Все тесты зелёные
- [ ] Coverage deepagents модулей ≥ 85%
- [ ] Coverage thin модулей ≥ 85%

### Тесты (TDD)

```python
def test_deepagents_does_not_advertise_memory_runtime_level():
    assert get_runtime_capabilities("deepagents").supports_builtin_memory is False

def test_deepagents_does_not_advertise_compaction_runtime_level():
    assert get_runtime_capabilities("deepagents").supports_builtin_compaction is False

def test_deepagents_does_not_advertise_hitl_runtime_level():
    assert get_runtime_capabilities("deepagents").supports_hitl is False
```

### Follow-up note

Structural alignment, при котором `deepagents` сможет честно рекламировать runtime-level `builtin_memory` / `builtin_compaction`, требует отдельного rewiring `RuntimeFactory` / default execution path на port-based layer и не входит в этот фикс-сет.

---

## Риски

| Риск | Вероятность | Митигация |
|------|------------|-----------|
| OpenAI SDK tool format ≠ Anthropic | Высокая | Адаптер конвертирует формат в `LlmAdapter` |
| Google SDK streaming API отличается | Средняя | Lazy import, отдельный адаптер |
| Breaking changes deepagents 0.5.0 | Средняя | Phase 5 рано, пока мало зависимостей |
| Token counting неточный | Низкая | Approximate `len/4` + optional tiktoken |
| Portable memory read-only | Низкая | Документируем: write только через native path |

---

## Новые файлы

| Файл | Phase | Назначение |
|------|-------|-----------|
| `src/swarmline/runtime/provider_resolver.py` | 0C | Shared provider resolution |
| `src/swarmline/runtime/thin/llm_providers.py` | 0B | LlmAdapter protocol + 3 адаптера |
| `src/swarmline/runtime/portable_memory.py` | 0A | Lightweight AGENTS.md read + inject |
| `tests/unit/test_provider_resolver.py` | 0C | Provider resolution тесты |
| `tests/unit/test_llm_providers.py` | 0B | LLM adapter тесты |
| `tests/unit/test_portable_memory.py` | 0A | Portable memory тесты |

## Что НЕ делаем

- Не удаляем portable path — оставляем как fallback
- Не удаляем `BaseRuntimePort._maybe_summarize()` — улучшаем
- Не удаляем `todo/tools.py` — нужен portable + thin
- Не добавляем Skills — следующая итерация
- Не добавляем `compact_conversation` tool — позже
- Не трогаем ClaudeCodeRuntime
- Portable memory = **read-only** (write только через native path)
