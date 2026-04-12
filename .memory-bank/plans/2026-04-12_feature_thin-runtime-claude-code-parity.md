# Plan: ThinRuntime → Claude Code-like функциональность

**Тип**: feature
**Дата**: 2026-04-12
**Версия**: swarmline 1.4.1 → 1.5.0
**Аудит**: `reports/2026-04-12_audit_thin-runtime-gaps.md`

## Цель

Превратить ThinRuntime из "lightweight LLM loop" в полноценный runtime с системой хуков, LLM-initiated субагентов, slash-команд и tool policy — на уровне возможностей Claude Code, но multi-provider.

## Принципы

- **TDD**: тесты → реализация → рефакторинг. Каждая фаза начинается с red tests.
- **Contract-first**: новые Protocol/ABC → contract tests → concrete implementation.
- **Обратная совместимость**: все существующие тесты (4263) должны проходить на каждом этапе.
- **Инкрементальность**: каждая фаза независимо деплоится, ничего не ломает.
- **Strangler Fig**: поэтапная замена pseudo tool-calling на native, старый путь работает пока новый не готов.

## Версионирование

Вся работа = **один minor release** (1.5.0). Внутренние коммиты в private repo без бампа версии. Release когда все фазы завершены и стабильны.

---

## Phase 1: Hook Dispatch в ThinRuntime (приоритет P0 — безопасность)

**Почему первая**: SecurityGuard middleware молча не работает для thin runtime. Это security gap.

### 1.1 Hook Dispatcher Protocol + типы

**Файлы**: `src/swarmline/hooks/dispatcher.py` (новый)

**Задачи**:
- Определить `HookDispatcher` Protocol: `dispatch_pre_tool(tool_name, tool_input) -> HookResult`
- Определить `HookResult`: `action: Literal["allow", "block", "modify"]`, `modified_input: dict | None`, `message: str | None`
- Определить `dispatch_post_tool(tool_name, tool_input, tool_output) -> str | None` (None = не менять)
- Определить `dispatch_stop(result_text: str) -> None`
- Определить `dispatch_user_prompt(prompt: str) -> str` (может трансформировать)
- Реализовать `DefaultHookDispatcher(registry: HookRegistry)` — конкретная реализация

**Тесты (RED first)**: `tests/unit/test_hook_dispatcher.py`
- `test_dispatch_pre_tool_no_hooks_returns_allow`
- `test_dispatch_pre_tool_with_block_hook_returns_block`
- `test_dispatch_pre_tool_with_modify_hook_returns_modified_input`
- `test_dispatch_pre_tool_matcher_filters_by_tool_name`
- `test_dispatch_pre_tool_multiple_hooks_first_block_wins`
- `test_dispatch_post_tool_no_hooks_returns_none`
- `test_dispatch_post_tool_modifies_output`
- `test_dispatch_stop_calls_all_registered_callbacks`
- `test_dispatch_user_prompt_transforms_text`
- `test_dispatch_user_prompt_no_hooks_returns_original`

**DoD**:
- [ ] `HookDispatcher` Protocol с ≤5 методами (ISP)
- [ ] `HookResult` frozen dataclass с action/modified_input/message
- [ ] `DefaultHookDispatcher` реализует Protocol
- [ ] 10+ unit тестов, все green
- [ ] `ruff check` + `mypy` clean на изменённых файлах
- [ ] Нет изменений в существующих файлах (только новые)

### 1.2 Интеграция hooks в ToolExecutor

**Файлы**: `src/swarmline/runtime/thin/executor.py` (модификация)

**Задачи**:
- Добавить `hook_dispatcher: HookDispatcher | None = None` в конструктор `ToolExecutor`
- Перед выполнением tool: `dispatcher.dispatch_pre_tool(name, args)` → если block → return error JSON
- После выполнения tool: `dispatcher.dispatch_post_tool(name, args, result)` → если modified → использовать modified
- Если `hook_dispatcher is None` — поведение не меняется (обратная совместимость)

