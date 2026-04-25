# Plan: feature — production-v2-phase-01a-ty-strict-foundation

**Baseline commit:** 1eb72b595259086a99f4eecdcf9e5334e633f2f9

## Context

**Problem:** Type checker `ty` в strict-режиме (`respect-type-ignore-comments = false`, `error-on-warning = true`) репортит **75 diagnostics** (фактическое значение `ty check src/swarmline/` на 2026-04-25; в checklist.md:6 устаревшая цифра 70 — будет обновлена). Среди них **11 потенциальных runtime-bug'ов** (вызовы несуществующих методов, type mismatch'ы, `__name__` на partial-функциях). CI gate `ty check` отсутствовал до Stage 1 — регрессии типизации проходили незамеченными.

Это **первый Sprint Phase 01** из roadmap'а v2.0 (см. `.memory-bank/plans/2026-04-25_feature_production-v2-roadmap.md`). Phase 01 разбит на **2 Sprintа** по правилу 200k-window:
- **1A (этот план)** — measurement infra + 11 critical bugs + категоризация паттернов
- **1B (отдельный план)** — bulk применение паттернов к остальным ~62 ошибкам в ~35 файлах

**Expected result:**
1. CI gate: `ty check src/swarmline/` запускается на каждый PR; PR блокируется при любом увеличении числа diagnostics
2. **0 critical errors** — все 11 потенциальных runtime-bug'ов исправлены с TDD-тестами
3. Установлены 3 канонических паттерна решения для оставшихся ошибок (Optional-Dep / DecoratedTool / CallableUnion)
4. Документ `.memory-bank/notes/2026-04-25_ty-strict-decisions.md` фиксирует решения для Sprint 1B
5. `ty check` после Sprint 1A → **≤ 62 diagnostics** (было 75, минус 11 critical, минус ~2 "побочных" от рефакторов)
6. **Прогрессия baseline:** 75 (Stage 1) → 72 (Stage 2) → 70 (Stage 3) → 66 (Stage 4) → **62 (Stage 5)** — финальный target

**Related files:**
- `.memory-bank/plans/2026-04-25_feature_production-v2-roadmap.md` — родительский roadmap (Phase 01 секция)
- `.memory-bank/reports/2026-04-25_audit_production-readiness-fastapi-parity.md` — аудит, выявивший 4 critical errors
- `pyproject.toml:225-235` — `[tool.ty.*]` конфигурация (уже strict)
- `.pipeline.yaml:18` — `typecheck: "ty check src/swarmline/"` (mypy удалён в текущей сессии)
- `src/swarmline/orchestration/coding_task_runtime.py:163,180,184` — критичные вызовы несуществующих методов
- `src/swarmline/project_instruction_filter.py:90` — tuple type bug
- `src/swarmline/multi_agent/agent_registry_postgres.py:133` — sqlalchemy `Result.rowcount`
- `src/swarmline/agent/tool.py:72`, `multi_agent/graph_tools.py:196-198` — `__tool_definition__` decorator pattern
- `src/swarmline/hooks/dispatcher.py:106,158,194,207` — `__name__` на callable union
- `src/swarmline/protocols/graph_task.py` — Protocol может потребовать дополнения методов

---

## Stages

<!-- mb-stage:1 -->
### Stage 1: ty strict-mode meta-test + CI gate

**Цель:** установить инфраструктуру измерения. Без этого фикс ошибок не защищён от регрессий.

**What to do:**
- Создать `tests/architecture/__init__.py` (пустой) и `tests/architecture/test_ty_strict_mode.py`
- Тест запускает `subprocess.run(["ty", "check", "src/swarmline/"], capture_output=True)` и парсит stdout на `Found N diagnostics`. Маркер `@pytest.mark.slow` (исполнение 30-90с)
- Сначала тест записывает baseline `ty_baseline.txt` (75 diagnostics — фактическое значение на 2026-04-25) и assert'ит **NOT exceeds**, не равенство — позволяет инкрементальный прогресс
- Каждая последующая Stage уменьшает baseline на N (обновляет файл) — финальный target после Sprint 1A: ≤62
- Добавить step в `.github/workflows/ci.yml` (после ruff): `name: ty | run: ty check src/swarmline/ | continue-on-error: false`
- `pyproject.toml [tool.pytest.ini_options]`: убедиться что `markers = ["slow", ...]` зарегистрирован (если нет — добавить)

