# Plan: Thin Coding-Agent Profile для swarmline

**Тип**: feature  
**Дата**: 2026-04-12  
**Основа**:
- `reports/2026-04-12_analysis_thin-coding-agent-reuse-aura-claw-pi-mono.md`
- `reports/2026-04-12_audit_thin-runtime-gaps.md`
- текущий активный план parity: `plans/2026-04-12_feature_thin-runtime-claude-code-parity.md`

## Цель

Собрать `ThinRuntime` в полноценный **coding-agent profile** без создания нового runtime:
- с единым tool surface для работы с кодом и файлами
- с persistent task/todo runtime
- с безопасным execution/path layer
- с richer context engineering для длинных coding задач

Итоговая цель не “сделать ещё один CLI-агент”, а усилить `swarmline` как **движок для создания coding agents**.

---

## Почему это отдельный план

Текущий план parity закрывает базовые runtime gaps:
- hooks
- tool policy
- LLM-initiated subagents
- commands
- native tool calling

Этот план — **следующий слой**, который строится поверх parity и делает `thin` пригодным именно для coding-agent сценариев.

---

## Обязательные правила исполнения

Этот план должен исполняться с явным соблюдением `RULES.md`.

### 1. TDD-first

Для каждой новой логики:
- сначала contract / unit / integration tests
- затем минимальная реализация
- затем рефакторинг

Исключения:
- чисто механические renames
- docs-only changes
- comment/docstring-only clarifications

### 2. Contract-first

Каждый новый subsystem начинается с Protocol / dataclass / typed contract:
- path service
- task runtime facade
- file mutation queue abstraction
- context compiler extension seam

Порядок:
1. protocol / interface
2. contract tests
3. implementation

### 3. Clean Architecture

Зависимости только в разрешённом направлении:
- `Domain` не импортирует `Infrastructure`
- `Application` зависит только от `Domain`
- `Infrastructure` реализует контракты

Следствие для этого плана:
- `PathService`, task-facing ports и context contracts должны жить в domain/application слое
- filesystem/sandbox/builtin integration — в infrastructure/runtime/tools

### 4. SOLID / DRY / KISS / YAGNI

Обязательные ограничения:
- interface ≤ 5 методов
- новые возможности расширять через composition, а не через монолитные `if/else`
- не добавлять “на будущее” generic plugin system под coding-agent, если текущий use case решается небольшими seams
- не дублировать существующие `todo`, `sandbox`, `task board`, `context builder`

### 5. No new dependencies

Новых библиотек не добавлять без отдельного запроса.  
Всё должно быть построено поверх уже существующих зависимостей `swarmline`.

### 6. Fail-fast

Если конкретный feature mode или backend не поддержан:
- явная ошибка
- без silent fallback, который ломает безопасность или делает поведение неочевидным

---

## Не-цели

Этот план **не** включает:
- новый отдельный runtime помимо `thin`
- перенос app-specific кода из `aura`
- literal copy кода из `claw-code-agent` до подтверждения лицензии
- UI/CLI продуктовую обвязку поверх coding-agent
- новые внешние сервисы, orchestration SaaS, hosted tracing

---

## Pre-conditions

Перед началом реализации по этому плану должны быть выполнены:

1. Завершён или стабилизирован текущий parity tranche:
- hooks
- tool policy
- subagents
- command routing
- native tool calling

2. Green baseline:
- targeted tests по thin/runtime/policy/hooks
- `ruff check src/ tests/`
- `mypy src/swarmline/`

3. Согласовано, что этот план идёт как **следующий minor feature tranche**, а не как side-track refactor.

---

## Целевой результат

После выполнения плана `swarmline` должен уметь предоставлять `ThinRuntime` как coding-agent engine со следующими свойствами:

1. Агент видит и использует согласованный набор coding tools.
2. Task/todo состояние persist'ится и переживает restart/resume.
3. Файловые мутации безопасны и сериализуются на уровне одного файла.
4. Пути нормализуются через единый canonical path layer.
5. Контекст для coding-task runs строится из task/session/search/skill/workspace summaries.
6. Tool policy для coding-agent режима включается явно, не ломая secure defaults библиотеки.

---

## Phase 0: Architecture Slice и контракты

**Приоритет**: P0  
**Зачем**: не дать реализации расползтись по runtime/tools/session/context без явной модели.

### Задачи

1. Определить целевые контракты:
- `CodingTaskRuntime` Protocol
- `PathService` Protocol или domain service interface
- `FileMutationCoordinator` Protocol
- `CodingContextPack` / `CodingContextAssembler` contract

2. Определить canonical boundaries:
- что является domain logic
- что является infra implementation
- где живёт wiring для `thin`