**Тесты (RED first)**: `tests/unit/test_executor_hooks.py`
- `test_executor_without_dispatcher_works_as_before`
- `test_executor_pre_tool_block_returns_error`
- `test_executor_pre_tool_modify_passes_modified_args`
- `test_executor_pre_tool_allow_proceeds_normally`
- `test_executor_post_tool_modifies_output`
- `test_executor_pre_tool_block_does_not_execute_tool`
- `test_executor_mcp_tool_also_triggers_hooks`

**DoD**:
- [ ] `ToolExecutor.__init__` принимает optional `hook_dispatcher`
- [ ] PreToolUse вызывается перед каждым tool call (local + MCP)
- [ ] PostToolUse вызывается после каждого tool call
- [ ] Block → tool не выполняется, возвращается JSON error
- [ ] Modify → изменённые args/output передаются дальше
- [ ] None dispatcher → поведение идентично текущему (4263 теста проходят)
- [ ] 7+ unit тестов green
- [ ] Интеграционный тест: SecurityGuard middleware → HookRegistry → DefaultHookDispatcher → ToolExecutor → tool blocked

### 1.3 Интеграция hooks в ThinRuntime.run()

**Файлы**: `src/swarmline/runtime/thin/runtime.py` (модификация)

**Задачи**:
- Добавить `hook_registry: HookRegistry | None = None` в конструктор `ThinRuntime`
- В начале `run()`: если есть UserPromptSubmit hooks → dispatch, может трансформировать prompt
- Создать `DefaultHookDispatcher` и передать в `ToolExecutor`
- В конце `run()` (finally): если есть Stop hooks → dispatch
- Прокинуть `hook_registry` через `RuntimeFactory.create()` → kwargs

**Тесты (RED first)**: `tests/unit/test_thin_runtime_hooks.py`
- `test_thin_runtime_without_hooks_works_as_before`
- `test_thin_runtime_pre_tool_hook_blocks_tool`
- `test_thin_runtime_post_tool_hook_modifies_output`
- `test_thin_runtime_stop_hook_called_on_completion`
- `test_thin_runtime_stop_hook_called_on_error`
- `test_thin_runtime_user_prompt_hook_transforms_input`
- `test_thin_runtime_security_guard_blocks_tool_via_hooks`

**Тесты интеграционные**: `tests/integration/test_thin_hooks_integration.py`
- `test_security_guard_middleware_blocks_tool_in_thin_runtime`
- `test_tool_output_compressor_compresses_in_thin_runtime`
- `test_hooks_from_agent_config_reach_thin_runtime`

**DoD**:
- [ ] HookRegistry пробрасывается через Agent → RuntimeFactory → ThinRuntime → ToolExecutor
- [ ] UserPromptSubmit hook вызывается в начале run()
- [ ] Stop hook вызывается в конце run() (нормальное завершение + ошибка)
- [ ] SecurityGuard middleware реально блокирует tools в thin runtime
- [ ] ToolOutputCompressor реально сжимает output в thin runtime
- [ ] 7+ unit тестов + 3 интеграционных green
- [ ] Все 4263+ существующих тестов проходят
- [ ] `ruff check` + `mypy` clean

### 1.4 Прокидывание hooks через Agent → RuntimeFactory → ThinRuntime

**Файлы**: 
- `src/swarmline/agent/runtime_wiring.py` (модификация)
- `src/swarmline/runtime/factory.py` (модификация)

**Задачи**:
- `build_portable_runtime_plan()`: извлечь `hooks` из `AgentConfig` → добавить в `create_kwargs`
- `RuntimeFactory._create_thin()`: передать `hook_registry` в ThinRuntime
- Merge hooks из middleware (`get_hooks()`) с hooks из config

**Тесты**: `tests/unit/test_hook_wiring.py`
- `test_agent_config_hooks_reach_thin_runtime`
- `test_middleware_hooks_merged_with_config_hooks`
- `test_no_hooks_no_dispatcher_created`

**DoD**:
- [ ] `AgentConfig(hooks=HookRegistry(...))` → hooks работают в thin runtime
- [ ] Middleware hooks merge'd с config hooks
- [ ] Без hooks — никаких изменений в поведении
- [ ] 3+ unit тестов green