**Testing (TDD — tests BEFORE implementation):**
- **Unit:** `tests/architecture/test_ty_strict_mode.py::test_ty_returns_below_baseline` — assert `current_diagnostics <= int(baseline_file.read())`. Red изначально (если baseline не записан). Сценарий: baseline=75 → ty=75 → green; ty=76 → fail; ty=62 → green + warning "baseline outdated"
- **Unit:** `test_ty_baseline_file_exists` — assert `tests/architecture/ty_baseline.txt` существует и parseable (just int)
- **Integration:** `test_ci_workflow_has_ty_step` — парсит `.github/workflows/ci.yml` YAML, ищет step с `ty check` командой
- Edge case: `ty` бинарник не установлен → тест skip с сообщением "ty not in PATH; install: pip install ty"

**DoD (Definition of Done):**
- [ ] `tests/architecture/test_ty_strict_mode.py` создан, все 3 теста зелёные локально (`pytest tests/architecture/ -v -m slow`)
- [ ] `tests/architecture/ty_baseline.txt` содержит число `75` (текущий baseline)
- [ ] `.github/workflows/ci.yml` имеет step `Run ty type-check` после ruff, fail-on-error
- [ ] CI run на тестовом PR — green (baseline = current = 75 → assert holds)
- [ ] `pytest -m slow tests/architecture/` < 90 секунд
- [ ] `ruff check tests/architecture/` — 0 violations
- [ ] `ty check src/swarmline/` сам по себе **не должен** запускаться этим тестом дважды в одном CI run — закешировать результат через session-scoped fixture

**Code rules:** TDD red→green, KISS (subprocess + assert; не делать сложный парсер), YAGNI (без классификации ошибок — только число).

---

<!-- mb-stage:2 -->
### Stage 2: Fix GraphTaskBoard missing methods (coding_task_runtime crashes)

**Цель:** убрать 3 потенциальных runtime crash'а в `orchestration/coding_task_runtime.py:163,180,184`. Эти строки вызывают `cancel_task`, `get_ready_tasks`, `get_blocked_by` на `GraphTaskBoard` — методов нет в Protocol.

**What to do:**
- Прочитать `src/swarmline/orchestration/coding_task_runtime.py` около строк 163, 180, 184 — понять контекст вызова
- Прочитать `src/swarmline/protocols/graph_task.py` (`GraphTaskBoard` Protocol)
- Прочитать `src/swarmline/multi_agent/graph_task_board_inmemory.py`, `graph_task_board_sqlite.py`, `graph_task_board_postgres.py` — есть ли эти методы в реализациях?
- **Решение А (если методы реально нужны):** добавить в `GraphTaskBoard` Protocol с сохранением ISP (≤5 методов в Protocol — может потребовать выделить `GraphTaskBoardScheduler` Protocol через композицию, как уже есть `GraphTaskScheduler`/`GraphTaskBlocker`)
- **Решение B (если не нужны / dead code):** удалить вызовы или заменить на существующие методы (`get_blocked_by` ⊃ `GraphTaskBlocker.get_blocked_by` уже есть отдельным Protocol — возможно `coding_task_runtime` должен принимать `GraphTaskBlocker` отдельно)
- Скорее всего **Решение B** — ISP уже разделил эти методы по разным Protocol; `coding_task_runtime` должен депендить от `GraphTaskBoard + GraphTaskScheduler + GraphTaskBlocker` явно
- Обновить `tests/architecture/ty_baseline.txt` → `72` (75 - 3)

