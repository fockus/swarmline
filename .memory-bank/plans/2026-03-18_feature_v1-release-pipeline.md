# v1.0.0-core Release Pipeline: Tech Debt → Docs → PyPI
Дата: 2026-03-18
Тип: feature
Статус: 🟡 В работе

## Контекст

Все продуктовые фазы (6-10A) завершены. 2357 тестов, 0 failures, coverage 89%.
Перед v1.0.0-core release нужно:
1. Закрыть технический долг (ruff 60 errors, mypy 27 errors, Wave 2/3 audit remediation)
2. Актуализировать документацию (CHANGELOG, Getting Started, mkdocs site)
3. Выпустить на PyPI

Текущие метрики:
- `ruff check src/`: 11 errors (все E402 — import order в deepagents.py)
- `ruff check tests/`: 49 errors (7 F401 unused imports, 16 E402, остальное мелочь)
- `mypy src/swarmline/`: 27 errors в 17 файлах (5 в llm_providers, 4 в sandbox_docker, 4 в sqlite, остальные по 1-2 в optional deps)
- `pytest -q`: 2357 passed, 0 failed
- `pyproject.toml version`: 0.5.0 (нужен bump до 1.0.0)
- CHANGELOG.md: есть, содержит [Unreleased] + [1.0.0-core]
- mkdocs.yml: настроен, 26 страниц docs/
- examples/: 27 рабочих примеров

## Scope

**Входит:**
- Ruff cleanup (src/ + tests/)
- Mypy cleanup (реальные ошибки + стратегия для optional deps)
- Wave 2 remaining (session/runtime migration cleanup — Phase 5 remediation)
- Wave 3 Phase 6 (factory/registry hardening)
- CHANGELOG.md финализация
- Getting Started guide обновление с новыми фичами
- mkdocs site проверка и актуализация
- Version bump 0.5.0 → 1.0.0
- PyPI release (sdist + wheel)

**НЕ входит:**
- Phase 9 Full (enterprise extras) — post-release
- Phase 10 rest (MCP, OAuth, etc.) — post-release
- Phase 11 (OpenAI Agents SDK) — заморожена
- Новые фичи

## Архитектурные решения

1. **Ruff**: auto-fix (`--fix`) для safe fixes, ручная правка E402 (import reorder)
2. **Mypy**: разделить на реальные type issues vs missing optional stubs. Для optional deps (`deepagents`, `crawl4ai`, `tavily`, etc.) — `# type: ignore[import-not-found]` с комментарием. Для реальных ошибок — fix.
3. **Wave 2/3 remediation**: по existing plan из `2026-03-18_fix_library-audit-remediation.md`, фазы 5-6
4. **Docs**: incremental update, не полная переписка
5. **Release**: `hatch build` + `twine upload`

## Этапы

### Этап 1: Ruff cleanup — src/

**Цель:** `ruff check src/` = 0 errors
**Файлы:** `src/swarmline/runtime/deepagents.py`, `src/swarmline/runtime/deepagents_builtins.py`

**Реализация:**
1. `ruff check --fix src/` для safe auto-fixes
2. Ручная правка E402 в `deepagents.py` — перенести imports выше или добавить `noqa` с причиной (lazy imports для optional deps)
3. Проверить что ничего не сломалось: `pytest -q`

**Тесты:**
- Unit: существующие тесты не должны ломаться
- Проверка: `ruff check src/` = 0

**DoD:**
- [ ] `ruff check src/` выдаёт 0 errors
- [ ] `pytest -q` = 2357+ passed, 0 failed
- [ ] Нет подавления ошибок без комментария-причины

### Этап 2: Ruff cleanup — tests/

**Цель:** `ruff check tests/` = 0 errors
**Файлы:** ~15 test files с unused imports и E402

**Реализация:**
1. `ruff check --fix tests/` для safe auto-fixes (7 unused imports)
2. Ручная правка оставшихся E402
3. `pytest -q` для проверки

**Тесты:**
- `ruff check tests/` = 0
- `pytest -q` green

**DoD:**
- [ ] `ruff check tests/` выдаёт 0 errors
- [ ] `pytest -q` = 2357+ passed, 0 failed

### Этап 3: Mypy cleanup

**Цель:** `mypy src/swarmline/` = 0 errors (или определённый baseline с документированными исключениями)
**Файлы:** 17 файлов с mypy ошибками

**Реализация:**
1. Классифицировать 27 ошибок:
   - **import-not-found** (deepagents, crawl4ai, etc.): `# type: ignore[import-not-found]` + lazy import guard уже на месте
   - **Реальные type issues** (llm_providers, sqlite, structured_output, options_builder): исправить типы
   - **sandbox_docker** (4 errors): docker SDK stubs — `# type: ignore` с причиной
2. Починить реальные ошибки в llm_providers.py (5 errors — stream/await typing)
3. Починить sqlite.py (4 errors)
4. Починить structured_output.py (2 errors)
5. Починить options_builder.py (1 error — Literal type)
6. Настроить `mypy.ini` / `pyproject.toml` секцию `[tool.mypy]` для optional deps