3. Зафиксировать mapping существующих частей:
- `tools/builtin.py`
- `todo/tools.py`
- `GraphTaskBoard`
- `TaskSessionStore`
- `context/builder.py`

4. Зафиксировать naming strategy:
- canonical tool names
- compatibility aliases
- profile naming (`coding`, `coding_agent`, `thin_coding`)

### Файлы

- `src/swarmline/...` — только новые Protocol/dataclass files или минимальные domain seams
- возможно ADR note в `.memory-bank/BACKLOG.md`, если потребуется архитектурное решение

### Тесты (RED first)

- `tests/unit/...contract...`
- `tests/unit/...protocol...`

### DoD

- [ ] Все новые контракты оформлены через Protocol/dataclass
- [ ] Ни один новый interface не превышает 5 методов
- [ ] Есть contract tests для каждого нового контракта
- [ ] Границы Domain/Application/Infrastructure описаны в docstrings/plan comments
- [ ] Нет реализации до появления контрактов и тестов
- [ ] `ruff` и `mypy` green на новых файлах

---

## Phase 1: Unified Coding Tool Pack

**Приоритет**: P0  
**Зачем**: сейчас tools физически есть, но surface фрагментирован и partly stubbed.

### Задачи

1. Сделать единый canonical pack для coding tools:
- `read`
- `write`
- `edit`
- `multi_edit`
- `bash`
- `ls`
- `glob`
- `grep`
- `todo_read`
- `todo_write`
- task-facing tools

2. Убрать thin-specific stubs:
- текущий `write_todos` markdown shim
- текущий noop `task`

3. Свести thin aliases к compatibility layer:
- `read_file -> read`
- `write_file -> write`
- `edit_file -> edit`
- `execute -> bash`
- legacy todo/task aliases — через canonical implementations

4. Починить active tool assembly:
- builtin executors и builtin tool specs должны попадать в один и тот же tool surface
- subagent inheritance должна видеть реальный активный набор инструментов

5. Обновить descriptions/schemas так, чтобы они направляли модель к правильному использованию tool pack.

### Источники reuse

- reuse из `swarmline`: `tools/builtin.py`, `todo/tools.py`
- reference из `pi-mono`: read UX, truncation, continuation hints
- reference из `claw`: tool surface shape

### Тесты (RED first)

- unit tests на canonical name resolution
- unit tests на alias compatibility
- integration tests на end-to-end tool visibility в thin runtime
- integration tests на subagent tool inheritance

### DoD

- [ ] В thin нет stub-only `write_todos/task` пути
- [ ] Canonical coding tools backed by real executors/providers
- [ ] Legacy aliases работают без behavioural drift
- [ ] Active tool list и executor registry согласованы
- [ ] Tool descriptions и schemas не дублируются в двух независимых источниках
- [ ] Есть integration test, где модельный runtime видит и использует unified tool pack
- [ ] Все существующие tool-related regressions проходят
- [ ] `ruff`, `mypy`, targeted `pytest` green

### Риски

- alias drift между старым и новым surface
- поломка backward compatibility в portable/native paths

### Mitigation

- compatibility tests на все legacy names
- migration slice без удаления aliases в этой фазе

---

## Phase 2: Coding Task Runtime поверх существующих seams

**Приоритет**: P0  
**Зачем**: todo и task persistence уже есть, но они не сведены в one coherent runtime.

### Задачи

1. Построить `CodingTaskRuntime` поверх:
- `GraphTaskBoard`
- `TaskSessionStore`
- `todo` providers

2. Поддержать минимальный task lifecycle:
- create
- update
- list
- next-ready
- mark in_progress
- mark completed
- mark blocked
- unblock
- cancel / reopen если нужно текущему use case

3. Связать task state с resume/session state:
- task_id ↔ session params
- agent_id ↔ task_id mapping

4. Определить, что хранится где:
- lightweight checklist state
- task dependency state
- session binding state

5. Вывести task summary в runtime-facing shape для context assembly.

### Источники reuse

- reuse из `swarmline`: `GraphTaskBoard`, `TaskSessionStore`, `todo/tools.py`
- reference из `claw`: `task_runtime.py`, `plan_runtime.py`
- reference из `aura`: task/code-agent domain modelling

### Тесты (RED first)

- contract tests для runtime facade
- integration tests на dependency-aware ready tasks
- persistence tests на session/task resume
- regression tests на block/unblock/complete flows

### DoD

- [ ] Новый task runtime построен поверх существующих storage seams, без дублирования моделей
- [ ] Статусы и переходы покрыты tests-first
- [ ] Resume path сохраняет и восстанавливает task/session binding
- [ ] Есть integration test на dependency chain и `get_ready_tasks()`
- [ ] Нет app-specific business logic из `aura` внутри core runtime
- [ ] Нет новых толстых интерфейсов
- [ ] `ruff`, `mypy`, targeted `pytest` green