**Testing (TDD):**
- **Unit (red FIRST):** `tests/unit/test_coding_task_runtime_protocol_deps.py::test_runtime_uses_correct_protocols` — assert через inspect, что `CodingTaskRuntime.__init__` принимает `GraphTaskBoard | GraphTaskScheduler | GraphTaskBlocker` (через Union или 3 отдельных параметра)
- **Integration (red FIRST):** `tests/integration/test_coding_task_runtime_cancel_flow.py::test_cancel_task_path_does_not_crash` — создать runtime, запустить task, вызвать cancel — не должно быть `AttributeError`
- **Integration:** `test_get_ready_tasks_returns_list_when_blocker_provided`, `test_get_blocked_by_returns_dict`
- Edge case: что если `GraphTaskBlocker` не передан (None) → `cancel_task` должен либо raise `ConfigError("blocker required for cancel")` либо silently ignore с warning
- Edge case: deadlock detection — `get_ready_tasks` возвращает `[]` при кольцевой зависимости

**DoD:**
- [ ] `ty check src/swarmline/orchestration/coding_task_runtime.py` → **0 attr-defined errors** на строках 163, 180, 184
- [ ] 3 новых теста (1 unit + 2 integration) — все green
- [ ] `tests/architecture/ty_baseline.txt` → `72`, тест из Stage 1 проходит
- [ ] `pytest tests/unit/test_coding_task_runtime*.py tests/integration/test_coding_task_runtime*.py -v` — все green
- [ ] `pytest tests/integration/` (ALL) — все green (нет регрессий в зависимых тестах)
- [ ] Если выбрано Решение A — `GraphTaskBoard` Protocol всё ещё ≤5 методов
- [ ] Backwards compat: старые usages `CodingTaskRuntime(task_board=...)` продолжают работать (если изменился конструктор — добавлен deprecation path с `__post_init__` или factory)
- [ ] `ruff check` + `ruff format --check` — clean

**Code rules:** ISP (Protocol ≤5 методов), Contract-first (Protocol → tests → implementation), Backwards compat (deprecation, не break).

---

<!-- mb-stage:3 -->
### Stage 3: Fix isolated type bugs (project_instruction_filter + agent_registry_postgres)

**Цель:** исправить 2 локализованных bug'а — оба one-line fixes но с TDD-защитой.

**What to do:**

**3.1 — `src/swarmline/project_instruction_filter.py:90`** — `tuple[int, list[str]]` vs ожидаемое `tuple[int, str]` в `list.append()`:
- Прочитать функцию вокруг 90 строки — понять, что элемент должен быть строкой
- Скорее всего bug: где-то появляется `list[str]` вместо `str` (возможно `_lines` вместо `_lines[0]` или `"\n".join(_lines)`)
- Исправить с правильным narrow'ом или join'ом

**3.2 — `src/swarmline/multi_agent/agent_registry_postgres.py:133`** — `Result[Any].rowcount` не существует:
- В sqlalchemy 2.x `result.rowcount` существует на `CursorResult`, но не на абстрактном `Result`. Скорее всего нужен `result = await session.execute(...)` → `cast(CursorResult, result).rowcount` или прямой `await session.execute(...).scalar()` где applicable
- Если используется для DELETE — паттерн `result = await session.execute(delete(...)); affected = result.rowcount` требует `from sqlalchemy.engine import CursorResult`
- Альтернатива: использовать `session.execute().rowcount` через `# type: ignore[union-attr]` с reason — но это техдолг

**Update baseline:** `tests/architecture/ty_baseline.txt` → `70` (72 - 2)

**Testing (TDD):**
- **Unit (red FIRST):** `tests/unit/test_project_instruction_filter_append_type.py::test_append_with_string_only` — feed input that triggers the bug path, assert no `TypeError` and content matches expected `tuple[int, str]`
- **Unit:** `test_filter_handles_multiline_input` — multiline string, проверить что элементы list — все strings, не nested lists
- **Integration:** `tests/integration/test_agent_registry_postgres_delete_returns_affected.py::test_delete_returns_correct_rowcount` — Postgres in-memory (или testcontainers если в CI), insert 3 agents, delete by filter → assert `affected_count == 2`
- Edge case (3.1): пустая строка → `(0, "")`, не `(0, [])`
- Edge case (3.2): delete без matches → `rowcount == 0`