**Тесты:**
- `mypy src/swarmline/` = 0 errors (или agreed baseline)
- `pytest -q` green

**DoD:**
- [ ] `mypy src/swarmline/` = 0 errors (или ≤5 documented optional-dep exclusions)
- [ ] Реальные type issues (llm_providers, sqlite, structured_output, options_builder) — все исправлены
- [ ] Каждый `# type: ignore` имеет `[error-code]` и комментарий-причину
- [ ] `pytest -q` green

### Этап 4: Wave 2 remaining — Session/runtime migration cleanup (Phase 5 remediation)

**Цель:** Убрать дублирование wiring-логики между Agent, Conversation, SessionManager
**Файлы:** `src/swarmline/agent/agent.py`, `src/swarmline/agent/conversation.py`, `src/swarmline/session/manager.py`

**Реализация:**
1. Выделить shared composition helper для runtime creation + tool wiring + hook merge
2. Перевести Agent и Conversation на shared path
3. Локализовать legacy RuntimePort path (adapter shim only)
4. Проверить что все entrypoints имеют одинаковую семантику

**Тесты (TDD):**
- Unit: тесты на shared composition helper (creation, wiring, hook merge)
- Integration: test_agent_conversation_semantics_parity — Agent.query vs Conversation.say дают одинаковый результат
- Regression: `pytest tests/unit/test_agent* tests/integration/ -q`

**DoD:**
- [ ] Agent, Conversation, SessionManager не дублируют wiring-логику
- [ ] Legacy RuntimePort path изолирован в отдельный adapter/shim
- [ ] Количество cross-calls между Agent и Conversation сокращено на ≥30%
- [ ] `pytest -q` green
- [ ] Нет нарушений SRP (файлы ≤400 строк или обоснованно)
- [ ] Self-review пройден

### Этап 5: Wave 2 remaining — Factory/registry hardening (Phase 6 remediation)

**Цель:** Public imports не возвращают None, RuntimeFactory и registry согласованы
**Файлы:** `src/swarmline/runtime/factory.py`, `src/swarmline/runtime/registry.py`, `src/swarmline/runtime/__init__.py`, `src/swarmline/hooks/__init__.py`, `src/swarmline/memory/__init__.py`, `src/swarmline/skills/__init__.py`

**Реализация:**
1. Канонизировать runtime creation через registry path
2. Вычистить backward-compatible re-exports: lazy getter или fail-fast proxy
3. Привести RuntimeFactory override path к корректному effective_config
4. cli/thin/deepagents creation semantics единообразны

**Тесты (TDD):**
- Unit: test_optional_import_fail_fast — импорт несуществующей optional dep даёт ImportError с понятным message
- Unit: test_runtime_factory_registry_consistency — factory names = registry names
- Integration: test_runtime_creation_all_paths — thin/cli создаются единообразно

**DoD:**
- [ ] Public import не возвращает None вместо API symbol
- [ ] RuntimeFactory и registry согласованы по built-in runtime names
- [ ] cli/thin/deepagents creation единообразны
- [ ] `ruff check src/` = 0
- [ ] `pytest -q` green

### Этап 6: CHANGELOG.md финализация

**Цель:** CHANGELOG.md содержит полные записи для v0.6.0, v0.7.0, v1.0.0-core с актуальным содержимым
**Файлы:** `CHANGELOG.md`

**Реализация:**
1. Проверить [Unreleased] → переименовать в актуальную версию или merge в [1.0.0-core]
2. Убедиться что все фичи Phase 6-10A перечислены
3. Добавить Breaking Changes секцию если есть
4. Добавить examples/ (27 runnable examples) в docs
5. Проверить даты, ссылки

**Тесты:**
- Manual: CHANGELOG.md парсится стандартными tools (keep-a-changelog format)
- Grep: все key features из checklist.md упомянуты

**DoD:**
- [ ] CHANGELOG.md содержит записи для всех выпущенных версий
- [ ] [Unreleased] секция пуста или содержит только post-release items
- [ ] Все Phase 6-10A фичи перечислены в соответствующих версиях
- [ ] Формат соответствует keep-a-changelog

### Этап 7: Getting Started guide обновление

**Цель:** docs/getting-started.md отражает актуальный API (Agent, @tool, structured output, middleware, runtimes)
**Файлы:** `docs/getting-started.md`

**Реализация:**
1. Проверить все code snippets на актуальность (event types, API signatures)
2. Добавить секции про новые фичи: CLI runtime, multi-agent, RAG, workflow graph
3. Обновить install instructions: `pip install swarmline[thin]`
4. Убедиться что примеры копируемы и запускаемы

**Тесты:**
- Manual: каждый code snippet из guide можно скопировать и запустить
- Grep: event types в docs = актуальным (`text_delta`, `tool_use_start`, etc.)

**DoD:**
- [ ] Все code snippets в getting-started.md используют актуальный API
- [ ] Event types = каноничные (`text_delta`, `tool_use_start`, `tool_use_result`, `done`)
- [ ] Install instructions актуальны
- [ ] Новые фичи (CLI runtime, multi-agent, RAG) упомянуты