---

## Phase 2: Tool Policy Enforcement в ThinRuntime (приоритет P0 — безопасность)

### 2.1 Интеграция DefaultToolPolicy в ToolExecutor

**Файлы**: `src/swarmline/runtime/thin/executor.py` (модификация)

**Задачи**:
- Добавить `tool_policy: DefaultToolPolicy | None = None` в ToolExecutor
- Перед выполнением (после PreToolUse hook): `policy.can_use_tool(input)` → если deny → return error JSON
- Policy check выполняется ПОСЛЕ hooks (hooks могут modify, policy проверяет результат)
- Если `tool_policy is None` — поведение не меняется

**Тесты (RED first)**: `tests/unit/test_executor_policy.py`
- `test_executor_without_policy_allows_all`
- `test_executor_denied_tool_returns_error`
- `test_executor_allowed_tool_executes`
- `test_executor_mcp_tool_checked_by_policy`
- `test_executor_policy_runs_after_pre_hook_modify`
- `test_executor_policy_deny_does_not_execute_tool`

**DoD**:
- [ ] `ToolExecutor` принимает optional `tool_policy`
- [ ] Denied tools не выполняются, возвращается JSON error с причиной
- [ ] Policy check после PreToolUse hooks (hooks могут modify args/name)
- [ ] None policy → всё разрешено (обратная совместимость)
- [ ] 6+ unit тестов green
- [ ] Все существующие тесты проходят

### 2.2 Прокидывание policy через Agent → ThinRuntime

**Файлы**:
- `src/swarmline/agent/runtime_wiring.py`
- `src/swarmline/runtime/factory.py`

**Задачи**:
- `AgentConfig` уже имеет поле для tools. Добавить `tool_policy: DefaultToolPolicy | None = None`
- Или: использовать `SkillRegistry.get_tool_allowlist()` для автоматического создания policy
- Передать policy через `create_kwargs` в ThinRuntime → ToolExecutor

**Тесты**: `tests/unit/test_policy_wiring.py`
- `test_agent_with_policy_thin_runtime_denies_tool`
- `test_agent_without_policy_thin_runtime_allows_all`

**DoD**:
- [ ] Policy пробрасывается Agent → RuntimeFactory → ThinRuntime → ToolExecutor
- [ ] E2E: `Agent(config, tool_policy=...)` → thin runtime → tool denied
- [ ] 2+ тестов green

---

## Phase 3: LLM-Initiated Subagents (приоритет P1 — ключевая фича)

### 3.1 SubagentTool spec + types

**Файлы**: `src/swarmline/runtime/thin/subagent_tool.py` (новый)

**Задачи**:
- Определить `SUBAGENT_TOOL_SPEC: ToolSpec` — tool "spawn_agent" с JSON Schema:
  ```
  { "task": str (required), "system_prompt": str (optional), "tools": list[str] (optional) }
  ```
- Определить `SubagentToolConfig`: `max_concurrent: int = 4`, `max_depth: int = 3`, `shared_tools: list[str]`, `timeout_seconds: int = 300`
- Return format: JSON с `agent_id`, `status`, `result`

**Тесты (RED first)**: `tests/unit/test_subagent_tool.py`
- `test_subagent_tool_spec_valid_json_schema`
- `test_subagent_tool_spec_task_required`
- `test_subagent_tool_config_defaults`

**DoD**:
- [ ] `SUBAGENT_TOOL_SPEC` — валидный ToolSpec с JSON Schema
- [ ] `SubagentToolConfig` frozen dataclass
- [ ] 3+ unit тестов green

### 3.2 SubagentTool executor

**Файлы**: `src/swarmline/runtime/thin/subagent_tool.py` (продолжение)

**Задачи**:
- `create_subagent_executor(orchestrator, config, parent_tools)` → async callable
- Executor: парсит args → создаёт `SubagentSpec` → `orchestrator.spawn(spec, task)` → `orchestrator.wait(agent_id)` → return result JSON
- Enforce `max_depth` — субагент не может spawn'ить свои субагенты глубже max_depth
- Enforce `max_concurrent` — через orchestrator
- Timeout — через `asyncio.wait_for`
- Наследование tools: субагент получает subset tools из parent (по `tools` аргументу)

