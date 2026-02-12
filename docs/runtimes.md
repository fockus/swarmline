# Runtimes

Cognitia поддерживает три runtime. Все реализуют единый `AgentRuntime` Protocol — переключение без изменения бизнес-кода.

## Сравнение

| | Claude SDK | ThinRuntime | DeepAgents |
|--|-----------|-------------|------------|
| **LLM** | Claude (через SDK subprocess) | Любой (Anthropic API) | Любой (LangChain) |
| **MCP** | Нативная поддержка | Встроенный MCP client | Через LangChain tools |
| **Sandbox** | Нативные Read/Write/Bash | Через SandboxProvider | Через SandboxProvider |
| **Planning** | Нативный plan mode | ThinPlannerMode | DeepAgentsPlannerMode |
| **Subagents** | Нативный Task tool | asyncio.Task | asyncio.Task / LangGraph |
| **Team mode** | ClaudeTeamOrchestrator | (backlog) | DeepAgentsTeamOrchestrator |
| **Extras** | `cognitia[claude]` | `cognitia[thin]` | `cognitia[deepagents]` |
| **Offline** | Нет | Да (через base_url) | Да |

## Claude SDK Runtime

Использует Claude Agent SDK subprocess. Нативная поддержка MCP, tools, subagents.

```python
config = RuntimeConfig(runtime_name="claude_sdk", model="claude-sonnet-4-20250514")
```

### Когда использовать

- Нужна полная интеграция с Claude ecosystem
- Нативные MCP серверы
- Subagents через Task tool

### Особенности

- SDK управляет subprocess'ом — cognitia нормализует events
- `permission_mode="bypassPermissions"` — наш `ToolPolicy` контролирует доступ
- `allowed_system_tools` whitelist разрешает нативные Read/Write для sandbox

## ThinRuntime

Собственная lightweight реализация. Прямые вызовы API без subprocess.

```python
config = RuntimeConfig(runtime_name="thin", model="claude-sonnet-4-20250514")
```

### Когда использовать

- Максимальный контроль над поведением
- Альтернативные LLM (через `base_url`)
- Простые проекты без MCP

### Режимы

- `conversational` — обычный chat (без tools)
- `react` — ReAct loop (tool calls → results → next iteration)
- `planner` — plan-then-execute

### Особенности

- Встроенный MCP client (STDIO)
- ToolExecutor для local/builtin tools
- Streaming через `async for event in runtime.run(...)`

## DeepAgents Runtime

Интеграция через LangChain/LangGraph. Доступ к экосистеме LangChain.

```python
config = RuntimeConfig(runtime_name="deepagents", model="claude-sonnet-4-20250514")
```

### Когда использовать

- Нужны LangGraph graphs (plan-and-execute, supervisor)
- Экосистема LangChain (retrievers, chains)
- Multi-agent workflows

### Особенности

- LangGraph PlanExecute pattern для planning
- Supervisor pattern для team mode
- `Send()` для параллельных subagents

## Переключение runtime

Runtime выбирается через конфиг — бизнес-код не меняется:

```python
# Разработка: ThinRuntime (быстрый, без subprocess)
config = RuntimeConfig(runtime_name="thin")

# Продакшен: Claude SDK (полная интеграция)
config = RuntimeConfig(runtime_name="claude_sdk")

# Эксперименты: DeepAgents (LangGraph)
config = RuntimeConfig(runtime_name="deepagents")
```

## AgentRuntime Protocol

```python
class AgentRuntime(Protocol):
    def run(
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        config: RuntimeConfig | None = None,
    ) -> AsyncIterator[RuntimeEvent]: ...

    async def cleanup(self) -> None: ...
```

Runtime **не хранит состояние** — получает messages каждый turn, возвращает new_messages в final event. SessionManager — source of truth.

## RuntimeEvent types

| Type | Данные | Когда |
|------|--------|-------|
| `assistant_delta` | `{"text": "..."}` | Streaming text |
| `status` | `{"message": "..."}` | Статус (thinking, tool call) |
| `tool_call_started` | `{"name": "...", "args": {...}}` | Начало tool call |
| `tool_call_finished` | `{"name": "...", "result": "..."}` | Конец tool call |
| `final` | `{"new_messages": [...], "metrics": {...}}` | Завершение turn |
| `error` | `{"kind": "...", "message": "..."}` | Ошибка |