### Риски

- дублирование между todo model и graph task model
- слишком ранняя генерализация task API

### Mitigation

- keep API minimal
- сначала использовать existing graph semantics, потом расширять только если реально нужно

---

## Phase 3: PathService и безопасный execution layer

**Приоритет**: P1  
**Зачем**: coding-agent без canonical path layer и execution policy быстро становится хрупким и небезопасным.

### Задачи

1. Ввести canonical `PathService`:
- safe resolve
- workspace-root aware normalization
- task-root aware normalization при необходимости
- явные ошибки на invalid path

2. Укрепить execution policy:
- отделить file editing от command execution
- добавить command classification / deny rules / explicit unsafe-path handling

3. Определить minimal code-execution contract:
- input
- execution request
- output/result
- artifact/journal metadata, если это можно сделать без разрастания scope

4. Не ломая существующий sandbox layer, ввести ясную структуру, поверх которой можно строить coding-agent execution backend.

### Источники reuse

- `aura`: `PathService`, code-execution ports/models/policies, local sandbox patterns
- `claw`: `bash_security.py` как reference

### Тесты (RED first)

- path normalization tests
- traversal denial tests
- bash policy tests
- integration tests для safe execution через existing sandbox

### DoD

- [ ] Все runtime-facing file paths проходят через единый path layer
- [ ] traversal/invalid root cases fail-fast
- [ ] command execution policy покрыта негативными тестами
- [ ] execution и file-editing contracts разделены типами/портами
- [ ] нет silent fallback на небезопасные пути
- [ ] `ruff`, `mypy`, targeted `pytest` green

### Риски

- перетяжеление path abstraction
- пересечение ответственности с existing sandbox provider

### Mitigation

- PathService должен быть маленьким domain seam
- sandbox provider остаётся infra executor, а не заменяется

---

## Phase 4: File Mutation Queue и deterministic file writes

**Приоритет**: P1  
**Зачем**: конкурентные edits по одному файлу должны быть сериализованы.

### Задачи

1. Добавить `FileMutationCoordinator` / queue abstraction.
2. Сериализовать:
- `write`
- `edit`
- `multi_edit`

3. Разрешить параллельность для операций по разным файлам.
4. Нормализовать file identity:
- `realpath`
- canonical path

### Источники reuse

- reference из `pi-mono`: per-file mutation queue

### Тесты (RED first)

- concurrent writes same file
- concurrent edits same file
- concurrent writes different files
- path alias / symlink identity behaviour

### DoD

- [ ] Для одного файла операции сериализуются
- [ ] Для разных файлов операции не блокируют друг друга без причины
- [ ] Поведение покрыто concurrency tests
- [ ] Coordinator не протекает в domain слой без необходимости
- [ ] Нет race-induced flaky behaviour в tests
- [ ] `ruff`, `mypy`, targeted `pytest` green

### Риски

- nondeterministic tests
- скрытые deadlocks

### Mitigation

- минимальная queue abstraction
- явные timeouts и deterministic test harness

---

## Phase 5: Coding Context Compiler

**Приоритет**: P1  
**Зачем**: long-running coding tasks деградируют без task/workspace/summary-aware context.

### Задачи

1. Расширить `DefaultContextBuilder` или добавить рядом `CodingContextAssembler`, который собирает:
- active task summary
- ready/blocked task summary
- plan summary
- workspace summary
- recent file activity summary
- active skills summary
- recent search/tool summary
- compaction summary

2. Сохранить budget-aware assembly.
3. Сохранить существующий base builder path как backward-compatible.
4. Добавить structured notes/metadata для compaction/replay.

### Источники reuse

- reuse из `swarmline`: `context/builder.py`
- reference из `aura`: context compiler
- reference из `claw`: `agent_context.py`, `agent_prompting.py`, `compact.py`

### Тесты (RED first)

- budget tests
- truncation order tests
- task summary inclusion tests
- skill summary inclusion tests
- compaction/replay note tests

### DoD

- [ ] Новый context layer не ломает текущий builder path
- [ ] Coding-specific context sections собираются из typed inputs, а не ad-hoc string hacks
- [ ] Budget behaviour покрыто tests-first
- [ ] Task/workspace/session summaries реально появляются в system prompt/context pack
- [ ] Нет протягивания инфраструктурных деталей напрямую в domain contracts
- [ ] `ruff`, `mypy`, targeted `pytest` green

### Риски

- разрастание prompt assembly
- mixed responsibilities builder vs runtime

