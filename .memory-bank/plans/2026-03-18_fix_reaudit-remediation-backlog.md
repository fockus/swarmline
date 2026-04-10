# Plan: Re-audit Remediation Backlog

Дата: 2026-03-18
Тип: fix
Тема: close re-review findings + broader runtime/session/public-surface audit gaps

## Контекст

После remediation Wave 1/2 и повторного re-review осталось два слоя проблем:

1. **Подтверждённые code-level gaps**, которые уже влияют на correctness:
   - `SessionManager.stream_reply()` теряет canonical `final.new_messages`;
   - builtin `cli` валиден в registry, но не создаётся через legacy fallback;
   - `BaseRuntimePort` и `SessionManager` всё ещё синтезируют `done` на silent EOF;
   - `ClaudeCodeRuntime` может эмитить `error`, а затем ещё и `final`;
   - DeepAgents portable path теряет tool history;
   - workflow executors частично интегрированы (`ThinWorkflowExecutor` tools, `MixedRuntimeExecutor` fake routing);
   - `convert_event()` теряет `tool_name` для `tool_call_finished`.

2. **Broader gaps**, которые снижают доверие к библиотеке, но не все являются blocker:
   - runtime/docs drift (`cli` уже есть в коде, но базовые docs всё ещё говорят про 3 runtime);
   - docs обещают старую optional-export семантику (`None` вместо fail-fast ImportError);
   - skills migration narrative и tests противоречат текущему split core registry vs infra loader;
   - repo-wide `ruff` и `mypy` всё ещё не являются рабочими gates.

Важно:
- `PyYAML` объявлен как core dependency, поэтому issues вокруг `skills.__all__` и cold import without yaml трактуем как consistency/test-signal debt, а не как blocker unsupported install.
- План ориентирован на **быструю реализацию через независимые низкорисковые батчи**, чтобы распараллелить работу по сабагентам и не смешивать correctness fixes со статическим cleanup в одном большом diff.

## Принципы исполнения

- Contract-first: сначала terminal/history/tool-surface contract tests, затем реализация.
- TDD: каждый correctness batch начинается с failing regression tests.
- Low-risk slices: один seam, один root cause, одна проверка.
- Clean Architecture: infrastructure fixes не тащат новый behavioural logic в application/domain без тестов.
- Verification before Memory Bank actualization: checklist/status менять только после реального green.
- Shared ownership boundaries: write sets сабагентов не пересекаются.

## Wave 1 — Must-fix now (correctness)

### Batch 1A — Terminal contract parity in compatibility paths

**Цель**
- закрыть silent-success и double-terminal behaviour в compatibility слоях.

**Scope**
- `src/cognitia/runtime/ports/base.py`
- `src/cognitia/session/manager.py`
- `src/cognitia/runtime/claude_code.py`
- tests:
  - `tests/unit/test_runtime_ports_base_coverage.py`
  - `tests/unit/test_session_manager.py`
  - `tests/unit/test_claude_code_runtime.py`
  - при необходимости один integration test в session/runtime path

**Шаги**
1. Добавить failing tests:
   - `BaseRuntimePort.stream_reply()` должен выдавать `error`, а не `done`, если runtime stream завершился без `final/error`.
   - `SessionManager.stream_reply()` в runtime path должен вести себя так же.
   - `ClaudeCodeRuntime.run()` не должен выдавать `final` после `StreamEvent(type="error")`.
2. В `BaseRuntimePort` завести terminal flag и fail-fast на silent EOF.
3. В `SessionManager.stream_reply()` завести такую же terminal guard семантику.
4. В `ClaudeCodeRuntime.run()` различать `error` vs successful completion и не синтезировать `final` после error path.

**DoD**
- compatibility paths больше не принимают incomplete run как success;
- один turn даёт не более одного terminal semantic outcome;
- targeted tests зелёные;
- полный offline `pytest -q` после merge batch не деградирует.

**Ownership**
- Worker 1:
  - `runtime/ports/base.py`
  - `tests/unit/test_runtime_ports_base_coverage.py`
- Worker 2:
  - `session/manager.py`
  - `tests/unit/test_session_manager.py`
- Worker 3:
  - `runtime/claude_code.py`
  - `tests/unit/test_claude_code_runtime.py`

### Batch 1B — Canonical history integrity

**Цель**
- довести canonical history contract до portable runtimes и session path.

**Scope**
- `src/cognitia/session/manager.py`
- `src/cognitia/runtime/deepagents_langchain.py`
- `src/cognitia/runtime/deepagents.py`
- tests:
  - `tests/unit/test_session_manager.py`
  - `tests/integration/test_runtime_portable_matrix.py`
  - DeepAgents-specific unit/integration tests