### Этап 8: mkdocs site audit и актуализация

**Цель:** Все 26 страниц docs/ синхронизированы с текущим API
**Файлы:** `docs/*.md`, `mkdocs.yml`

**Реализация:**
1. Проверить каждую страницу на drifted API names/signatures
2. Обновить cli-runtime.md, multi-agent.md с актуальными примерами
3. Проверить mkdocs.yml nav — все страницы в навигации
4. `mkdocs build` без ошибок

**Тесты:**
- `mkdocs build` = success, 0 warnings
- Grep: нет устаревших event names в docs/ (`tool_call_started` → `tool_use_start`, etc.)

**DoD:**
- [ ] `mkdocs build` проходит без ошибок и warnings
- [ ] Нет устаревших API names в docs/
- [ ] Все 26+ страниц в mkdocs.yml nav
- [ ] Code snippets в docs синхронизированы с актуальным API

### Этап 9: Version bump + PyPI release

**Цель:** swarmline v1.0.0 опубликована на PyPI
**Файлы:** `pyproject.toml`, `src/swarmline/__init__.py` (если есть __version__)

**Реализация:**
1. Bump version: 0.5.0 → 1.0.0 в `pyproject.toml`
2. Обновить `__version__` если определён в `__init__.py`
3. `hatch build` — создать sdist + wheel
4. `twine check dist/*` — валидация пакета
5. `twine upload dist/*` — загрузить на PyPI
6. Git tag `v1.0.0`

**Тесты:**
- `hatch build` = success
- `twine check dist/*` = PASSED
- `pip install swarmline` из PyPI работает

**DoD:**
- [ ] `pyproject.toml` version = "1.0.0"
- [ ] `hatch build` = success (sdist + wheel)
- [ ] `twine check dist/*` = PASSED
- [ ] Package uploaded to PyPI
- [ ] Git tag `v1.0.0` создан
- [ ] `pip install swarmline` из чистого venv работает

### Этап 10: Финальная проверка

**Цель:** Всё работает вместе, release quality gate пройден

**Тесты:**
- Полный `pytest -q` green
- `ruff check src/ tests/` = 0 errors
- `mypy src/swarmline/` = 0 errors (или agreed baseline)
- `mkdocs build` success
- Все 27 examples запускаются

**DoD:**
- [ ] `pytest -q` = 2357+ passed, 0 failed
- [ ] `ruff check src/ tests/` = 0
- [ ] `mypy` gate green
- [ ] `mkdocs build` = success
- [ ] Все 27 examples/ работают без ошибок
- [ ] CHANGELOG.md, Getting Started, mkdocs site — актуальны
- [ ] Coverage ≥ 89%
- [ ] Нет TODO/FIXME/HACK в новом коде

## Зависимости между этапами

```
Этап 1 (ruff src) ──┐
Этап 2 (ruff tests) ┼── можно параллелить
Этап 3 (mypy) ──────┘
         │
         ▼
Этап 4 (session cleanup) ──┐
Этап 5 (factory hardening) ┘── можно параллелить, но после 1-3
         │
         ▼
Этап 6 (CHANGELOG) ──────┐
Этап 7 (Getting Started) ┼── можно параллелить
Этап 8 (mkdocs audit) ───┘
         │
         ▼
Этап 9 (version bump + PyPI) ← зависит от всех предыдущих
         │
         ▼
Этап 10 (финальная проверка) ← после release
```

## Риски и mitigation

| Риск | Вероятность | Влияние | Mitigation |
|------|-------------|---------|------------|
| mypy ошибки в optional deps неисправимы без stubs | Средняя | Блокирует mypy gate | Использовать `# type: ignore[import-not-found]` + mypy config overrides |
| Session/runtime refactor (Phase 5) ломает backward compat | Средняя | Regression в тестах | TDD: regression tests first, strangler fig pattern |
| PyPI credentials не настроены | Низкая | Блокирует release | Проверить заранее, настроить `~/.pypirc` или env vars |
| mkdocs build падает из-за broken links | Низкая | Блокирует docs | `mkdocs build --strict` для раннего обнаружения |
| deepagents 0.4.11 совместимость с v1.0.0 | Низкая | Runtime issues | Документировать в CHANGELOG как known limitation |

## Оценка

| Этап | Сложность | Оценка |
|------|-----------|--------|
| 1. Ruff src | Низкая | 15 мин |
| 2. Ruff tests | Низкая | 20 мин |
| 3. Mypy | Средняя | 1-2 часа |
| 4. Session cleanup | Высокая | 3-4 часа |
| 5. Factory hardening | Средняя | 1-2 часа |
| 6. CHANGELOG | Низкая | 30 мин |
| 7. Getting Started | Средняя | 1 час |
| 8. mkdocs audit | Средняя | 1-2 часа |
| 9. Version bump + PyPI | Низкая | 30 мин |
| 10. Финальная проверка | Низкая | 30 мин |
| **Итого** | | **~10-13 часов** |