**DoD:**
- [ ] `ty check src/swarmline/project_instruction_filter.py` → 0 errors на line 90
- [ ] `ty check src/swarmline/multi_agent/agent_registry_postgres.py` → 0 errors на line 133
- [ ] 4 новых теста (3 unit + 1 integration) — все green
- [ ] `tests/architecture/ty_baseline.txt` → `70`
- [ ] `pytest tests/unit/test_project_instruction_filter*.py tests/integration/test_agent_registry_postgres*.py -v` — green
- [ ] Если для 3.2 потребовался Postgres — `@pytest.mark.requires_postgres`, fixture `pg_engine` (testcontainers или skip если PG_DSN env не задан)
- [ ] Нет новых `# type: ignore` — настоящие фиксы, не silencing
- [ ] `ruff check` clean

**Code rules:** TDD red→green, KISS (one-line fixes, не overengineer), Fail-fast (Postgres test should fail loud если DSN не задан в integration mode).

---

<!-- mb-stage:4 -->
### Stage 4: Introduce ToolFunction Protocol for __tool_definition__ pattern

**Цель:** убрать 4 ошибки `unresolved-attribute: __tool_definition__` (`agent/tool.py:72`, `multi_agent/graph_tools.py:196-198`). Это паттерн декоратора, ty не может вывести добавленный атрибут — нужен явный Protocol.

**What to do:**
- Создать `src/swarmline/agent/tool_protocol.py` (или добавить в существующий `tool.py`):
  ```python
  from typing import Any, Protocol, runtime_checkable

  @runtime_checkable
  class ToolFunction(Protocol):
      """Callable enriched by @tool decorator with __tool_definition__."""
      __tool_definition__: ToolSpec
      __name__: str
      def __call__(self, *args: Any, **kwargs: Any) -> Any: ...
  ```
- В `src/swarmline/agent/tool.py:72` — после декорирования вернуть `cast(ToolFunction, handler)` вместо raw function
- В `src/swarmline/multi_agent/graph_tools.py:196-198` — заменить `hire_agent.__tool_definition__  # type: ignore[attr-defined]` на `cast(ToolFunction, hire_agent).__tool_definition__` (без ignore)
- Удалить `# type: ignore[attr-defined]` комментарии в graph_tools.py
- Экспортировать `ToolFunction` из `swarmline.agent` (для use внешними кастомными tools-providers)

**Update baseline:** `tests/architecture/ty_baseline.txt` → `66` (70 - 4)

**Testing (TDD):**
- **Unit (red FIRST):** `tests/unit/test_tool_function_protocol.py::test_decorated_tool_satisfies_protocol`:
  ```python
  @tool("greet", description="Greet someone")
  async def greet(name: str) -> str: return f"hi {name}"
  
  assert isinstance(greet, ToolFunction)  # runtime_checkable
  assert greet.__tool_definition__.name == "greet"
  ```
- **Unit:** `test_undecorated_function_not_satisfies_protocol` — без `@tool` — `isinstance(plain_func, ToolFunction) is False`
- **Unit:** `test_tool_definition_attribute_typed_correctly` — статическая проверка через `assert_type` (mypy_extensions если установлен) — но в ty это уже даст 0 ошибок если правильно
- Edge case: tool с **mismatched signature** (e.g. без async) — должен fail на decorator level, не на Protocol level

**DoD:**
- [ ] `ty check src/swarmline/agent/tool.py` → 0 errors на line 72
- [ ] `ty check src/swarmline/multi_agent/graph_tools.py` → 0 errors на lines 196-198
- [ ] `grep -n "type: ignore" src/swarmline/multi_agent/graph_tools.py` → 0 occurrences (раньше было 3)
- [ ] 3 новых unit-теста — все green
- [ ] `tests/architecture/ty_baseline.txt` → `66`
- [ ] `ToolFunction` экспортирован из `swarmline.agent` (`__all__` обновлён)
- [ ] Backwards compat: существующие examples (`examples/02_tool_decorator.py`, etc.) — green без изменений
- [ ] `pytest tests/unit/test_tool*.py tests/integration/test_*tool*.py -v` — green
- [ ] Документация в docstring `ToolFunction` объясняет когда и почему использовать `cast(ToolFunction, ...)`
- [ ] `ruff check` clean

**Code rules:** Protocol-first (явный контракт вместо magic-attribute), DIP (зависим от ToolFunction Protocol, не от concrete decorated function), `runtime_checkable` для тестируемости.

---

