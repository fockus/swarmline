# Plan: Library Audit Remediation

Дата: 2026-03-18
Тип: fix
Тема: runtime/session hardening + static quality remediation after full library audit

## Контекст

Полный аудит библиотеки выявил две группы проблем:

1. P1/P2 логические дефекты и migration debt в runtime/session/orchestration слоях:
   - portable runtimes теряют `mcp_servers`;
   - `Conversation`/facade игнорируют `final.new_messages`;
   - `ThinTeamOrchestrator` не advertises `send_message`;
   - `collect_runtime_output()` и часть SDK wrapper’ов принимают incomplete runs как success;
   - `ThinRuntimePort` передаёт пустой `active_tools`;
   - legacy/session path теряет final metadata;
   - coexistence `RuntimePort` и `AgentRuntime` осталось в hot path.
2. repo-wide quality debt:
   - `ruff check src/ tests/` не зелёный;
   - `mypy src/cognitia/` не зелёный;
   - optional import surface экспортирует `None`;
   - docs/examples дрейфуют от каноничных runtime event names;
   - часть public protocols не имеет явных contract tests.

Цель плана: закрыть выявленные проблемы без расширения public API и без новых runtime зависимостей, сохранить backward compatibility там, где это осознанно требуется, и вернуть библиотеку к честному, проверяемому execution contract.

## Принципы исполнения

- Contract-first: сначала фиксируем и уточняем execution/terminal/history contracts.
- TDD: каждый defect batch начинается с failing regression tests.
- Low-risk slices: сначала private helpers / adapters / consumers, потом переключение call sites.
- Clean Architecture: сначала выравниваем contract ownership, затем compatibility shims выносим на периферию.
- No placeholders: никакого `TODO`, временных заглушек, молчаливых downgrade paths.
- Verification before Memory Bank actualization: checklist/status обновлять только после фактического green.

## Порядок фаз

### Phase 0 — Freeze contracts and failing tests

Цель:
- формализовать все проблемные seams до кода;
- зафиксировать expected behavior как тесты, чтобы параллельная реализация не разошлась по смыслу.

Шаги:
1. Добавить contract/integration regression tests для:
   - propagation `mcp_servers` в `thin`/`deepagents`;
   - consumption `final.new_messages` в `Agent.query`, `Conversation.say`, `Conversation.stream`;
   - terminal-event contract для `sdk_query`, `RuntimeAdapter`, `collect_runtime_output`;
   - preservation of final metadata в `BaseRuntimePort` и `SessionManager.stream_reply`;
   - `ThinRuntimePort` active tool advertisement;
   - `send_message` availability в `ThinTeamOrchestrator` worker tool list;
   - retry single-loop semantics в buffered `ThinRuntime`.
2. Зафиксировать expected behavior в test names и assertions только через business facts.

DoD:
- каждый подтверждённый finding имеет минимум один падающий regression test;
- tests падают по ожидаемой причине на текущем коде;
- нет новых мок-лабиринтов: где seam широкий, использовать integration-style test.

Параллелизация:
- Worker A: facade/runtime contract tests.
- Worker B: session/port contract tests.
- Worker C: orchestration/thin team/retry tests.

### Phase 1 — Runtime completion and data integrity

Цель:
- убрать ложные success path’ы;
- гарантировать, что every run ends in `final` or `error`;
- не терять final metadata.

Шаги:
1. Нормализовать terminal behavior в:
   - `src/cognitia/runtime/sdk_query.py`
   - `src/cognitia/runtime/adapter.py`
   - `src/cognitia/orchestration/runtime_helpers.py`
2. `collect_runtime_output()` сделать fail-fast при отсутствии terminal `final`/`error`.
3. В `BaseRuntimePort.stream_reply()` и `SessionManager.stream_reply()` переносить final metadata (`session_id`, `cost`, `usage`, `structured_output`, `native_metadata`) в `done` event.
4. Сохранить не более одного terminal event на run.

DoD:
- incomplete/truncated runtime output больше не возвращается как success;
- terminal contract одинаков для CLI, SDK, AgentRuntime helpers и legacy port path;
- final metadata не теряется в port/session wrappers;
- все новые regression tests зелёные.

Параллелизация:
- Worker A ownership:
  - `src/cognitia/runtime/sdk_query.py`
  - `src/cognitia/runtime/adapter.py`
- Worker B ownership:
  - `src/cognitia/runtime/ports/base.py`
  - `src/cognitia/session/manager.py`
- Worker C ownership:
  - `src/cognitia/orchestration/runtime_helpers.py`

### Phase 2 — Portable runtime wiring and tool surface

Цель:
- сделать portable path feature-complete относительно заявленного public API.

