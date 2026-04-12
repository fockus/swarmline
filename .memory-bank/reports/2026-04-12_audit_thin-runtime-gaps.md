# Аудит ThinRuntime: gap-анализ для Claude Code-like функциональности

**Дата**: 2026-04-12
**Версия**: swarmline 1.4.1
**Цель**: определить что нужно доработать в ThinRuntime для полноценной системы субагентов, команд и хуков

## Архитектура ThinRuntime (17 файлов, ~2800 строк)

```
src/swarmline/runtime/thin/
├── runtime.py          (397)  — главный класс ThinRuntime, точка входа run()
├── react_strategy.py   (285)  — ReAct цикл: LLM → tool_call → result → repeat
├── conversational.py   (254)  — один вызов LLM, без инструментов
├── planner_strategy.py (229)  — планировщик: план → шаги → финальная сборка
├── executor.py         (192)  — ToolExecutor: диспатч local_tools + MCP
├── mcp_client.py       (207)  — HTTP JSON-RPC клиент для MCP серверов
├── builtin_tools.py    (232)  — 9 встроенных инструментов (read/write/edit/bash/glob/grep...)
├── llm_client.py       (192)  — default_llm_call, стриминг, retry
├── llm_providers.py    (261)  — 3 адаптера: Anthropic, OpenAI-compat, Google
├── prompts.py          (151)  — системные промпты для каждой стратегии
├── schemas.py          (110)  — Pydantic: ActionEnvelope, PlanSchema
├── parsers.py          (100)  — парсинг JSON из текста LLM
├── finalization.py     (194)  — валидация structured output + retry
├── stream_parser.py    (170)  — инкрементальный парсер (НЕ используется)
├── runtime_support.py  (159)  — guardrails, event bus wrapping, helpers
├── helpers.py           (51)  — Message → dict, metrics builder
├── errors.py            (52)  — ThinLlmError, dependency_missing_error
└── json_utils.py        (39)  — поиск границ JSON-объекта
```

## Что работает хорошо

| Возможность | Статус | Детали |
|-------------|--------|--------|
| Multi-provider LLM | ✅ | Anthropic + OpenAI-compat + Google через адаптеры |
| 3 стратегии выполнения | ✅ | conversational, react (tool loop), planner (multi-step) |
| Tool execution | ✅ | local_tools + MCP (HTTP), @tool decorator, sandbox builtins |
| Structured output | ✅ | output_type (Pydantic), retry при ошибке валидации |
| Streaming | ✅ | try_stream → buffered → fallback |
| Cost tracking | ✅ | CostBudget, budget_exceeded events |
| Guardrails | ✅ | input/output guardrails параллельно |
| Cancellation | ✅ | CancellationToken на каждом yield |
| RAG | ✅ | auto-wrap retriever → input_filter |
| EventBus | ✅ | llm_call_start/end, tool_call_start/end |

## 5 критических gap'ов

### Gap 1: Hooks НЕ подключены к ThinRuntime

```
HookRegistry → registry_to_sdk_hooks() → claude_agent_sdk  ← ТОЛЬКО этот путь работает
              ThinRuntime.run()  ← НОЛЬ интеграции с hooks
```

- `HookRegistry` поддерживает 4 типа: `PreToolUse`, `PostToolUse`, `Stop`, `UserPromptSubmit`
- `ToolExecutor.execute()` НЕ вызывает PreToolUse/PostToolUse
- `ThinRuntime.run()` НЕ вызывает Stop/UserPromptSubmit
- `SecurityGuard` middleware создаёт PreToolUse хук — **молча игнорируется** для thin
- `ToolOutputCompressor` middleware создаёт PostToolUse хук — тоже игнорируется

**Последствие**: пользователь подключает middleware для безопасности, но для thin runtime они не работают. Ложное чувство защищённости.

### Gap 2: LLM не может порождать subagents

```
Orchestration layer (Python code):
  ThinSubagentOrchestrator.spawn(spec, task) → asyncio.Task → new ThinRuntime → run()
  ThinTeamOrchestrator.start() → N workers с MessageBus

ThinRuntime (LLM perspective):
  ❌ Нет tool "spawn_agent" / "Task" в списке инструментов
  ❌ LLM не знает о существовании субагентов
  ❌ Делегация только через Python API, не через LLM
```