<!-- mb-stage:5 -->
### Stage 5: Fix hooks/dispatcher __name__ on callable union (4 errors)

**Цель:** убрать 4 ошибки `unresolved-attribute: __name__` в `hooks/dispatcher.py:106,158,194,207`. Все 4 — одинаковый паттерн логирования имени hook'а в warning.

**What to do:**
- Прочитать `src/swarmline/hooks/dispatcher.py` около строк 106, 158, 194, 207
- Все 4 имеют один паттерн:
  ```python
  logger.warning("... %r raised an exception ...", hook.__name__)
  ```
  где `hook` имеет тип `Unknown | (...) -> Awaitable[Any]` (callable union, частично от `functools.partial` который не имеет `__name__`)
- Решение — defensive helper:
  ```python
  def _hook_name(hook: object) -> str:
      """Best-effort name for any callable; safe for partial/lambdas."""
      return getattr(hook, "__name__", repr(hook))
  ```
- Поместить helper в `src/swarmline/hooks/_helpers.py` (новый файл) или в `dispatcher.py` private
- Заменить все 4 вхождения `hook.__name__` → `_hook_name(hook)`

**Update baseline:** `tests/architecture/ty_baseline.txt` → `62` (66 - 4)

**Testing (TDD):**
- **Unit (red FIRST):** `tests/unit/test_hook_name_helper.py`:
  - `test_named_function_returns_qualname` — `def foo(): ...; assert _hook_name(foo) == "foo"`
  - `test_partial_falls_back_to_repr` — `from functools import partial; p = partial(foo, x=1); assert _hook_name(p).startswith("functools.partial(")`
  - `test_lambda_returns_lambda` — `f = lambda x: x; assert _hook_name(f) == "<lambda>"`
  - `test_class_with_call_uses_class_name_or_repr` — `class C:\n  def __call__(self): pass\nassert _hook_name(C()) is not None and isinstance(_hook_name(C()), str)`
- **Integration:** `tests/integration/test_hooks_dispatcher_with_partial.py::test_pretool_hook_partial_logs_correctly` — register partial as PreToolUse hook, trigger exception, assert `caplog.records` has WARNING with non-empty hook name (не падает с AttributeError)
- Edge case: hook is None → не должен достигать `_hook_name` (фильтруется выше) — но defensive: `_hook_name(None) == "None"` instead of crash

**DoD:**
- [ ] `ty check src/swarmline/hooks/dispatcher.py` → 0 errors на lines 106, 158, 194, 207
- [ ] `tests/architecture/ty_baseline.txt` → `62`
- [ ] 5 новых тестов (4 unit + 1 integration) — все green
- [ ] `pytest tests/unit/test_hook_name*.py tests/integration/test_hooks*.py -v` — green
- [ ] `pytest tests/integration/` (ALL hooks tests) — green (не сломали PreToolUse/PostToolUse/Stop/UserPromptSubmit)
- [ ] `_hook_name` helper documented (1-line docstring + example)
- [ ] DRY: 4 одинаковых вхождения заменены на вызов helper'а — не копипаст
- [ ] `ruff check` clean

**Code rules:** DRY (helper вместо 4×inline), Fail-safe (никогда не падать в логирующем коде — `getattr` с default), KISS (1 helper-функция, не класс).

---

<!-- mb-stage:6 -->
### Stage 6: Decisions doc + Sprint 1B handoff + ADR

**Цель:** зафиксировать паттерны решения для оставшихся ~62 ошибок в .memory-bank/notes/, чтобы Sprint 1B мог быть выполнен механически (или другим разработчиком).

**What to do:**
- Создать `.memory-bank/notes/2026-04-25_ty-strict-decisions.md` (5-15 строк по правилу notes/, см. `~/.claude/skills/memory-bank/references/templates.md`):
  - Pattern OptDep — для `unresolved-import` от опциональных deps (tavily, crawl4ai, ddgs, openshell, docker): `try/except ImportError + TYPE_CHECKING + # type: ignore[unresolved-import]  # optional dep`
  - Pattern DecoratedTool — для `__tool_definition__` и аналогов: `cast(ToolFunction, ...)` (см. Stage 4)
  - Pattern CallableUnion — для `__name__`/attribute access на `partial | callable`: `_hook_name(...)` helper (см. Stage 5)
