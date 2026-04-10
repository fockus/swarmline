# Library Audit — 2026-03-18

## Scope

Полный read-only аудит библиотеки `cognitia` по следующим направлениям:

- code review и логические дефекты;
- Clean Architecture / SOLID / DRY / KISS;
- `ruff` и `mypy` по репозиторию;
- dead code / partially integrated paths / migration debt;
- проверка, насколько зелёные тесты действительно защищают контракты.

Аудит выполнен с участием сабагентов:

- `Mendel` — архитектура, SOLID, migration debt;
- `Linnaeus` — runtime/session/orchestration логика;
- `Dalton` — static quality, `ruff`, `mypy`, dead code, gaps.

## Methodology

Использованы:

- repo-wide `ruff check src/ tests/ --statistics`;
- repo-wide `mypy src/cognitia/`;
- полный offline `pytest -q`;
- ручной просмотр hot-path модулей: `agent/`, `session/`, `runtime/`, `orchestration/`, `memory/`, `protocols/`;
- выборочная проверка public surface и compatibility shims;
- поиск по тестам на фактическое покрытие публичных протоколов.

## Verification Snapshot

- `pytest -q`: `2331 passed, 16 skipped, 5 deselected, 19 warnings`
- `ruff check src/ tests/ --statistics`: `68 errors`
- Разбивка `ruff`: `15` ошибок в `src/`, `53` в `tests/`
- Разбивка `ruff` по правилам:
  - `32` `F401` unused-import
  - `29` `E402` module-import-not-at-top-of-file
  - `6` `F841` unused-variable
  - `1` `F541` f-string-missing-placeholders
- `mypy src/cognitia/`: `48 errors in 23 files`
- Разбивка `mypy` по кодам:
  - `13` `arg-type`
  - `12` `assignment`
  - `8` `import-not-found`
  - `8` `attr-defined`
  - `2` `var-annotated`
  - `2` `misc`
  - `2` `import-untyped`
  - `1` `union-attr`
- import-smoke пакета не выявил hard import failures.

Вывод: test suite очень широкий, но статические quality gates сейчас не являются рабочими repo-wide gate'ами.

## Executive Summary

Библиотека в целом функциональна и имеет сильное тестовое покрытие по happy-path и многим integration-сценариям, но архитектурная миграция runtime/session слоя не доведена до конца. Из-за этого в hot path живут два контракта одновременно, часть portable runtime возможностей не подключена из facade/session слоёв, а несколько вспомогательных обёрток продолжают переводить оборванные или неполные исполнения в ложный успех.

Главная проблема не в отдельных style-ошибках, а в том, что:

1. канонический `AgentRuntime` контракт уже объявлен, но не везде реально является source of truth;
2. compatibility shims остались в production path, а не на периферии;
3. тесты зелёные, но не покрывают несколько критичных seams: перенос `mcp_servers`, consumption `final.new_messages`, runtime completion contract, и tool advertisement в team orchestration.

## Confirmed Findings

### P1 — portable runtimes silently lose remote MCP integration

`Agent` и `Conversation` создают portable runtime'ы через `RuntimeFactory`, но не передают туда `AgentConfig.mcp_servers`:

- `src/cognitia/agent/agent.py:169-174`
- `src/cognitia/agent/conversation.py:145-149`

При этом сами runtime'ы умеют принимать remote MCP servers:

- `src/cognitia/runtime/deepagents.py:70-86`
- `src/cognitia/runtime/thin/runtime.py:53-58`

Следствие: `runtime="thin"` и `runtime="deepagents"` молча теряют remote MCP tool discovery/execution, хотя пользователь передал `mcp_servers` в публичный `AgentConfig`.

### P1 — multi-turn history ignores `final.new_messages` and loses tool context

Контракт `AgentRuntime` явно говорит, что runtime возвращает историю через `final.new_messages`:

- `src/cognitia/runtime/base.py:3-8`
- `src/cognitia/runtime/base.py:62-65`

Но фасадный сбор результата и conversation-history это игнорируют:

- `src/cognitia/agent/agent.py:297-333`
- `src/cognitia/agent/conversation.py:54-63`
- `src/cognitia/agent/conversation.py:86-95`