**Шаги**
1. Добавить failing tests:
   - `SessionManager.stream_reply()` должен сохранять `final.new_messages`, а не только synthetic assistant text.
   - DeepAgents portable multi-turn path должен сохранять tool history между turn’ами.
2. В session runtime path использовать `final.new_messages` как authoritative delta истории.
3. В DeepAgents portable path:
   - либо корректно переносить tool records в `new_messages`,
   - либо честно документировать и тестово закрепить reduced contract, если tool history там принципиально недоступна.
4. Проверить, что `Conversation`/`SessionManager` после tool-heavy turn’а видят одинаковую историю.

**DoD**
- после tool-use multi-turn tool context не теряется ни в facade path, ни в session path;
- DeepAgents portable runtime не отдаёт урезанную history delta без тестового обоснования;
- regression tests зелёные на portable matrix.

**Ownership**
- Worker 1:
  - `session/manager.py`
  - session tests
- Worker 2:
  - `runtime/deepagents_langchain.py`
  - `runtime/deepagents.py`
  - DeepAgents runtime tests

### Batch 1C — Registry/factory correctness

**Цель**
- выровнять builtin `cli` с fallback semantics.

**Scope**
- `src/cognitia/runtime/factory.py`
- `src/cognitia/runtime/registry.py`
- `tests/unit/test_runtime_factory.py`
- `tests/integration/test_runtime_registry_integration.py`

**Шаги**
1. Добавить failing regression test: если `_effective_registry is None`, `RuntimeFactory.create(RuntimeConfig(runtime_name="cli"))` всё ещё создаёт builtin runtime, а не падает.
2. Добавить legacy `cli` fallback branch в `RuntimeFactory.create()`.
3. При необходимости вынести общий `_create_cli()` path, чтобы registry и fallback использовали одну и ту же семантику.

**DoD**
- `cli` valid runtime name всегда constructable, независимо от доступности registry;
- поведение builtin runtime creation одинаково для registry path и fallback path;
- targeted tests зелёные.

**Ownership**
- Worker 3:
  - `runtime/factory.py`
  - `runtime/registry.py`
  - factory/registry tests

### Batch 1D — Workflow executor integration correctness

**Цель**
- довести workflow runtime layer до честно интегрированного состояния.

**Scope**
- `src/cognitia/orchestration/workflow_executor.py`
- tests:
  - `tests/unit/test_workflow_executor.py`
  - `tests/integration/test_workflow_runtime.py`
  - `tests/e2e/test_workflow_e2e.py`

**Шаги**
1. Добавить failing tests:
   - `ThinWorkflowExecutor` advertises tools, если `local_tools` переданы.
   - `MixedRuntimeExecutor` либо реально route’ит execution по runtime map, либо переименовывается/документируется как observability-only wrapper.
2. Исправить `ThinWorkflowExecutor.run_node()` так, чтобы `active_tools` строились из local tools.
3. Принять решение по `MixedRuntimeExecutor`:
   - либо реализовать фактический runtime-based dispatch;
   - либо убрать misleading semantics из имени/docs/tests.

**DoD**
- workflow runtime helpers не притворяются полноценным runtime routing без фактического routing;
- tools реально доступны LLM в thin workflow path;
- tests проверяют behaviour, а не только metadata.

**Ownership**
- Worker 4:
  - `orchestration/workflow_executor.py`
  - workflow tests

## Wave 2 — Next batch (public surface + docs/tests signal)

### Batch 2A — Optional-export narrative and import-signal cleanup

**Цель**
- выровнять docs/tests/public surface вокруг lazy fail-fast exports.

**Scope**
- `src/cognitia/runtime/__init__.py`
- `src/cognitia/hooks/__init__.py`
- `src/cognitia/skills/__init__.py`
- `tests/unit/test_import_isolation.py`
- docs:
  - `docs/advanced.md`
  - `docs/tools-and-skills.md`
  - `docs/architecture.md`

**Шаги**
1. Уточнить ожидаемую семантику:
   - fail-fast `ImportError` вместо `None`;
   - skills loader narrative как infra-layer helper, а не чистый core primitive.
2. Исправить order-dependent import-isolation test вокруг `YamlSkillLoader`.
3. Обновить docs, где всё ещё обещается `None` или старый core-surface story.

**DoD**
- docs описывают реальную import semantics;
- import-isolation tests не зависят от warmed modules;
- нет противоречия между docstring package module и docs site.

**Ownership**
- Worker 5:
  - optional-export docs/tests

### Batch 2B — Runtime/docs surface sync