**Тесты (RED first)**: `tests/unit/test_subagent_executor.py`
- `test_subagent_spawns_and_returns_result`
- `test_subagent_timeout_returns_error`
- `test_subagent_max_depth_exceeded_returns_error`
- `test_subagent_max_concurrent_exceeded_returns_error`
- `test_subagent_inherits_parent_tools`
- `test_subagent_with_custom_system_prompt`
- `test_subagent_failure_returns_error_json`
- `test_subagent_task_required_validation`

**DoD**:
- [ ] `create_subagent_executor()` возвращает async callable
- [ ] Субагент запускается через `ThinSubagentOrchestrator`
- [ ] max_depth enforcement (JSON error при превышении)
- [ ] max_concurrent enforcement (JSON error при превышении)
- [ ] Timeout enforcement (asyncio.wait_for)
- [ ] Tool inheritance (subset из parent)
- [ ] Error handling — ошибки субагента → JSON error, не crash parent
- [ ] 8+ unit тестов green

### 3.3 Интеграция subagent tool в ThinRuntime

**Файлы**:
- `src/swarmline/runtime/thin/runtime.py`
- `src/swarmline/runtime/thin/builtin_tools.py`
- `src/swarmline/runtime/factory.py`

**Задачи**:
- Добавить `subagent_config: SubagentToolConfig | None = None` в ThinRuntime
- Если config не None: создать `ThinSubagentOrchestrator`, `create_subagent_executor`, зарегистрировать как local tool
- Добавить `SUBAGENT_TOOL_SPEC` в active_tools
- `AgentConfig`: добавить `subagent_config: SubagentToolConfig | None = None`
- `RuntimeFactory._create_thin()`: прокинуть subagent_config

**Тесты (RED first)**:
- `tests/unit/test_thin_subagent_integration.py`:
  - `test_thin_runtime_without_subagent_config_no_spawn_tool`
  - `test_thin_runtime_with_subagent_config_has_spawn_tool`
  - `test_thin_runtime_subagent_tool_in_active_tools`
- `tests/integration/test_thin_subagent_e2e.py`:
  - `test_agent_with_subagents_thin_runtime_tool_available`
  - `test_subagent_executes_task_and_returns`

**DoD**:
- [ ] `ThinRuntime(subagent_config=...)` → "spawn_agent" tool доступен LLM
- [ ] LLM может вызвать spawn_agent → субагент создаётся → результат возвращается
- [ ] Без subagent_config — поведение не меняется
- [ ] Субагент runs в отдельном ThinRuntime instance
- [ ] 3+ unit + 2 integration тестов green
- [ ] Все существующие тесты проходят

---

## Phase 4: Command Routing в ThinRuntime (приоритет P2)

### 4.1 Command interceptor

**Файлы**: `src/swarmline/runtime/thin/command_interceptor.py` (новый)

**Задачи**:
- `CommandInterceptor(registry: CommandRegistry)`
- `intercept(user_text: str) -> CommandInterceptResult`
  - Если `registry.is_command(user_text)`: parse → execute → return `CommandInterceptResult(handled=True, response=...)`
  - Если нет: return `CommandInterceptResult(handled=False)`
- `CommandInterceptResult`: `handled: bool`, `response: str | None`, `inject_context: str | None`
- Поддержка двух режимов: "handle and respond" (команда обработана, вернуть ответ) и "inject context" (добавить результат команды в system prompt для LLM)

**Тесты (RED first)**: `tests/unit/test_command_interceptor.py`
- `test_non_command_not_intercepted`
- `test_slash_command_intercepted_and_executed`
- `test_unknown_command_returns_error`
- `test_command_with_args_parsed_correctly`
- `test_command_result_in_response`
- `test_inject_context_mode`

**DoD**:
- [ ] `CommandInterceptor` парсит /commands из user input
- [ ] Известные команды выполняются через `CommandRegistry`
- [ ] Неизвестные → error message
- [ ] Non-command text → passthrough
- [ ] 6+ unit тестов green