- Создать `/mb adr "Use ty in strict mode as sole type checker; no mypy"` через `bash ~/.claude/skills/memory-bank/scripts/mb-adr.sh`
- ADR заполнить:
  - Context: 2 type checkers (mypy + ty) → дрейф между ними; mypy lenient, ty strict
  - Options: a) mypy only, b) ty only strict, c) both with sync
  - Decision: ty strict only
  - Rationale: ty быстрее, обнаруживает больше bugs (70 vs 4), официальный astral.sh tool, repository уже на ty
  - Consequences: 70 errors → план поэтапного фикса (Sprint 1A + 1B), CI gate, нет mypy в pyproject/pipeline
- Создать `.memory-bank/plans/2026-04-25_feature_production-v2-phase-01b-ty-bulk-cleanup.md` через `mb-plan.sh feature production-v2-phase-01b-ty-bulk-cleanup` (только scaffold + Context секция; полное наполнение — отдельной сессией)
- В Sprint 1B Context: ссылка на этот план (1A) + decisions doc + текущий baseline (62)

**Testing (TDD):**
- N/A — это документация и handoff. Smoke test:
- **Unit:** `tests/architecture/test_memory_bank_artifacts.py::test_ty_decisions_note_exists_and_lists_3_patterns` — assert `notes/2026-04-25_ty-strict-decisions.md` существует, парсится, имеет минимум 3 H2/H3 секции с именами pattern'ов
- **Unit:** `test_sprint_1b_plan_exists` — assert `plans/2026-04-25_feature_production-v2-phase-01b-ty-bulk-cleanup.md` существует и имеет non-empty Context
- **Unit:** `test_adr_for_ty_choice_recorded` — grep `BACKLOG.md` на `ADR-NNN — Use ty in strict mode`

**DoD:**
- [ ] `.memory-bank/notes/2026-04-25_ty-strict-decisions.md` создан, ≤15 строк, описывает 3 паттерна (OptDep / DecoratedTool / CallableUnion) с примерами кода
- [ ] ADR-NNN зафиксирован в `BACKLOG.md ## ADR` с полностью заполненным skeleton (Context/Options/Decision/Rationale/Consequences)
- [ ] `.memory-bank/plans/2026-04-25_feature_production-v2-phase-01b-ty-bulk-cleanup.md` scaffold с заполненным Context (ссылки на Sprint 1A + decisions note + baseline 62)
- [ ] 3 новых архитектурных теста — все green
- [ ] `bash ~/.claude/skills/memory-bank/scripts/mb-plan-sync.sh .memory-bank/plans/2026-04-25_feature_production-v2-phase-01a-ty-strict-foundation.md` — выполнен, `checklist.md` содержит DoD из всех 6 stages
- [ ] `bash ~/.claude/skills/memory-bank/scripts/mb-index.sh` — реестр актуален, видит новый ADR + note + plan
- [ ] `progress.md` имеет append с датой 2026-04-25 для Sprint 1A completion
- [ ] STATUS.md `<!-- mb-active-plans -->` обновлён через mb-plan-sync (показывает Sprint 1B как active)

**Code rules:** Append-only progress, ≤15 строк notes (knowledge не chronology), ADR обязателен для значимого технического решения.

---

## Risks and mitigation