Шаги:
1. Пробросить `mcp_servers` из `AgentConfig`/`Conversation` в portable runtime factory path.
2. Исправить `ThinRuntimePort`, чтобы он передавал реальные `active_tools`, а не пустой список.
3. В `ThinTeamOrchestrator` не только регистрировать executor `send_message`, но и добавлять соответствующий `ToolSpec` в worker-visible tools.
4. Проверить, что remote MCP tools и team messaging видны LLM, а не только backend execution path.

DoD:
- `runtime="thin"` и `runtime="deepagents"` реально используют `mcp_servers`;
- `ThinRuntimePort` advertises tools consistently with executors;
- workers команды реально видят `send_message` tool в tool list;
- tests подтверждают не только executor registration, но и advertised tool surface.

Параллелизация:
- Worker A ownership:
  - `src/cognitia/agent/agent.py`
  - `src/cognitia/agent/conversation.py`
- Worker B ownership:
  - `src/cognitia/runtime/ports/thin.py`
- Worker C ownership:
  - `src/cognitia/orchestration/thin_team.py`
  - `src/cognitia/orchestration/thin_subagent.py`

### Phase 3 — History ownership and canonical runtime contract

Цель:
- довести `AgentRuntime` contract до реального source of truth;
- перестать терять tool/history context между turn’ами.

Шаги:
1. На facade/session уровне использовать `final.new_messages` как authoritative delta истории.
2. В `Conversation.say()` и `Conversation.stream()` перестать хранить только финальный assistant text; сохранять все canonical `new_messages`.
3. В `collect_stream_result()` расширить сбор результата так, чтобы history-level consumers могли извлекать `new_messages`, не ломая existing result API.
4. Привести session runtime path к той же модели ownership, что и direct facade path.

DoD:
- после tool-use multi-turn conversation сохраняет и повторно использует tool context;
- history mutation происходит из canonical runtime final payload, а не из эвристики по `text_delta`;
- backward compatibility `Result.text` не ломается;
- tests покрывают `react`/tool scenarios, а не только simple conversational turns.

Параллелизация:
- Worker A ownership:
  - `src/cognitia/agent/agent.py`
  - `src/cognitia/agent/conversation.py`
- Worker B ownership:
  - `src/cognitia/session/manager.py`
- Shared review point:
  - `src/cognitia/runtime/base.py`
  - `src/cognitia/runtime/types.py`

### Phase 4 — Retry normalization in ThinRuntime

Цель:
- убрать nested retry loops и привести retry semantics к одной понятной модели.

Шаги:
1. Определить один authoritative retry layer:
   - либо wrapper в `ThinRuntime.__init__()`,
   - либо buffered call path в strategy layer.
2. Удалить дублирующий loop из второго уровня.
3. Сохранить observability:
   - retry status events;
   - cancellation behavior;
   - bounded retries по policy.

DoD:
- одна transient failure создаёт ровно один retry flow;
- retry delays и max attempts соответствуют policy, без удвоения;
- не дублируются retry status events;
- integration tests фиксируют attempts/delay semantics.

Параллелизация:
- Single-owner slice:
  - `src/cognitia/runtime/thin/runtime.py`
  - `src/cognitia/runtime/thin/helpers.py`
  - `src/cognitia/runtime/thin/conversational.py`
  - `src/cognitia/runtime/thin/react_strategy.py`

### Phase 5 — Runtime/session migration cleanup

Цель:
- вывести compatibility debt из hot path;
- уменьшить SRP/DRY violations в `SessionManager`, `Agent`, `Conversation`.

Шаги:
1. Выделить единый composition helper/service для:
   - runtime creation,
   - tool executor wiring,
   - hook merge,
   - MCP injection,
   - SDK options building.
2. Перевести `Agent` и `Conversation` на shared composition path.
3. Локализовать legacy `RuntimePort` path:
   - либо только adapter shim,
   - либо только backward compatibility layer без дублирования ownership.
4. Определить судьбу `Agent.cleanup()`:
   - либо runtime ownership становится реальным,
   - либо lifecycle API упрощается и честно документируется.
5. Уменьшить dual-path state в `SessionState`.

DoD:
- `Agent`, `Conversation`, `SessionManager` не дублируют одну и ту же wiring-логику;
- SDK-specific options ведут себя одинаково во всех entrypoints;
- legacy path либо изолирован, либо удалён из production hot path;
- количество приватных cross-calls между `Agent` и `Conversation` сокращено;
- новые tests проверяют одинаковую семантику разных entrypoints.

Параллелизация:
- Worker A ownership:
  - `src/cognitia/agent/agent.py`
  - `src/cognitia/agent/conversation.py`
- Worker B ownership:
  - `src/cognitia/session/types.py`
  - `src/cognitia/session/manager.py`