### Mitigation

- builder должен собирать packs, runtime только wiring
- sections выделять через typed input structs

---

## Phase 6: Wiring thin coding-agent profile

**Приоритет**: P2  
**Зачем**: собрать все предыдущие слои в один explicit режим.

### Задачи

1. Ввести explicit profile/config для coding-agent mode.
2. Подключить:
- unified tool pack
- coding task runtime
- path service
- execution policy
- context compiler
- mutation queue

3. Не ломать default secure posture библиотеки.
4. Сохранить backward compatibility для non-coding thin use cases.

### Тесты (RED first)

- profile wiring tests
- end-to-end thin coding-agent integration tests
- regression tests: default thin without coding profile behaves as before

### DoD

- [ ] Coding-agent profile включается явно
- [ ] Default secure-by-default path остаётся прежним
- [ ] End-to-end integration test проходит через task + read/write/edit + context assembly
- [ ] Backward compatibility path покрыт regression tests
- [ ] Документация profile/config создана или обновлена
- [ ] `ruff`, `mypy`, targeted `pytest` green

---

## Phase 7: Stabilization и release gate

**Приоритет**: P3

### Задачи

1. Прогнать targeted и broader verification:
- unit
- integration
- relevant e2e / workflow tests

2. Добавить docs:
- coding-agent profile overview
- configuration examples
- migration notes if aliases or naming changed

3. Проверить, что реализация соответствует плану и RULES.

### Финальный DoD

- [ ] Все фазовые DoD закрыты
- [ ] Все новые слои покрыты tests-first
- [ ] Repo-wide `ruff check src/ tests/` green
- [ ] Repo-wide `mypy src/swarmline/` green
- [ ] Targeted `pytest` по новым зонам green
- [ ] Если затронуты orchestration/runtime/session/context — прогнан broader regression pack
- [ ] Документация синхронизирована
- [ ] Нет placeholder'ов, временных флагов без явной необходимости, незакрытых stub paths
- [ ] Memory Bank обновлён только после фактической верификации

---

## Тестовая стратегия

### Unit

Фокус:
- contracts
- path normalization
- alias resolution
- mutation queue
- task transitions
- context section assembly

### Integration

Фокус:
- thin runtime + coding tools
- thin runtime + task runtime
- thin runtime + policy profile
- thin runtime + context assembly
- resume / session binding

### E2E / smoke

Фокус:
- representative coding-agent flow
- delegated subtask flow if profile uses subagents
- compatibility smoke для non-coding thin path

---

## Риски и решения

### R1. Scope explosion

Риск:
- coding-agent quickly turns into “rewrite half the runtime”

Mitigation:
- строго phase-by-phase
- reuse existing seams first
- no new runtime

### R2. Архитектурное размытие

Риск:
- task/path/context logic размажется по runtime и tools

Mitigation:
- contract-first
- explicit ownership per layer
- small interfaces only

### R3. Backward compatibility drift

Риск:
- thin aliases или старый non-coding path сломаются

Mitigation:
- compatibility tests
- profile opt-in
- no hard delete of aliases in первой версии

### R4. Безопасность execution path

Риск:
- new coding surface accidentally weakens secure defaults

Mitigation:
- separate coding policy profile
- default deny unchanged
- negative security tests mandatory

### R5. Контекст разрастётся и ухудшит качество

Риск:
- richer context compiler перегрузит model context

Mitigation:
- budget-aware assembly
- compaction
- section-level truncation tests

---

## Acceptance Gate

План считается выполненным только если одновременно верны все условия:

1. `thin` получает explicit coding-agent profile без нового runtime.
2. Stub `task/write_todos` пути заменены настоящими runtime-backed seams.
3. Task/todo/session/context layers работают согласованно.
4. Secure defaults не сломаны.
5. Все проверки зелёные:
- targeted tests
- relevant integration tests
- broader regression for runtime/session/context
- `ruff`
- `mypy`

---

## Порядок исполнения

Рекомендуемый порядок:

1. Phase 0
2. Phase 1
3. Phase 2
4. Phase 3
5. Phase 4
6. Phase 5
7. Phase 6
8. Phase 7

Допустимая параллельность:
- Phase 3 и Phase 4 можно partially parallel после фиксации контрактов из Phase 0
- docs писать только после стабилизации основного implementation slice

---

## Решение

**Рекомендация**: выполнять этот план как следующий feature tranche после стабилизации parity work, с отдельным minor release и без смешивания с несвязанными refactor/security инициативами.

Это соответствует `RULES.md`:
- contract-first
- TDD-first
- Clean Architecture
- low-risk slices
- fail-fast
- без преждевременных абстракций и без расширения scope