| Risk | Probability | Mitigation |
|------|-------------|------------|
| Stage 2 — добавление методов в `GraphTaskBoard` Protocol нарушит ISP (>5 методов) | M | Использовать композицию — `GraphTaskScheduler`/`GraphTaskBlocker` уже выделены; depend on them в `coding_task_runtime` отдельно. Проверка через `tests/architecture/test_isp_protocol_method_count.py` если ещё не существует |
| Stage 3.2 — Postgres test требует CI infra | L | `@pytest.mark.requires_postgres`, skip если PG_DSN env не задан; в локальном dev — testcontainers fixture (опционально, не блокирует) |
| Stage 4 — `cast(ToolFunction, ...)` пропускает реальные ошибки если decorator не применён | L | `runtime_checkable` Protocol + `isinstance` assertion в hot-path debug режиме; unit-тест проверяет, что undecorated function NOT satisfies |
| Stage 5 — `getattr(hook, "__name__", repr(hook))` может вернуть длинный repr на сложных partial — log spam | L | Limit длину: `name[:80]` если len>80; покрыть тестом `test_hook_name_truncated_for_long_repr` |
| Baseline `ty_baseline.txt` забыли обновить после фикса → false-positive failure | M | Автоматизировать в Stage 1 helper script `scripts/update_ty_baseline.sh` (не входит в DoD, но опционально); человеко-readme в `tests/architecture/README.md` |
| Sprint 1A фиксы откроют новые ошибки в зависимом коде (cascading) | L | Каждая Stage прогоняет полный `pytest tests/integration/` — регрессии видны сразу; `ty check` на каждом этапе обновляет baseline только если число действительно уменьшилось |
| ADR-NNN номер коллидирует если параллельно в другой сессии создаётся ещё один ADR | L | `mb-adr.sh` атомарно резервирует номер; после создания — re-run `mb-index.sh` для верификации |
| `tests/architecture/test_ty_strict_mode.py` slow → CI time увеличится на 30-90с | M | `@pytest.mark.slow` + cache: запускать только на main + PR в release branch, не на каждый push в feature branches |

---

## Gate (plan success criterion)

**Sprint 1A считается завершённым тогда и только тогда, когда выполнены ВСЕ следующие условия (verifiable by single command):**

```bash
# 1. ty diagnostics уменьшены до ≤62 (было 75)
test "$(ty check src/swarmline/ 2>&1 | grep -oE 'Found [0-9]+' | grep -oE '[0-9]+')" -le 62

# 2. Все 11 critical errors исправлены (нулевое количество в перечисленных файлах)
test "$(ty check src/swarmline/ 2>&1 | grep -c -E 'orchestration/coding_task_runtime\.py.*(163|180|184)|project_instruction_filter\.py:90|agent_registry_postgres\.py:133|agent/tool\.py:72|multi_agent/graph_tools\.py.*(196|197|198)|hooks/dispatcher\.py.*(106|158|194|207)')" -eq 0

# 3. Все новые тесты Sprint 1A зелёные
pytest tests/architecture/ tests/unit/test_coding_task_runtime_protocol_deps.py tests/unit/test_project_instruction_filter_append_type.py tests/unit/test_tool_function_protocol.py tests/unit/test_hook_name_helper.py tests/unit/test_memory_bank_artifacts.py tests/integration/test_coding_task_runtime_cancel_flow.py tests/integration/test_agent_registry_postgres_delete_returns_affected.py tests/integration/test_hooks_dispatcher_with_partial.py -v

# 4. Регрессий нет — все существующие тесты зелёные
pytest -m "not live and not slow" -q

# 5. Lint чист
ruff check src/ tests/ && ruff format --check src/ tests/

# 6. Memory Bank артефакты на месте
test -f .memory-bank/notes/2026-04-25_ty-strict-decisions.md
test -f .memory-bank/plans/2026-04-25_feature_production-v2-phase-01b-ty-bulk-cleanup.md
grep -q "ADR-[0-9]\+ — Use ty in strict mode" .memory-bank/BACKLOG.md
test "$(cat tests/architecture/ty_baseline.txt)" = "62"

# 7. CI gate активен — yaml содержит step "ty check"
grep -q "ty check src/swarmline/" .github/workflows/ci.yml
```

**Если все 7 условий → green → `/mb verify` → `/mb done` → Sprint 1B starts (отдельная сессия с pre-loaded contextом из decisions note + Sprint 1A note).**

**Если хоть одно red → план остаётся in-progress, текущая stage помечается blocked, и blocker конкретизируется в `BACKLOG.md` как новая `I-NNN`.**

---

**Estimate:** 1.5 рабочих дня (12 ч)
- Stage 1: 1.5 ч
- Stage 2: 3 ч (самая большая — ISP refactor)
- Stage 3: 2 ч (2 локализованных bug'а с TDD)
- Stage 4: 2 ч (Protocol + 4 cast)
- Stage 5: 1.5 ч (helper + 5 тестов)
- Stage 6: 2 ч (docs + ADR + scaffold 1B + sync)