Субагенты управляются только программно из application code. LLM внутри ThinRuntime не может инициировать делегацию задачи другому агенту.

### Gap 3: Commands не активированы

```
CommandRegistry (commands/registry.py):
  ✅ Полный парсинг /command arg1 arg2
  ✅ Алиасы, категории, JSON Schema валидация
  ✅ YAML загрузчик (одиночный + директория)
  ✅ to_tool_definitions() — конвертация в ToolSpec для LLM
  
ThinRuntime:
  ❌ Не проверяет /command в user input
  ❌ Не вызывает CommandRegistry.parse_command()
  ❌ Не экспонирует commands как tools для LLM
```

### Gap 4: Pseudo tool-calling вместо native API

ThinRuntime использует JSON-in-text протокол:
- System prompt инструктирует: `{"type": "tool_call", "name": "...", "args": {...}}`
- LLM output парсится через `parse_envelope()` → `ActionEnvelope`
- Не использует native `tools` parameter API у Anthropic/OpenAI/Google
- Парсинг хрупкий — JSON обёрнут в markdown fences, mixed с текстом
- Нет parallel tool calling (батчинг нескольких tool_call за один ход)

### Gap 5: Tool policy не применяется в ThinRuntime

```
DefaultToolPolicy.can_use_tool():
  ✅ 4-step allow/deny logic
  
ToolExecutor.execute():
  ❌ НЕ вызывает tool policy
  ❌ Любой tool выполняется без проверки
```

## Сравнение с Claude Code

| Feature | Claude Code | ThinRuntime |
|---------|------------|-------------|
| Subagents (LLM-initiated) | Task tool → дочерний процесс | ❌ Нет (только Python API) |
| PreToolUse hook | Блокировка/модификация до вызова | ❌ Не подключено |
| PostToolUse hook | Модификация output после вызова | ❌ Не подключено |
| Stop hook | При завершении | ❌ Не подключено |
| Slash commands | /help, /compact, custom YAML | ❌ Registry есть, не активирован |
| Native tool calling | Anthropic tools API | ❌ JSON-in-text |
| Parallel tool calls | Поддержано | ❌ Один tool за ход |
| Tool policy | allow/deny + permission_mode | ❌ Не применяется |
| MCP | stdio + HTTP | Только HTTP |

## Точки интеграции

### ToolExecutor.execute() — ключевая точка

```python
# Текущий код (executor.py:~60):
async def execute(self, tool_name: str, args: dict) -> str:
    if tool_name in self._local_tools:
        return await self._execute_local(tool_name, args)
    elif tool_name.startswith("mcp__"):
        return await self._execute_mcp(tool_name, args)
    return json.dumps({"error": f"Unknown tool: {tool_name}"})
```

Здесь нужно добавить: PreToolUse hooks → policy check → execute → PostToolUse hooks.

### ThinRuntime.run() — command routing + lifecycle hooks

В начале `run()`: UserPromptSubmit hook + command parsing.
В конце `run()`: Stop hook.

### builtin_tools.py — subagent tool

Добавить `spawn_agent` ToolSpec + executor, аналогично существующим sandbox tools.

## Существующие абстракции для переиспользования

| Абстракция | Файл | Можно использовать для |
|-----------|------|----------------------|
| `HookRegistry` | hooks/registry.py | Dispatch hooks в ThinRuntime (уже готовый API) |
| `HookEntry.matcher` | hooks/registry.py | Фильтрация по tool name |
| `ThinSubagentOrchestrator` | orchestration/thin_subagent.py | Backend для spawn_agent tool |
| `CommandRegistry` | commands/registry.py | Парсинг /commands в user input |
| `CommandRegistry.to_tool_definitions()` | commands/registry.py | Экспонирование commands как tools |
| `DefaultToolPolicy` | policy/tool_policy.py | Enforce allow/deny в ToolExecutor |
| `SEND_MESSAGE_TOOL_SPEC` | orchestration/message_tools.py | Паттерн для subagent tool spec |
| `collect_runtime_output()` | orchestration/runtime_helpers.py | Сбор output субагента |
