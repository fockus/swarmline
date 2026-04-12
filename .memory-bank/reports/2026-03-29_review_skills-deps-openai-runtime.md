# Code Review Report
Дата: 2026-03-29 01:30
Файлов проверено: 26 (12 изменённых + 10 новых + 4 example skills)
Строк изменено: +564 / -73 (tracked) + ~600 (untracked new files)

## Критичное

### C1. Path traversal в loader.py через instruction field
**Файл:** `src/swarmline/skills/loader.py:176-181`
Злонамеренный `skill.yaml` может указать `instruction: /etc/passwd` — содержимое файла попадёт в `instruction_md`. Путь `self._project_root / instruction_file_raw` разрешает произвольные пути без валидации.
**Fix:** Добавить `instruction_path.resolve().is_relative_to(self._project_root.resolve())` проверку перед чтением.

### C2. Tool bridge — proxy заглушка, tools не работают
**Файл:** `src/swarmline/runtime/openai_agents/tool_bridge.py:21-24`
Функция `_proxy` всегда возвращает `{"status": "proxy_not_connected"}`. Все local tools в openai_agents runtime сломаны.
**Fix:** Реализовать делегирование к Swarmline tool executor через замыкание `toolspecs_to_agent_tools(specs, executor=...)`, или добавить docstring что это staged stub + feature flag.

### C3. _build_codex_mcp() игнорирует config
**Файл:** `src/swarmline/runtime/openai_agents/runtime.py:179-197`
`codex_sandbox` и `codex_approval_policy` из `OpenAIAgentsConfig` не передаются в MCP server. Staticmethod не имеет доступа к self. Пользователь думает sandbox включён, но настройка не применяется.
**Fix:** Сделать обычным методом, передавать config параметры.

## Серьёзное

### S1. _resolve_thinking молча проглатывает невалидный type
**Файл:** `src/swarmline/runtime/options_builder.py:150-166`
`thinking={"type": "turbo"}` → thinking молча отключается (возвращает None). Нарушение fail-fast.
**Fix:** `raise ValueError(f"Unknown thinking type: {kind!r}")` для неизвестных типов.

### S2. settings.json ошибки парсинга без логирования
**Файл:** `src/swarmline/skills/loader.py:43-61`
`except (json.JSONDecodeError, OSError): continue` — silent failure, debugging nightmare.
**Fix:** Добавить `_log.warning("settings_parse_error", ...)` перед continue.

### S3. settings_mcp_servers property не инициализирован
**Файл:** `src/swarmline/skills/loader.py:137-140`
`getattr(self, "_settings_mcp", {})` — если вызвать до `load_all()`, вернёт пустой dict без предупреждения.
**Fix:** Инициализировать `self._settings_mcp = {}` в `__init__`.

### S4. env поле в OpenAIAgentsConfig — dead config
**Файл:** `src/swarmline/runtime/openai_agents/types.py:22`
Поле `env` нигде не используется. Misleading API.
**Fix:** Удалить до реализации или пробросить в MCP server params.

### S5. Некорректный npm пакет в gemini-cli skill
**Файл:** `examples/skills/gemini-cli/SKILL.md:24`
`npm install -g @anthropic-ai/gemini-cli` — пакет Anthropic не существует для Gemini (продукт Google).
**Fix:** Исправить на актуальную команду установки Google Gemini CLI.

### S6. Нет тестов для tool_bridge.py
**Файл:** `src/swarmline/runtime/openai_agents/tool_bridge.py`
0% покрытие. Ни `toolspec_to_function_tool`, ни `toolspecs_to_agent_tools` не тестируются.
**Fix:** Минимум 3 теста: конвертация, фильтрация is_local, пустой список.

## Замечания

### W1. _FRONTMATTER_RE не обрабатывает trailing newline edge case
**Файл:** `src/swarmline/skills/loader.py:26`
`\n---\s*\n` требует newline после закрывающего `---`. Файл без trailing newline не парсится.
**Fix:** `r"\A---\s*\n(.*?)\n---\s*\n?(.*)"` — сделать trailing newline опциональным.

### W2. Stale docstring в registry.py
**Файл:** `src/swarmline/runtime/registry.py:134`
"Register built-in runtimes: Claude_SDK, DeepAgents, Thin, cli" — не упомянут openai_agents.
**Fix:** Обновить docstring.

### W3. Any overuse в event_mapper.py
**Файл:** `src/swarmline/runtime/openai_agents/event_mapper.py`
Все event params — `Any`. Typo в имени атрибута не детектируется.
**Fix:** Protocol/TypedDict для event типов или explicit comments.

### W4. Typo: `handoff_occured` (одна r)
**Файл:** `src/swarmline/runtime/openai_agents/event_mapper.py:83`
Если SDK использует `handoff_occurred` — branch не сработает.
**Fix:** Проверить по OpenAI SDK docs.

### W5. DRY: TurnAccumulator pattern дублируется
**Файлы:** `runtime.py:108-155` и `claude_code.py:119-181`
Идентичный паттерн accumulation text + tool_calls_count + new_messages + final.
**Fix:** Извлечь `TurnAccumulator` helper (отдельный PR).

### W6. openai-agents>=0.1 — слишком широкий range
**Файл:** `pyproject.toml:89`
SDK активно разрабатывается, breaking changes возможны.
**Fix:** `openai-agents>=0.1,<1.0`.

### W7. relative_to() может бросить ValueError
**Файл:** `src/swarmline/skills/loader.py:189`
Если instruction_path не подпуть project_root — необработанный ValueError.
**Fix:** try/except или is_relative_to() проверка.

### W8. Слабый assert в test_context_manager
**Файл:** `tests/unit/test_openai_agents_runtime.py:297`
`assert rt is not None` — не проверяет бизнес-факт.
**Fix:** `assert isinstance(rt, OpenAIAgentsRuntime)`.

## Тесты
- Unit: ✅ 2223/2223 passed (18 warnings — deprecated SessionState.adapter)
- Lint: ✅ All checks passed (ruff)
- Непокрытые модули: `tool_bridge.py` (0%), `_resolve_thinking` edge cases, path traversal validation

## Соответствие плану
- **Реализовано:** SKILL.md совместимость, description поле, ThinkingConfig миграция, dependency updates, OpenAI Agents runtime scaffold, MCP skills (Codex, Gemini)
- **Не реализовано:** tool_bridge реальная делегация (заглушка), _build_codex_mcp config проброс, тесты tool_bridge
- **Вне плана:** dead code _merge_hooks в conversation.py (pre-existing, не наше)

## Итог
Архитектура чистая, паттерны проекта соблюдены, 2223 теста зелёные. **Главные риски:** path traversal в loader (C1), нерабочий tool bridge (C2), игнорируемый Codex config (C3). Рекомендация: **доработать** — исправить 3 critical + 6 serious issues, затем мержить. Оценка усилий: ~1 час.
