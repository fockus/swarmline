# Plan: OpenAI Agents Runtime для Swarmline

**Тип:** feature
**Дата:** 2025-03-29
**Статус:** draft
**Приоритет:** medium

## Контекст

Swarmline имеет 4 runtime'а: `claude_sdk`, `thin`, `deepagents`, `cli`.
Нужен 5-й runtime `openai_agents` — обёртка над OpenAI Agents SDK (`openai-agents`).
Это даст нативную интеграцию с Codex (как MCP server внутри агента),
handoffs между агентами, traces, и Runner API.

## Аналог для изучения

Реализация `claude_sdk` runtime:
- `src/swarmline/runtime/adapter.py` — ClaudeSDKClient wrapper
- `src/swarmline/runtime/claude_code.py` — AgentRuntime implementation
- `src/swarmline/runtime/options_builder.py` — Options factory
- `src/swarmline/runtime/sdk_tools.py` — MCP tool bridge

## Архитектура

```
src/swarmline/runtime/
├── openai_agents/
│   ├── __init__.py          # Public exports
│   ├── runtime.py           # OpenAIAgentsRuntime (implements AgentRuntime)
│   ├── event_mapper.py      # Map OpenAI events → RuntimeEvent
│   ├── tool_bridge.py       # Swarmline tools → OpenAI Agent tools
│   └── types.py             # OpenAI-specific config types
```

## Этапы

### Этап 1: Scaffold + types (0.5 дня)
- `types.py` — `OpenAIAgentsConfig` (frozen dataclass)
  - model: str
  - codex_enabled: bool
  - handoffs: list
  - max_turns: int
  - sandbox_mode: str
- Регистрация в `registry.py` + `capabilities.py`
- **DoD:** `runtime="openai_agents"` валидируется в AgentConfig

### Этап 2: Event mapper (0.5 дня)
- Маппинг OpenAI streaming events → RuntimeEvent:
  - `RunItemStreamEvent` → `RuntimeEvent.assistant_delta`
  - Tool call events → `RuntimeEvent.tool_call_started` / `tool_call_result`
  - `AgentUpdatedStreamEvent` → `RuntimeEvent.status`
  - Run complete → `RuntimeEvent.final`
- **DoD:** Unit тесты на каждый маппинг

### Этап 3: Tool bridge (0.5 дня)
- Конвертация Swarmline `ToolSpec` → OpenAI `FunctionTool`
- Конвертация Swarmline `@tool` → OpenAI `@function_tool`
- MCP server pass-through (Codex)
- **DoD:** Swarmline tools работают в OpenAI Agent

### Этап 4: Runtime implementation (1 день)
- `OpenAIAgentsRuntime.run()` → `async for event in Runner.run_streamed()`
- Маппинг system_prompt → Agent.instructions
- Маппинг messages → Agent input
- Codex MCP server lifecycle (start/stop)
- cancel() / cleanup()
- **DoD:** Полный e2e с mock OpenAI (без API key)

### Этап 5: Integration + docs (0.5 дня)
- `RuntimeFactory` support
- `AgentConfig(runtime="openai_agents")` работает
- Пример в `examples/`
- Документация в `docs/`
- **DoD:** Все тесты зелёные, example запускается

## Зависимости

```toml
openai-agents = ["openai-agents>=0.1", "openai>=2.29"]
```

## Capabilities

```python
"openai_agents": RuntimeCapabilities(
    runtime_name="openai_agents",
    tier="full",
    supports_mcp=True,        # Codex как MCP
    supports_streaming=True,   # Runner.run_streamed()
    supports_native_tools=True,
    supports_handoffs=True,    # OpenAI handoffs
)
```

## Риски

1. **OpenAI Agents SDK ещё молодой** — API может меняться
2. **Codex MCP server** — требует npm/npx, может быть проблемой в Docker
3. **Тестирование** — нужен mock, реальные тесты требуют OPENAI_API_KEY
4. **Overlap с thin runtime** — thin уже поддерживает OpenAI API напрямую.
   Разница: thin = raw API calls, openai_agents = full agent framework (handoffs, traces, Codex)

## Оценка

- **Объём:** ~400-600 строк кода + ~300 строк тестов
- **Время:** 2-3 дня
- **Блокеры:** нет (openai-agents extra уже добавлен в pyproject.toml)