Это уже ломает реальный сценарий в `ThinRuntime` react path, где tool-call context складывается в `new_messages`:

- `src/cognitia/runtime/thin/react_strategy.py:190-206`

Следствие: после turn'а с инструментом следующий turn в `Conversation` идёт без tool/result контекста, хотя runtime его сформировал.

### P1 — `ThinTeamOrchestrator` регистрирует `send_message` executor, но не публикует tool spec

`ThinTeamOrchestrator.start()` обещает, что каждый worker автоматически получает `send_message` tool, и регистрирует executor:

- `src/cognitia/orchestration/thin_team.py:72-90`

Но `ThinSubagentRuntime` публикует только `self._spec.tools`:

- `src/cognitia/orchestration/thin_subagent.py:194-207`

В `spec.tools` этот tool не добавляется. В результате инструмент существует на execution side, но не виден LLM в advertised tool list.

### P1 — `collect_runtime_output()` treats truncated/incomplete runs as success

Хелпер для subagent/workflow путей:

- `src/cognitia/orchestration/runtime_helpers.py:14-49`

считает поток успешным, если видел только `assistant_delta`, и возвращает partial text даже без terminal `final`/`error`. Это расходится с runtime contract:

- `src/cognitia/runtime/base.py:62-65`

Следствие: обрезанный или аварийно оборванный run может быть принят orchestration слоем как completed.

### P1 — `ThinRuntimePort` effectively disables tools

Порт декларирует поддержку `local_tools`, но при вызове runtime всегда передаёт пустой `active_tools`:

- `src/cognitia/runtime/ports/thin.py:73-85`

Runtime получает executors, но LLM не получает описания инструментов. Это partially integrated path: инструменты технически существуют, но для модели они невидимы.

### P1 — SDK wrappers still allow silent success without terminal SDK result

В SDK one-shot path итоговое событие/результат формируются даже если `ResultMessage` не пришёл:

- `src/cognitia/runtime/sdk_query.py:160-170`
- `src/cognitia/runtime/sdk_query.py:221-267`
- `src/cognitia/runtime/adapter.py:291-342`

Проблема аналогична уже исправленному дефекту в CLI runtime: truncated/partial SDK stream может превратиться в `ok`-результат с пустыми метаданными вместо typed error.

### P1 — final metadata is dropped in legacy `RuntimePort` path

`BaseRuntimePort.stream_reply()` сохраняет только `final.text`, а затем переупаковывает итог в `StreamEvent(type="done")` без `session_id`, `total_cost_usd`, `structured_output`, `native_metadata`:

- `src/cognitia/runtime/ports/base.py:269-294`

Аналогично `SessionManager.stream_reply()` для runtime path:

- `src/cognitia/session/manager.py:287-335`

Следствие: legacy/session stream paths теряют полезные final metadata даже если runtime их отдал.

## Architecture / SOLID / DRY / KISS Findings

### P2 — runtime/session migration not finished; two contracts live in the hot path

`SessionState` одновременно держит:

- `adapter: RuntimePort | None`
- `runtime: AgentRuntime | None`
- `runtime_messages` для legacy path

См.:

- `src/cognitia/session/types.py:27-41`
- `src/cognitia/session/manager.py:270-340`

Это уже не thin compatibility shim, а полноценная dual-path execution model. Нарушается KISS и SRP: `SessionManager` обязан поддерживать две модели жизненного цикла, две истории и два формата событий.

### P2 — `Agent` and `Conversation` duplicate runtime wiring and are already drifting semantically

Дублируются:

- runtime dispatch
- hook merge
- tools → MCP wiring
- runtime config assembly
- SDK adapter construction

Ключевые места:

- `src/cognitia/agent/agent.py:105-213`
- `src/cognitia/agent/conversation.py:114-220`

Это уже привело к реальному behavioural drift: `Conversation` прокидывает `sandbox` и `max_thinking_tokens` в `ClaudeOptionsBuilder.build()`, а `Agent.query()/stream()` через `sdk_query` не могут передать эти опции:

- `src/cognitia/agent/agent.py:136-156`
- `src/cognitia/agent/conversation.py:192-210`

