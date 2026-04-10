# Re-audit — broader follow-up after re-review

Дата: 2026-03-18

## Scope

Повторный read-only аудит после remediation Wave 1/2 и строгого re-review.  
Задача этого прохода: не только проверить уже найденные 4 review findings, но и собрать adjacent gaps, pre-existing debt, docs/tests drift и repo-wide quality-gate состояние.

Аудит выполнен с:

- локальными воспроизведениями и code reading;
- сабагентами `Carson`, `Poincare`, `Heisenberg`;
- repo-wide snapshot:
  - `python -m pytest -q`
  - `ruff check src/ tests/ --statistics`
  - `mypy src/cognitia/`

## Verification Snapshot

- `python -m pytest -q` → `2357 passed, 16 skipped, 5 deselected, 19 warnings`
- `ruff check src/ tests/ --statistics` → `60` ошибок
  - `27` `E402`
  - `26` `F401`
  - `6` `F841`
  - `1` `F541`
- `mypy src/cognitia/` → `27 errors in 17 files`

## Status of the 4 re-review findings

### Confirmed and still open

1. `SessionManager.stream_reply()` теряет canonical `final.new_messages` и сохраняет только synthetic assistant text:
   - `src/cognitia/session/manager.py:317-343`
2. builtin `cli` добавлен в valid runtime names/registry, но legacy fallback в `RuntimeFactory.create()` остаётся несовместимым:
   - `src/cognitia/runtime/registry.py:141-145`
   - `src/cognitia/runtime/factory.py:181-192`
3. `cognitia.runtime` public surface регрессировал для optional SDK exports:
   - `src/cognitia/runtime/__init__.py:59-102`
   - `src/cognitia/runtime/__init__.py:153-173`

### Downgraded after broader audit

4. finding про `cognitia.skills.__all__` нужно трактовать осторожнее:
   - `src/cognitia/skills/__init__.py:15-21`
   - `pyproject.toml:40-43`

`PyYAML` объявлен как core dependency, поэтому сценарий “unsupported install without yaml” не является честным blocker для релизного public API. Тем не менее, это остаётся consistency gap для package narrative и import-isolation tests, а не top-priority runtime bug.

## New confirmed code-level gaps

### 1. Legacy port/session wrappers still synthesize success on silent EOF

Даже после fix’ов terminal contract остаётся незавершённым в compatibility paths:

- `src/cognitia/runtime/ports/base.py:275-308`
- `src/cognitia/session/manager.py:317-343`

В обоих местах, если runtime stream закончился без terminal `final/error`, код всё равно доходит до synthetic `done`. Это означает, что truncated/incomplete run продолжает считаться success в legacy `RuntimePort` path и в `SessionManager.stream_reply()` runtime path.

Это adjacent gap к уже найденной проблеме с `collect_runtime_output()`: contract уже исправлен в orchestration helper, но не доведён до port/session wrappers.

### 2. `ClaudeCodeRuntime` может выдать `error`, а затем ещё и `final` для одного turn

- `src/cognitia/runtime/claude_code.py:125-177`
- `src/cognitia/runtime/claude_code.py:223-229`

`_convert_event()` преобразует `StreamEvent(type="error")` в `RuntimeEvent.error(...)`, который пробрасывается наружу в основном loop, но этот loop не завершает turn и после окончания adapter stream всё равно синтезирует `RuntimeEvent.final(...)`.

Следствие: один failed turn может породить два terminal-like сигнала с конфликтующей семантикой.

### 3. DeepAgents portable multi-turn path по конструкции теряет tool history

- `src/cognitia/runtime/deepagents_langchain.py:41-48`
- `src/cognitia/runtime/deepagents.py:221-227`

LangChain compatibility path конвертирует в LC history только `user` / `assistant` / `system`, игнорируя `tool` messages. Затем `DeepAgentsRuntime` в `final.new_messages` возвращает только один assistant message.

Следствие: в portable multi-turn после tool-heavy turn’а canonical history неполная ещё до фасадного слоя. Даже если `Conversation`/`Agent` уже научились уважать `final.new_messages`, DeepAgents portable path сам приносит урезанную историю.

### 4. Workflow executors partially integrated

#### `ThinWorkflowExecutor` не advertises tools

- `src/cognitia/orchestration/workflow_executor.py:43-54`

`ThinWorkflowExecutor` создаёт `ThinRuntime` с `local_tools`, но вызывает `runtime.run(..., active_tools=[])`. Это повторяет уже встречавшийся defect pattern из `ThinRuntimePort`: executors есть, LLM-visible tool list нет.

#### `MixedRuntimeExecutor` не делает runtime routing

- `src/cognitia/orchestration/workflow_executor.py:88-96`
- `tests/unit/test_workflow_executor.py:153-204`

`MixedRuntimeExecutor` сейчас только записывает `__runtime_executions__` metadata, но node всё равно исполняется через `wf._execute_node()` без использования соответствующего runtime. Текущие тесты это маскируют: они проверяют только metadata, а не реальное runtime-dependent execution.

### 5. `convert_event()` теряет `tool_name` на `tool_call_finished`