- Worker C ownership:
  - new shared composition helper/module in `src/cognitia/agent/` or `src/cognitia/runtime/`

### Phase 6 — Factory/registry and optional surface hardening

Цель:
- сделать public/runtime composition fail-fast и детерминированным;
- убрать `None` placeholders из публичной поверхности.

Шаги:
1. Канонизировать runtime creation вокруг registry path.
2. Для optional imports:
   - либо explicit lazy getter,
   - либо dedicated integration modules,
   - либо fail-fast proxy with clear dependency message.
3. Привести `RuntimeFactory` override path к корректному `effective_config`.
4. Вычистить backward-compatible re-exports в `memory/__init__.py`, `skills/__init__.py`, `runtime/__init__.py`, `runtime/ports/__init__.py`, `hooks/__init__.py`.

DoD:
- public import больше не возвращает `None` вместо API symbol;
- `RuntimeFactory` и registry не расходятся по built-in runtime names;
- `cli`/`thin`/`deepagents` creation semantics единообразны;
- `ruff`/`mypy` больше не падают на assignment noise из optional exports.

Параллелизация:
- Worker A ownership:
  - `src/cognitia/runtime/factory.py`
  - `src/cognitia/runtime/registry.py`
- Worker B ownership:
  - `src/cognitia/runtime/__init__.py`
  - `src/cognitia/runtime/ports/__init__.py`
  - `src/cognitia/hooks/__init__.py`
- Worker C ownership:
  - `src/cognitia/memory/__init__.py`
  - `src/cognitia/skills/__init__.py`

### Phase 7 — Type system and static gates

Цель:
- сделать `ruff` и `mypy` честными и рабочими quality gates.

Шаги:
1. Починить реальные type defects:
   - `runtime/structured_output.py`
   - `runtime/sdk_query.py`
   - `runtime/options_builder.py`
   - `memory/sqlite.py`
   - `memory/postgres.py`
   - `runtime/adapter.py`
   - `agent/conversation.py`
2. Развести:
   - реальные type issues;
   - missing optional deps/stubs.
3. Привести `pyproject.toml` и dev workflow в соответствие:
   - либо `mypy` на subset без extras;
   - либо dev extra включает всё нужное для advertised command;
   - либо отдельные mypy profiles.
4. Закрыть repo-wide `ruff` debt в `src/` и `tests/`.

DoD:
- `ruff check src/ tests/` зелёный;
- `mypy`-gate определён явно и зелёный в поддерживаемом dev setup;
- нет `type: ignore` без документированной причины;
- optional deps не маскируют реальные type regressions.

Параллелизация:
- Worker A ownership:
  - `src/cognitia/runtime/structured_output.py`
  - `src/cognitia/runtime/sdk_query.py`
  - `src/cognitia/runtime/options_builder.py`
  - `src/cognitia/runtime/adapter.py`
- Worker B ownership:
  - `src/cognitia/memory/sqlite.py`
  - `src/cognitia/memory/postgres.py`
- Worker C ownership:
  - `tests/` ruff cleanup
  - `pyproject.toml`

### Phase 8 — Protocol boundaries, docs and examples

Цель:
- синхронизировать contracts, docs и examples;
- убрать ложные architectural claims.

Шаги:
1. Либо привести `protocols` package к обещанным зависимостям, либо обновить contract docs честно.
2. Исправить docs/examples на каноничные runtime event names и актуальные semantics.
3. Добавить explicit contract tests на exported protocols, которые сейчас не покрыты.
4. Проверить examples на отсутствие unfinished lifecycle placeholders.

DoD:
- docs и examples соответствуют текущему event model и runtime behavior;
- exported protocol surface имеет хотя бы smoke/contract coverage;
- no dead/lying docs about layer boundaries;
- examples runnable и не дрейфуют от каноничных API names.

Параллелизация:
- Worker A ownership:
  - `src/cognitia/protocols/*`
- Worker B ownership:
  - `README.md`
  - `docs/*.md`
  - `examples/*.py`
- Worker C ownership:
  - protocol contract tests in `tests/unit/`

## Быстрый план реализации по волнам

### Волна 1 — blocking correctness

Содержимое:
- Phase 0
- Phase 1
- Phase 2
- Phase 3
- Phase 4

Почему сначала:
- это реальные логические дефекты и partially integrated paths;
- они user-visible и влияют на correctness больше, чем static debt.

### Волна 2 — architectural hardening

Содержимое:
- Phase 5
- Phase 6

Почему потом:
- после фикса correctness можно безопаснее резать migration debt;
- меньше шанс смешать bugfix и refactor в одном диффе.

### Волна 3 — static gates and sync