### P2 — `RuntimeFactory` and `RuntimeRegistry` are partially duplicated and inconsistent

`RuntimeFactory` сначала идёт в registry, потом имеет legacy fallback `if/elif`:

- `src/cognitia/runtime/factory.py:152-192`

Но fallback знает только `claude_sdk/deepagents/thin`, тогда как registry/valid names уже включают `cli`.

Дополнительно, при `runtime_override` создаётся runtime с исходным `config`, а не с нормализованным `RuntimeConfig(runtime_name=name)`:

- `src/cognitia/runtime/factory.py:152-171`

Это не обязательно ломает всё немедленно, но делает composition path неканоничным и увеличивает риск drift.

### P2 — public optional API exports `None` instead of failing fast

В `cognitia.runtime` optional symbols сначала присваиваются `None`, а затем попадают в `__all__` независимо от наличия extras:

- `src/cognitia/runtime/__init__.py:42-48`
- `src/cognitia/runtime/__init__.py:66-84`
- `src/cognitia/runtime/__init__.py:86-129`

Схожий паттерн есть в:

- `src/cognitia/runtime/ports/__init__.py:17-24`
- `src/cognitia/hooks/__init__.py:7-10`

Это fail-late surface: import выглядит успешным, а реальная ошибка сдвигается в место вызова `None`.

### P2 — `ThinRuntime` has nested retry loops in buffered path

`ThinRuntime.__init__()` сначала оборачивает `llm_call` в `_wrap_with_retry()`:

- `src/cognitia/runtime/thin/runtime.py:63-70`

А buffered strategies затем ещё раз передают `retry_policy` в `run_buffered_llm_call()`:

- `src/cognitia/runtime/thin/helpers.py:44-50`
- `src/cognitia/runtime/thin/conversational.py:43-56`
- `src/cognitia/runtime/thin/react_strategy.py:65-73`

Следствие: возможны вложенные retry loops, завышенные задержки и дублированные retry-status events.

### P3 — `Agent.cleanup()` is a dead lifecycle abstraction

`Agent` хранит поле `_runtime`, но реальные execution paths создают runtime локально и сразу чистят его в `finally`:

- `src/cognitia/agent/agent.py:21-24`
- `src/cognitia/agent/agent.py:79-84`
- `src/cognitia/agent/agent.py:169-191`

То есть `cleanup()` выглядит как реальный lifecycle API, но production path почти ничего через него не освобождает.

### P3 — `protocols` package violates its own dependency contract

Докстринг обещает зависимости только на `cognitia.types` и stdlib:

- `src/cognitia/protocols/__init__.py:1-8`

Но протоколы импортируют конкретные типы из инфраструктурных/смежных пакетов:

- `src/cognitia/protocols/memory.py:7`
- `src/cognitia/protocols/runtime.py:28-31`

Это снижает доверие к декларируемым layer boundaries.

## Static Quality Findings

### `ruff` is not green repo-wide

Снимок:

- `68` ошибок total
- `15` в `src/`
- `53` в `tests/`

Source-примеры:

- `src/cognitia/runtime/deepagents.py:11` — `E402`
- `src/cognitia/runtime/__init__.py:50` — `E402`
- `src/cognitia/memory/__init__.py:23` — `F401`

### `mypy` is not a working repository gate

Repo-wide запуск:

- `48` ошибок в `23` файлах

Повторяющиеся категории:

- optional import surface (`assignment`) из-за `symbol = None` + `suppress(ImportError)`
- public typing drift (`attr-defined`, `arg-type`)
- missing optional deps/stubs (`import-not-found`, `import-untyped`)

Показательные примеры:

- `src/cognitia/runtime/structured_output.py:11-30`
- `src/cognitia/runtime/sdk_query.py:55-88`
- `src/cognitia/runtime/options_builder.py:123-149`
- `src/cognitia/memory/sqlite.py:127`, `164`, `201`, `246`
- `src/cognitia/runtime/adapter.py:36`

### `dev` extra is insufficient for advertised type-check workflow

`pyproject.toml` рекламирует `mypy src/cognitia/`, но `dev` extra не включает ни optional extras, ни stub packages:

- `pyproject.toml:133-139`