**Цель**
- синхронизировать entry docs с фактическим public runtime API.

**Scope**
- `README.md`
- `docs/api-reference.md`
- `docs/runtimes.md`
- `docs/why-cognitia.md`
- возможно `mkdocs.yml` если нужен nav sync

**Шаги**
1. Везде, где перечисляются runtime names, добавить `cli` и актуализировать count.
2. Уточнить install/runtime matrix и public examples.
3. Проверить, что docs не конфликтуют с `docs/cli-runtime.md`.

**DoD**
- базовые docs, API reference и dedicated CLI docs говорят одно и то же;
- пользователь видит корректный список допустимых runtime values;
- docs snippets не противоречат текущему package surface.

**Ownership**
- Worker 6:
  - docs-only batch

## Wave 3 — Tracked debt, отдельной волной

### Batch 3A — Compatibility-layer cleanup

**Цель**
- продолжить migration cleanup вокруг dual-path session/runtime state.

**Scope**
- `src/cognitia/session/types.py`
- `src/cognitia/session/manager.py`
- `src/cognitia/agent/agent.py`
- related tests

**Шаги**
1. Определить целевую ownership модель для `adapter`, `runtime`, `runtime_messages`.
2. Сузить роль compatibility shims.
3. Решить судьбу mostly ceremonial `Agent.cleanup()`.

**DoD**
- session/runtime ownership становится проще и менее двусмысленным;
- lifecycle APIs либо реальны, либо упрощены и честно документированы.

### Batch 3B — Repo-wide `ruff` cleanup

**Цель**
- вернуть `ruff` в состояние честного repo-wide gate.

**Scope**
- repo-wide, но отдельными безопасными подбатчами:
  - source first
  - tests second

**Шаги**
1. Сначала убрать source-side `E402`/`F401` в runtime modules.
2. Затем вычистить test-only `unused-import`/`unused-variable` шум.
3. Закрепить `ruff check src/ tests/` как обязательный gate.

**DoD**
- `ruff check src/ tests/` зелёный;
- signal по source больше не тонет в test noise.

### Batch 3C — Repo-wide `mypy` cleanup

**Цель**
- вернуть `mypy` в usable regression gate хотя бы по agreed scope.

**Scope**
- hot paths first:
  - `memory/sqlite.py`
  - `runtime/structured_output.py`
  - `runtime/options_builder.py`
  - `runtime/thin/llm_providers.py`
- затем missing-stubs strategy

**Шаги**
1. Разделить real type defects и optional-dependency stub noise.
2. Исправить hot-path typing errors.
3. Определить реалистичный gate command:
   - либо narrowed strict subset;
   - либо repo-wide command с exclusions по unsupported third-party stubs.

**DoD**
- выбранный `mypy` gate стабильно зелёный и полезен;
- real typed seams в hot paths больше не скрыты за global red state.

## Порядок запуска и merge points

### Можно делать параллельно сразу

1. Batch 1A
2. Batch 1C
3. Batch 1D

### После Batch 1A

- запускать Batch 1B, потому что `SessionManager` уже затрагивается и terminal semantics не должны конфликтовать с history fix.

### После Wave 1

- один общий merge point:
  - `python -m pytest -q`
  - targeted `ruff check` по touched files
  - targeted `mypy --follow-imports=silent` по touched source files

### После Wave 1 green

- можно параллелить Batch 2A и 2B, потому что это docs/tests/public-surface sync без пересечения write sets.

### Wave 3

- только после correctness and public-surface sync, отдельными cleanup PR/batches.

## Acceptance Criteria

План считается готовым к исполнению, если:

1. Все confirmed findings из re-review и broader audit отражены в backlog.
2. Каждая correctness проблема имеет свой batch с ownership, тестами и DoD.
3. Параллельные батчи не конфликтуют по write set.
4. Отдельно отделены:
   - must-fix correctness
   - docs/tests signal cleanup
   - tracked static/architecture debt
5. Для каждого merge point определена проверка.
6. Нет смешения unsupported-env нюансов с настоящими product/runtime bug’ами.

## Финальный Gate для всей программы работ

Программа remediation считается завершённой, когда выполнены все условия:

- все must-fix Wave 1 batches закрыты и подтверждены regression tests;
- docs/tests/public-surface sync из Wave 2 завершён;
- 4 re-review findings либо исправлены, либо явно переоценены/закрыты с подтверждением;
- `python -m pytest -q` зелёный;
- agreed `ruff` gate зелёный;
- agreed `mypy` gate зелёный;
- Memory Bank обновлён только после фактической верификации каждого завершённого batch.