### 4.2 Интеграция в ThinRuntime.run()

**Файлы**: `src/swarmline/runtime/thin/runtime.py`

**Задачи**:
- Добавить `command_registry: CommandRegistry | None = None` в ThinRuntime
- В начале `run()` после UserPromptSubmit hook: проверить `CommandInterceptor.intercept(user_text)`
- Если handled: yield `RuntimeEvent.final(response)` и return (не вызывать LLM)
- Если inject_context: добавить context в system_prompt
- `AgentConfig`: добавить `command_registry: CommandRegistry | None = None`

**Тесты**:
- `test_thin_runtime_command_intercept_returns_without_llm_call`
- `test_thin_runtime_non_command_proceeds_to_llm`
- `test_thin_runtime_inject_context_added_to_prompt`
- `test_thin_runtime_without_registry_ignores_commands`

**DoD**:
- [ ] /command intercepted перед LLM call
- [ ] Handled commands → immediate response, no LLM call
- [ ] No registry → passthrough (обратная совместимость)
- [ ] 4+ тестов green
- [ ] Все существующие тесты проходят

---

## Phase 5: Native Tool Calling (приоритет P2 — quality)

### 5.1 Native tool call protocol для Anthropic

**Файлы**: `src/swarmline/runtime/thin/native_tools.py` (новый)

**Задачи**:
- `NativeToolCallAdapter` Protocol: `format_tools(specs) -> provider_format`, `parse_response(response) -> list[ActionEnvelope]`
- `AnthropicNativeToolAdapter`: конвертирует ToolSpec → Anthropic tools format, парсит tool_use content blocks
- Поддержка parallel tool calls (несколько tool_use blocks в одном response)

**Тесты (RED first)**: `tests/unit/test_native_tools.py`
- `test_anthropic_format_tools_converts_specs`
- `test_anthropic_parse_single_tool_call`
- `test_anthropic_parse_parallel_tool_calls`
- `test_anthropic_parse_text_only_no_tools`
- `test_anthropic_parse_mixed_text_and_tools`

**DoD**:
- [ ] `AnthropicNativeToolAdapter` конвертирует ToolSpec ↔ Anthropic format
- [ ] Parallel tool calls parsed (multiple tool_use blocks)
- [ ] 5+ unit тестов green

### 5.2 OpenAI/Google native tool adapters

**Файлы**: `src/swarmline/runtime/thin/native_tools.py` (продолжение)

**Задачи**:
- `OpenAINativeToolAdapter`: ToolSpec → OpenAI functions/tools format, парсит tool_calls
- `GoogleNativeToolAdapter`: ToolSpec → Google function declarations, парсит function calls
- `resolve_native_adapter(provider: str) -> NativeToolCallAdapter | None`

**Тесты (RED first)**: `tests/unit/test_native_tools_openai.py`, `tests/unit/test_native_tools_google.py`
- По 5 тестов на каждый адаптер (аналогично Anthropic)

**DoD**:
- [ ] 3 adapter'а: Anthropic, OpenAI, Google
- [ ] Каждый конвертирует ToolSpec ↔ provider format
- [ ] `resolve_native_adapter()` по provider name
- [ ] 10+ unit тестов green

### 5.3 Интеграция native tools в react strategy

**Файлы**:
- `src/swarmline/runtime/thin/react_strategy.py`
- `src/swarmline/runtime/thin/llm_client.py`
- `src/swarmline/runtime/thin/llm_providers.py`

**Задачи**:
- Добавить `use_native_tools: bool = False` в RuntimeConfig
- Если True: `llm_call` передаёт `tools` parameter через adapter
- `react_strategy.run_react()`: вместо `parse_envelope()` из текста → парсить tool calls из native response
- Поддержка parallel execution: несколько tool calls → `asyncio.gather` → все results → append messages
- Fallback: если native tools fail → revert to JSON-in-text (Strangler Fig)

**Тесты**:
- `test_react_native_tools_single_call`
- `test_react_native_tools_parallel_calls`
- `test_react_native_tools_fallback_to_json`
- `test_react_native_tools_disabled_uses_json`