Отсюда часть repo-wide `mypy` failures возникает не из-за конкретного дефекта в логике, а из-за того, что сам gate не соответствует declared dev environment.

### Backward-compatible re-exports are incomplete

Есть import-ы, которые не попадают в `__all__`, из-за чего:

- `ruff` помечает их как unused;
- public API становится неочевидным.

Примеры:

- `src/cognitia/memory/__init__.py:22-35` — `PostgresMemoryProvider` импортируется, но не экспортируется
- `src/cognitia/skills/__init__.py:13-20` — `YamlSkillLoader` и `load_mcp_from_settings` импортируются, но не экспортируются

## Test Gaps

Несмотря на зелёный `pytest`, нашлись важные seams без явного contract coverage.

### Нет coverage на public protocol usage

Поиск по `tests/` не дал упоминаний следующих exported protocol names:

- `MessageStore`
- `FactStore`
- `GoalStore`
- `SummaryStore`
- `SessionStateStore`
- `UserStore`
- `PhaseStore`
- `ToolEventStore`
- `SessionFactory`
- `SessionLifecycle`
- `ContextBuilder`

Команда проверки дала `0` попаданий для всех перечисленных символов.

### Нет regression tests на:

- propagation `mcp_servers` из `AgentConfig` в portable runtimes;
- consumption `final.new_messages` в `Conversation`;
- mandatory terminal result contract для SDK wrapper path;
- availability of `send_message` tool in thin team worker tool specs;
- preservation of final metadata в `BaseRuntimePort` / `SessionManager.stream_reply`.

## DRY / KISS / SOLID Assessment

### Что сделано хорошо

- сильное покрытие unit/integration tests по многим feature slices;
- typed event model в `runtime/types.py`;
- хороший объём contract-style tests вокруг recent runtime/multi-agent additions;
- заметное стремление к DIP через Protocols и runtime abstraction.

### Что сейчас мешает

- SRP нарушен в `SessionManager`, `Agent`, `Conversation`, `RuntimeFactory`;
- DRY нарушен в SDK/runtime wiring и final result handling;
- KISS нарушен coexistence двух runtime-контрактов в active path;
- fail-fast местами заменён на silent downgrade (`None` exports, incomplete run treated as success).

## Recommended Repair Tracks

### Track A — finish runtime/session migration

Цель:

- один канонический execution contract (`AgentRuntime`);
- legacy `RuntimePort` вынести на периферию или удалить из hot path;
- history ownership везде строить через `final.new_messages`.

### Track B — normalize portable runtime wiring

Цель:

- один composition path для `mcp_servers`, `tools`, `hooks`, `sandbox`, `betas`, `thinking`, `budget`;
- одинаковая семантика у `Agent`, `Conversation`, `SessionManager`.

### Track C — repair runtime completion contracts

Цель:

- любой runtime/helper/wrapper обязан завершаться `final` или `error`;
- отсутствие terminal event переводить в typed error, а не в partial success.

### Track D — make static gates honest

Цель:

- починить optional import surface;
- привести `dev` extra в соответствие с advertised `mypy` workflow;
- закрыть repo-wide `ruff` debt;
- отделить missing optional deps от настоящих type errors.

### Track E — add missing contract regressions

Минимальный обязательный набор:

- portable `mcp_servers` propagation;
- `final.new_messages` consumption;
- `send_message` tool advertisement in thin teams;
- metadata preservation in `BaseRuntimePort`/`SessionManager`;
- terminal result contract for SDK wrappers.

## Bottom Line

Проект нельзя назвать "сырой": behaviour в большом числе сценариев уже проверен, а offline tests зелёные. Но библиотеку нельзя считать архитектурно стабилизированной. Основной риск сейчас не в том, что всё сломано, а в том, что migration debt и partially integrated paths создают ложное чувство завершённости: API выглядит унифицированным, тогда как в ряде ключевых seam'ов semantics зависит от entrypoint и runtime path.

Практический вывод: перед следующей feature wave стоит сделать целевой hardening runtime/session/orchestration слоя и привести static gates в рабочее состояние, иначе новые возможности будут наращиваться поверх уже расходящихся контрактов.