Содержимое:
- Phase 7
- Phase 8

Почему в конце:
- static/type cleanup должен ложиться уже на стабилизированную архитектуру;
- docs/examples проще синхронизировать после выравнивания contracts.

## План делегирования сабагентам

### Worker 1 — Facade + portable runtime wiring

Ownership:
- `src/cognitia/agent/agent.py`
- `src/cognitia/agent/conversation.py`
- related tests in `tests/unit/test_agent_*`, `tests/integration/test_runtime_portable_matrix.py`

Задачи:
- `mcp_servers` propagation;
- `final.new_messages` consumption;
- unification of facade semantics;
- shared runtime composition extraction.

Правило:
- не трогать `session/` и `runtime/ports/`, кроме чтения для совместимости.

### Worker 2 — Session + RuntimePort legacy containment

Ownership:
- `src/cognitia/session/types.py`
- `src/cognitia/session/manager.py`
- `src/cognitia/runtime/ports/base.py`
- `src/cognitia/runtime/ports/thin.py`

Задачи:
- metadata preservation;
- history ownership on legacy path;
- `active_tools` in `ThinRuntimePort`;
- localization of legacy `RuntimePort` path.

Правило:
- не рефакторить facade/runtime factory modules без явной необходимости.

### Worker 3 — SDK/runtime completion contract + orchestration

Ownership:
- `src/cognitia/runtime/sdk_query.py`
- `src/cognitia/runtime/adapter.py`
- `src/cognitia/orchestration/runtime_helpers.py`
- `src/cognitia/orchestration/thin_team.py`
- `src/cognitia/orchestration/thin_subagent.py`

Задачи:
- terminal-event enforcement;
- no silent success on incomplete runs;
- `send_message` advertisement;
- orchestration runtime output correctness.

Правило:
- не лезть в static/lint cleanup и не править `agent/` call sites.

### Worker 4 — ThinRuntime retry normalization

Ownership:
- `src/cognitia/runtime/thin/runtime.py`
- `src/cognitia/runtime/thin/helpers.py`
- `src/cognitia/runtime/thin/conversational.py`
- `src/cognitia/runtime/thin/react_strategy.py`

Задачи:
- single retry layer;
- retry observability;
- bounded/cancellable behavior.

Правило:
- не менять semantics outside retry/postprocessing paths.

### Worker 5 — Static gates + public surface cleanup

Ownership:
- `src/cognitia/runtime/__init__.py`
- `src/cognitia/runtime/ports/__init__.py`
- `src/cognitia/hooks/__init__.py`
- `src/cognitia/memory/__init__.py`
- `src/cognitia/skills/__init__.py`
- `pyproject.toml`
- repo-wide lint/type cleanup in `tests/`

Задачи:
- optional import surface;
- `ruff`;
- `mypy`;
- re-export cleanup;
- honest dev/type workflow.

Правило:
- запускать после мержа Wave 1, чтобы не чинить типы поверх меняющихся контрактов.

## Verification plan

### После каждой фазы

Обязательно:
- targeted unit/integration tests по затронутым модулям;
- `ruff check` по changed files;
- при затрагивании runtime contracts — targeted `mypy` на затронутые пакеты.

### После Wave 1

Обязательно:
- весь набор новых regression tests зелёный;
- `pytest -q tests/unit/test_agent_* tests/unit/test_runtime_* tests/integration/test_*runtime* tests/integration/test_*team*` green;
- smoke path для CLI/SDK/thin/deepagents wrappers без silent-success regressions.

### После Wave 2

Обязательно:
- broader regression по `agent`, `session`, `runtime`, `orchestration`;
- сравнение plan vs code vs checklist;
- проверка backward compatibility на публичных entrypoints.

### После Wave 3

Обязательно:
- `ruff check src/ tests/` green;
- agreed `mypy` command green;
- `pytest -q` full offline green;
- docs/examples smoke-checked.

## Критерии приёмки плана

План считаем готовым к реализации, если одновременно выполнены все условия:

1. Все findings из audit report разложены по конкретным фазам, а не оставлены как “разобраться потом”.
2. Для каждой фазы есть:
   - цель,
   - конкретные шаги,
   - DoD,
   - порядок зависимостей,
   - ownership для параллельной реализации.
3. P1 correctness issues идут раньше architectural cleanup и static debt.
4. План совместим с правилами проекта:
   - contract-first,
   - TDD,
   - low-risk slices,
   - verification before Memory Bank status updates.
5. Работа реально распараллеливается по disjoint write sets, чтобы subagents не конфликтовали.
6. В конце есть чёткие acceptance gates:
   - targeted green,
   - broader regression green,
   - repo-wide static gates green,
   - docs/examples synchronized.