**DoD**:
- [ ] `use_native_tools=True` → provider native tool calling
- [ ] Parallel tool calls → asyncio.gather
- [ ] `use_native_tools=False` (default) → JSON-in-text (обратная совместимость)
- [ ] Fallback при ошибке native → JSON-in-text
- [ ] 4+ тестов green
- [ ] Все существующие тесты проходят (default = False)

---

## Phase 6: Стабилизация и документация (приоритет P3)

### 6.1 Integration тесты всех фич вместе

**Файлы**: `tests/integration/test_thin_full_stack.py` (новый)

**Задачи**:
- Тест: Agent с hooks + policy + subagents + commands → thin runtime → всё работает вместе
- Тест: hooks блокируют tool → subagent не может вызвать заблокированный tool
- Тест: command в subagent context
- Тест: native tools + hooks + policy

**DoD**:
- [ ] 4+ integration тестов green
- [ ] Полный стек: Agent → hooks → policy → commands → subagents → thin runtime
- [ ] Нет race conditions в subagent + hooks

### 6.2 Документация

**Файлы**:
- `docs/thin-runtime.md` (новый или обновление `docs/runtimes.md`)
- `CHANGELOG.md` (обновление)
- Обновление `docs/releasing.md` decision log

**Задачи**:
- Документировать hooks в ThinRuntime (примеры PreToolUse/PostToolUse)
- Документировать subagent tool (примеры, конфигурация, ограничения)
- Документировать slash commands в ThinRuntime
- Документировать native tool calling (opt-in, fallback)
- CHANGELOG entry для v1.5.0

**DoD**:
- [ ] docs/thin-runtime.md с примерами кода для каждой фичи
- [ ] CHANGELOG v1.5.0 с breaking changes (если есть) и features
- [ ] Примеры в examples/ (по желанию)

### 6.3 Финальная валидация

**Задачи**:
- `pytest -q` — все тесты green
- `ruff check src/ tests/` — clean
- `mypy src/swarmline/` — clean
- `pytest -m integration` — green
- Coverage ≥ 85%

**DoD**:
- [ ] Все gate'ы green
- [ ] Coverage новых файлов ≥ 95%
- [ ] Общий coverage ≥ 85%

---

## Зависимости между фазами

```
Phase 1 (Hooks)     ← Phase 2 (Policy) зависит от hook dispatch order
    ↓                       ↓
Phase 3 (Subagents) ← нужны hooks для контроля subagent tools
    ↓
Phase 4 (Commands)  ← независима, но логично после hooks
    ↓
Phase 5 (Native Tools) ← независима, Strangler Fig
    ↓
Phase 6 (Stabilization) ← после всех фич
```

**Параллельно можно**: Phase 4 (Commands) параллельно с Phase 3 (Subagents) после Phase 1-2.
**Phase 5 (Native Tools)** можно начать параллельно с Phase 3-4 (независимый Strangler Fig).

## Оценка объёма

| Phase | Новые файлы | Изменённые файлы | Новые тесты | Сложность |
|-------|-------------|-------------------|-------------|-----------|
| 1. Hooks | 1 | 3 | ~27 | Средняя |
| 2. Policy | 0 | 3 | ~8 | Низкая |
| 3. Subagents | 1 | 3 | ~13 | Высокая |
| 4. Commands | 1 | 2 | ~10 | Средняя |
| 5. Native Tools | 1 | 3 | ~19 | Высокая |
| 6. Stabilization | 1 | 2 | ~4 | Низкая |
| **Итого** | **5** | **~10** | **~81** | — |

## Риски

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| Native tool calling ломает стриминг у какого-то provider | Средняя | Strangler Fig: fallback на JSON-in-text, `use_native_tools` default=False |
| Subagent deadlock (parent ждёт child, child ждёт parent tool) | Низкая | max_depth + timeout + no shared locks |
| Hook callback exceptions ломают tool execution | Средняя | try/except в dispatcher, log + allow on hook error |
| Breaking change в RuntimeConfig/AgentConfig | Низкая | Все новые поля optional с None default |