- `src/cognitia/runtime/ports/base.py:59-63`

При конвертации `RuntimeEvent.tool_call_finished` в `StreamEvent(type="tool_use_result")` теряется `tool_name`. Любой consumer port-level stream’а получает результат инструмента без имени инструмента, хотя upstream runtime event имя содержит.

Это не такой высокий приоритет, как terminal-contract gaps, но это реальный information loss в compatibility layer.

## Tests / docs / public narrative gaps

### 6. Новый skills import-isolation test даёт ложную уверенность

- `tests/unit/test_import_isolation.py:184-195`
- `src/cognitia/__init__.py:10`
- `src/cognitia/runtime/model_registry.py:18`
- `pyproject.toml:40-43`

Изолированный запуск:

`python -m pytest -q tests/unit/test_import_isolation.py::TestCoreImportsWithoutOptionalDeps::test_skills_optional_loader_fail_fast_without_yaml`

падает не на ожидаемом `ImportError("YamlSkillLoader ...")`, а раньше — через cold import `cognitia` и `yaml` в `runtime.model_registry`.

Важно: это не blocker публичного API, потому что `PyYAML` — core dependency. Но это плохой test signal: тест формулирует unsupported-env expectation и при этом order-dependent в большом suite.

### 7. Runtime docs/README отстают от реального public API

#### runtime count / valid runtime names

- `README.md:129-130`
- `README.md:173-195`
- `docs/api-reference.md:55-56`
- `docs/runtimes.md:3-15`
- `docs/why-cognitia.md:34-49`
- код:
  - `src/cognitia/runtime/capabilities.py:8`
  - `src/cognitia/runtime/registry.py:141-145`

Базовые docs всё ещё говорят о “3 runtimes” и перечисляют только `claude_sdk | thin | deepagents`, хотя код уже принимает `cli` как валидный runtime.

#### optional hook bridge semantics

- `docs/advanced.md:83-84`
- код:
  - `src/cognitia/hooks/__init__.py:13-26`

Docs по-прежнему говорят, что `registry_to_sdk_hooks` будет `None`, если SDK не установлен. После lazy fail-fast export это уже неверно: теперь import падает с `ImportError`.

### 8. Skills migration narrative остаётся внутренне противоречивой

- `src/cognitia/skills/__init__.py:1-4`
- `docs/architecture.md:58`
- `docs/tools-and-skills.md:77-80`
- `tests/unit/test_skills.py:6`

Package docstring говорит, что `YamlSkillLoader` вынесен в infrastructure layer и `skills` должен быть “чистый registry без IO”. Но docs и tests продолжают подавать loader как каноничную часть core `cognitia.skills` surface.

Это не моментальный runtime bug, но это явный sign, что migration narrative и public surface не доведены до конца.

## Static gate assessment

### `ruff`

Repo-wide lint всё ещё красный, и ошибки есть не только в тестах:

- source hot cluster:
  - `src/cognitia/runtime/deepagents.py:11-45` → `11` нарушений `E402`
- test-side шум:
  - многочисленные `F401` / `F841`, из-за которых реальный signal тонет

Текущий вывод: `ruff` пока нельзя использовать как строгий repo-wide merge gate.

### `mypy`

Repo-wide type-check красный не только из-за missing stubs. Есть реальные typed seams:

- `src/cognitia/memory/sqlite.py:127,164,201,246`
- `src/cognitia/runtime/structured_output.py:25,30`
- `src/cognitia/runtime/options_builder.py:131`
- `src/cognitia/runtime/thin/llm_providers.py:167,213-229`

Текущий вывод: typed regression в hot paths всё ещё может проскочить незамеченным.

## Broader debt worth keeping visible

- dual-path session state `adapter + runtime + runtime_messages` остаётся в hot path:
  - `src/cognitia/session/types.py:31-41`
  - `src/cognitia/session/manager.py:270-348`
- lifecycle API `Agent.cleanup()` в основном ceremonial:
  - `src/cognitia/agent/agent.py:27`
  - `src/cognitia/agent/agent.py:94-99`
  - runtime instances в реальном query/stream path создаются локально и чистятся в `finally`
- `DeepAgentsSubagentOrchestrator` по умолчанию остаётся tool-incomplete path:
  - `src/cognitia/orchestration/deepagents_subagent.py:32` и соседний ownership slice

## Recommended triage

### Must-fix next

1. `silent EOF -> synthetic done` в `BaseRuntimePort` и `SessionManager`
2. `ClaudeCodeRuntime` double-terminal behaviour (`error` + `final`)
3. `DeepAgents` portable history loss
4. `MixedRuntimeExecutor` fake routing / `ThinWorkflowExecutor` tool advertisement

### Fix with docs/tests batch

1. import-isolation test around skills/yaml
2. README / API reference / runtimes / why-cognitia docs sync for `cli`
3. docs sync for fail-fast `registry_to_sdk_hooks`
4. skills migration narrative sync

### Keep as tracked debt

1. repo-wide `ruff` cleanup
2. repo-wide `mypy` cleanup
3. session dual-path migration
4. ceremonial lifecycle / compatibility shims cleanup
