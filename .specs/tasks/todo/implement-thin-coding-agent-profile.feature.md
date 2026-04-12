---
title: Implement Thin coding-agent profile
status: todo
created: 2026-04-12
source_report: /Users/fockus/Apps/swarmline/.memory-bank/reports/2026-04-12_analysis_thin-coding-agent-reuse-aura-claw-pi-mono.md
source_plan: /Users/fockus/Apps/swarmline/.memory-bank/plans/2026-04-12_feature_thin-coding-agent-profile.md
---

## Initial User Prompt

Сделать подробную спецификацию на основе репорта `2026-04-12_analysis_thin-coding-agent-reuse-aura-claw-pi-mono.md`
и плана `2026-04-12_feature_thin-coding-agent-profile.md`.

Нужна implementation-ready task/specification для развития `ThinRuntime` как coding-agent profile
в `swarmline`, с учётом reuse из `swarmline`, `aura`, `claw-code-agent`, `pi-mono`
и с соблюдением правил из `RULES.md`.

## Description

Нужно реализовать opt-in `coding-agent profile` поверх существующего `ThinRuntime`, не создавая новый runtime и не ломая secure-by-default поведение библиотеки вне coding-mode.

Профиль должен собрать уже существующие части `swarmline` в единый coding-agent engine:
- canonical coding tools для чтения, записи, редактирования, shell execution и поиска по коду;
- persistent task/todo runtime c resume-friendly состоянием;
- richer coding context assembly для длинных сессий;
- profile-aware policy, который явно включает coding tools только в специальном режиме;
- subagent inheritance, чтобы coding-profile консистентно распространялся на дочерние thin-сабагенты.

Решение должно опираться на:
- прямой reuse уже существующих модулей `swarmline`;
- seam-level reuse и адаптацию проверенных паттернов из `aura`;
- reference-only паттерны из `claw-code-agent` до отдельного подтверждения лицензии;
- UX-паттерны coding tools из `pi-mono`.

## Problem Statement

Сейчас `swarmline` уже содержит значительную часть нужного фундамента, но он не собран в cohesive coding-agent stack.

Наблюдаемые gaps:
- builtin file/shell/search tools существуют, но visible tool surface и executable tool surface не сведены в один canonical pack;
- thin builtin `write_todos` и `task` ведут себя как shim/stub, а не как настоящий persistent task runtime;
- secure default policy корректно запрещает dangerous tools по умолчанию, но нет profile-level механизма явно включить их в coding-mode;
- task board, todo provider, session-task binding и context builder уже есть, но не соединены в один runtime path;
- текущий context builder не собирает coding-specific slices: active task summary, task board summary, workspace summary, search summary, session summary, active skill/profile summary.

## Goals

1. Сделать `ThinRuntime` пригодным для coding-agent сценариев через opt-in profile, а не через новый runtime.
2. Свести canonical coding tool pack в единый visible+executable contract.
3. Подключить persistent task/todo runtime поверх уже существующих `GraphTaskBoard`, `TaskSessionStore`, `todo` providers.
4. Усилить context engineering для coding runs без замены всего существующего context builder.
5. Сохранить backwards compatibility для существующих thin flows вне coding-profile.
6. Оставить внешнее поведение secure-by-default: coding tools не становятся доступными без явного profile opt-in.

## Non-Goals

- новый runtime помимо `ThinRuntime`;
- wholesale port архитектуры `aura`;
- literal copy кода из `claw-code-agent` до явного подтверждения лицензии;
- новая CLI/UI продуктовая оболочка поверх `swarmline`;
- новые внешние зависимости;
- generic plugin framework "на будущее" под гипотетические coding-agent use cases;
- изменение публичного поведения non-coding thin runs.

## Scope

### In Scope

- opt-in coding profile configuration и runtime wiring;
- canonical coding tool pack;
- policy profile для coding tools;
- persistent task/todo adapters;
- coding context assembly;
- compatibility aliases и fail-fast semantics;
- subagent inheritance and workflow sync;
- targeted and broader regression coverage.

### Out of Scope

- app-specific orchestration из `aura`;
- remote worktree managers, hosted services, SaaS orchestration;
- новые web tools, browser tools или MCP ecosystems;
- redesign всего session framework;
- новые storage backends;
- изменение release/public packaging flow.

## Rules and Constraints

Реализация обязана соблюдать [RULES.md](/Users/fockus/Apps/swarmline/RULES.md):

- `Contract-First`: новый subsystem начинается с Protocol/dataclass/typed contract.
- `TDD-first`: сначала тесты, потом реализация. Исключения только для механических docs/rename изменений.
- `Clean Architecture`: `Infrastructure -> Application -> Domain`, без обратных импортов.
- `SOLID`: интерфейсы не шире 5 методов, composition вместо монолитных `if/else`.
- `DRY / KISS / YAGNI`: не дублировать существующие `todo`, `sandbox`, `task board`, `context builder`.
- `Fail-fast`: unsupported mode, alias drift, missing persistence binding, unsupported tool name или broken profile wiring должны падать явно.
- `No new deps`: использовать только уже существующие зависимости проекта.
- `No placeholders`: без `TODO`, `...`, stubbed production behavior без feature/profile gate.

## Source-of-Truth and Reuse Matrix

| Source | Reuse mode | Why it matters | What to reuse |
|---|---|---|---|
| `swarmline.tools.builtin` | direct code reuse | Уже содержит canonical file/shell/search executors | `bash`, `read`, `write`, `edit`, `multi_edit`, `ls`, `glob`, `grep` |
| `swarmline.todo.tools` | direct code reuse | Уже содержит provider-backed todo persistence | `todo_read`, `todo_write` |
| `swarmline.session.task_session_store` | direct code reuse | Уже хранит session-to-task binding | resume and task-session state |
| `swarmline.multi_agent.graph_task_board` | direct code reuse | Уже реализует lifecycle, dependencies, ready/blocked logic | task board backend |
| `swarmline.context.builder` | extension/reuse | Уже умеет layered budget-aware assembly | coding context extension seam |
| `aura domain/services/path_service.py` | adapt seam | Даёт canonical path normalization и root semantics | `PathService`-подобный seam |
| `aura domain/code_execution/*` | adapt seam | Даёт clean separation между file mutation и command execution | typed execution artifacts and policies |
| `aura application/components/context/compiler.py` | reference + partial adaptation | Даёт patterns stable prefix / saturation / compression | coding context compaction patterns |
| `aura application/components/context/skill_manager.py` | adapt pattern | Даёт controlled skill/profile summary assembly | skill/profile context integration |
| `claw-code-agent` | reference only | Сильные patterns для plan/task/runtime/context, но license не подтверждён | `task_runtime`, `plan_runtime`, `agent_context`, `compact`, `bash_security` patterns |
| `pi-mono/packages/coding-agent` | reference only | Даёт лучший UX для file tools и mutation serialization | file mutation queue, read truncation UX, continuation hints |

### Mandatory reuse decisions

- `claw-code-agent` не копируется буквально, пока license не подтверждён отдельно.
- canonical source of truth для coding tools: `src/swarmline/tools/builtin.py`.
- canonical source of truth для todo tools: `src/swarmline/todo/tools.py`.
- task runtime строится поверх `GraphTaskBoard + TaskSessionStore`, а не как новый engine.

## Architecture Overview

`coding-agent profile` должен быть реализован как composition layer поверх `ThinRuntime`.

Целевая схема:

1. `ThinRuntime` получает opt-in profile config.
2. Profile config подключает canonical coding tool pack.
3. Policy profile разрешает только явно объявленный набор tools для coding-mode.
4. Persistent adapters связывают:
   - task lifecycle;
   - todo persistence;
   - session-task binding.
5. Coding context assembler строит bounded context slices из task/session/workspace/search/skill/profile state.
6. Thin subagent path наследует тот же profile, policy и task context.

## Design Principles

1. Не новый runtime, а новый profile.
2. Один canonical tool pack, один canonical task runtime boundary.
3. Runtime state ownership должен быть единым и явным.
4. Весь compatibility слой должен быть thin adapter, а не второй implementation path.
5. Fail-fast при любых unsupported или ambiguous состояниях.
6. No-regression вне coding profile.

## Public and Internal API Seams

### Public seams

- `ThinRuntime` получает opt-in coding profile configuration seam.
- Пользовательский consumer может явно включить coding profile без изменения non-coding paths.
- Legacy alias names в coding mode остаются доступными только как compatibility surface.

### Internal seams

- `CodingTaskRuntime` Protocol
- `PathService` Protocol
- `CodingContextAssembler` Protocol
- `CodingProfile` / `CodingProfileConfig` typed dataclass
- internal `coding_toolpack` builder
- compatibility alias resolver

## Compatibility Contract

### Canonical tool names

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
- task-facing tools backed by persistent task runtime

### Legacy aliases that must map to canonical behavior in coding mode

- `read_file -> read`
- `write_file -> write`
- `edit_file -> edit`
- `execute -> bash`
- `write_todos -> todo_write` or explicit fail-fast if profile not active
- `task -> persistent task runtime command surface`

### Compatibility requirements

- Alias invocation must reach the same implementation and policy path as canonical name.
- Alias descriptions and schemas must stay semantically equivalent to canonical behavior.
- Outside coding profile aliases must not silently enable dangerous capabilities.
- If an alias cannot be supported with the same semantics, runtime must raise explicit configuration/runtime error.

## Task Lifecycle Contract

### Required statuses

- `pending`
- `ready`
- `in_progress`
- `blocked`
- `completed`
- `failed`
- `cancelled`

### Required operations

- create task
- list ready tasks
- mark in progress
- mark blocked with reason
- unblock task
- mark completed
- mark failed with reason
- cancel task
- resume task by persisted binding

### Required persistence properties

- task state survives restart/resume when backed by persistent provider;
- session-to-task binding survives restart/resume;
- todo state remains provider-backed and not downgraded to markdown shim;
- parent/child dependency semantics remain consistent with `GraphTaskBoard`.

## Coding Context Contract

### Required context inputs

- active task summary
- task board summary
- workspace summary
- recent search summary
- session summary
- skill/profile summary

### Required behavior

- each slice is bounded and budget-aware;
- slice omission must be deterministic and testable under budget pressure;
- context assembly must not exceed configured budget envelope;
- coding-specific context must only be added when coding profile is active;
- compaction path must preserve task continuity facts needed for resume.

## File Impact Split

### New files

- `src/swarmline/runtime/thin/coding_profile.py`
- `src/swarmline/runtime/thin/coding_toolpack.py`
- `src/swarmline/orchestration/coding_task_runtime.py`
- `src/swarmline/orchestration/task_context.py`
- optional `src/swarmline/context/coding_context_builder.py`
- optional `src/swarmline/policy/coding_tool_policy.py`

### Modified files

- `src/swarmline/runtime/thin/runtime.py`
- `src/swarmline/runtime/thin/builtin_tools.py`
- `src/swarmline/runtime/ports/thin.py`
- `src/swarmline/tools/builtin.py`
- `src/swarmline/todo/tools.py`
- `src/swarmline/session/task_session_store.py`
- `src/swarmline/multi_agent/graph_task_board.py`
- `src/swarmline/context/builder.py`
- `src/swarmline/policy/tool_policy.py`
- `src/swarmline/orchestration/thin_subagent.py`
- `src/swarmline/runtime/thin/subagent_tool.py`

### Adapter-wrapper preferred

- path normalization
- compatibility alias resolution
- context compaction helpers
- task/todo bridge layer

## High-Risk Integration Points and Mitigations

| Risk | Why risky | Mitigation |
|---|---|---|
| visible tools diverge from executable tools | модель видит tools, которых runtime не исполняет, или наоборот | один canonical builder и integration tests на visible+executable parity |
| task runtime дублирует `GraphTaskBoard` semantics | lifecycle drift и inconsistent statuses | использовать `GraphTaskBoard` как single backend, а не переписывать lifecycle |
| legacy aliases получают другую семантику | скрытый behavioral drift | contract tests alias-to-canonical parity |
| coding context ломает budget discipline | переполнение prompt и нестабильный resume | bounded slice tests и budget overflow tests |
| subagent path теряет profile/policy/context | дочерние агенты работают в другой semantic surface | inheritance integration tests на tools, policy и task context |
| coding mode ломает non-coding thin runs | регрессия всей библиотеки | explicit no-profile regression pack |

## Acceptance Criteria

1. `ThinRuntime` получает opt-in coding profile без создания нового runtime class hierarchy.
2. В coding profile модель видит ровно один canonical coding tool surface, совпадающий с executable tool surface.
3. `read/write/edit/bash/ls/glob/grep` приходят из общего builtin tool source, а не из параллельной thin-реализации.
4. `todo_read/todo_write` в coding profile используют provider-backed implementation, а не markdown shim.
5. Task operations в coding profile используют persistent task runtime semantics, а не noop/stub behavior.
6. Legacy aliases в coding profile либо маппятся на canonical implementations, либо fail-fast с явной ошибкой.
7. Default secure policy вне coding profile не изменяется и продолжает запрещать dangerous coding tools.
8. Coding profile policy разрешает только явно объявленный набор coding tools и не размывает default-deny baseline.
9. Task state и session-to-task binding переживают restart/resume в поддерживаемом persistent режиме.
10. Coding context включает task/session/workspace/search/skill-profile slices только в coding mode.
11. Coding context остаётся bounded и проходит budget discipline tests.
12. Subagent path наследует тот же coding profile, policy и task context, что и родительский thin run.
13. Unsupported alias, profile drift или missing runtime wiring приводят к явной ошибке, а не к silent fallback.
14. Non-coding thin runs проходят regression без изменения tool surface и behavior.
15. Реализация следует Contract-First и TDD-first, подтверждается порядком артефактов и test history.
16. В реализацию не добавлены новые runtime dependencies.
17. Все новые interfaces остаются в пределах `<= 5` методов.
18. Все DoD выполнены по шагам и по tranche в целом.

## Scenarios

### Scenario 1: Explicit coding profile

Пользователь включает `ThinRuntime` в coding mode и получает:
- canonical file/shell/search tools;
- task/todo tools;
- bounded coding context;
- explicit profile-aware policy.

### Scenario 2: Resume after interruption

Сессия падает или завершается, затем возобновляется:
- task binding восстанавливается;
- актуальный task status сохраняется;
- todo state сохраняется;
- coding context получает task/session continuity summary.

### Scenario 3: Legacy alias compatibility

Модель вызывает `read_file` или `execute`:
- alias резолвится в canonical implementation;
- policy path идентичен canonical name;
- event stream и result semantics совпадают.

### Scenario 4: Non-coding run remains unchanged

Пользователь запускает обычный `ThinRuntime` без coding profile:
- dangerous coding tools не становятся доступны;
- context shape не получает coding-specific slices;
- существующие thin tests не деградируют.

### Scenario 5: Subagent inheritance

Родительский thin coding-agent делегирует задачу thin-сабагенту:
- дочерний агент видит тот же coding tool surface;
- policy profile унаследован;
- task context synchronised;
- несовместимый inheritance path fail-fast.

## Implementation Summary Table

| Step | Name | Main output | Depends on |
|---|---|---|---|
| 1 | Public profile contract | typed contracts and contract tests | none |
| 2 | Task/runtime ownership boundary | single task runtime owner | 1 |
| 3 | Canonical coding tool pack | unified visible+executable tools | 1 |
| 4 | Coding policy profile | explicit allow policy for coding mode | 3 |
| 5 | Persistent task/todo adapters | task/todo/session persistence path | 2, 4 |
| 6 | Coding context assembly | bounded coding context slices | 5 |
| 7 | Legacy compatibility and fail-fast semantics | alias resolver and explicit errors | 3 |
| 8 | Subagent inheritance and workflow sync | profile-aware delegation | 2, 6, 7 |
| 9 | Hardening and regression closure | final stabilization and regressions | 1-8 |

## Detailed Implementation Steps

## Step 1. Public profile contract

### Goal

Зафиксировать public/internal contract spine до любой runtime wiring реализации.

### Scope

- typed profile config/dataclasses;
- protocol seams для task runtime, path service, context assembler;
- naming contract для canonical tools и legacy aliases.

### Required tests first

- contract tests для каждого нового Protocol/dataclass;
- negative tests на invalid profile configuration;
- tests на interface width and typing expectations там, где это зафиксировано проектом.

### DoD

- все новые contracts оформлены через Protocol/dataclass;
- каждый interface содержит не более 5 методов;
- canonical names и alias mapping зафиксированы тестами;
- до merge есть только contracts + tests, без runtime behavior drift.

## Step 2. Task/runtime ownership boundary

### Goal

Сделать один явный owner для coding-task runtime semantics.

### Scope

- task runtime facade;
- task state orchestration boundary;
- связь с `GraphTaskBoard` и `TaskSessionStore` без lifecycle duplication.

### Required tests first

- contract tests для create/resume/update task lifecycle;
- integration tests на ready/blocked/in_progress/completed transitions;
- negative tests на invalid ownership or status transitions.

### DoD

- один runtime owner управляет task state;
- `GraphTaskBoard` используется как backend, а не переизобретён;
- session-task binding интегрирован через typed boundary;
- status transitions observable and tested.

## Step 3. Canonical coding tool pack

### Goal

Свести visible и executable coding tools в один canonical pack.

### Scope

- canonical builder для coding tools;
- thin tool exposure через общий source of truth;
- замена thin-specific shims на canonical implementations.

### Required tests first

- parity tests visible vs executable tools;
- tool schema tests на canonical names;
- integration tests на read/write/edit/bash/ls/glob/grep/todo presence в coding mode.

### DoD

- одна canonical сборка tools используется и для описания, и для execution;
- thin-specific stubbed todo/task behavior удалён из active coding path;
- non-coding path не меняется.

## Step 4. Coding policy profile

### Goal

Добавить explicit allow-profile для coding tools без изменения default-deny baseline.

### Scope

- policy profile registration;
- policy selection by profile;
- tests на allow/deny matrix.

### Required tests first

- tests на default deny вне coding profile;
- tests на allow-list внутри coding profile;
- negative tests на unknown profile / tool leakage.

### DoD

- default policy вне coding mode не изменена;
- coding mode включает только объявленный набор tools;
- unsupported profile selection fail-fast.

## Step 5. Persistent task/todo adapters

### Goal

Собрать один persistence path для task/todo/session semantics.

### Scope

- provider-backed todo wiring;
- task/session persistence adapters;
- typed snapshots для resume.

### Required tests first

- integration tests на restart/resume;
- persistence tests на task status and todo state;
- negative tests на missing provider/binding.

### DoD

- task state и todo state переживают restart/resume в поддерживаемых режимах;
- markdown shim больше не является coding-profile persistence path;
- missing persistence wiring fail-fast.

## Step 6. Coding context assembly

### Goal

Добавить bounded coding-specific context slices поверх существующего builder.

### Scope

- active task summary;
- task board summary;
- workspace summary;
- recent search summary;
- session summary;
- skill/profile summary;
- optional compaction hooks.

### Required tests first

- tests на presence/absence slices по profile;
- tests на budget caps и deterministic omission;
- tests на continuity facts after compaction.

### DoD

- все обязательные slices observable и ограничены budget;
- coding slices появляются только в coding mode;
- budget overflow приводит к deterministic truncation behavior, покрытому тестами.

## Step 7. Legacy compatibility and fail-fast semantics

### Goal

Сохранить совместимость с legacy thin naming без второго implementation path.

### Scope

- alias resolver;
- alias-to-canonical parity;
- explicit failure modes.

### Required tests first

- alias mapping tests;
- parity tests canonical vs alias behavior;
- negative tests на unsupported alias или broken resolver wiring.

### DoD

- aliases достигают тех же implementations, policy и event semantics;
- unsupported alias paths падают с явной ошибкой;
- silent fallback отсутствует.

## Step 8. Subagent inheritance and workflow sync

### Goal

Обеспечить наследование coding profile на дочерних thin-сабагентах.

### Scope

- profile inheritance;
- policy inheritance;
- task context propagation;
- sync with delegation runtime path.

### Required tests first

- integration tests parent -> child inheritance;
- tests на task context propagation;
- negative tests на incompatible inheritance state.

### DoD

- child thin subagent inherits profile, tools and policy from parent;
- task context sync observable in child context;
- inheritance mismatch fail-fast.

## Step 9. Hardening and regression closure

### Goal

Закрыть integration debt и подтвердить отсутствие регрессий.

### Scope

- targeted fixes from failures;
- final lint/type/test closure;
- broader regression pack.

### Required tests first

- regression tests на баги, найденные в предыдущих шагах;
- non-coding no-regression tests;
- final end-to-end integration pack по critical coding flows.

### DoD

- все targeted tests green;
- broader regression green по затронутым контурам;
- `ruff check` и `mypy` green на итоговом изменённом срезе;
- нет известных открытых behavior gaps внутри scope.

## Parallelization Strategy

Безопасная схема исполнения: `contract freeze -> isolated slices -> controlled merge`.

Основные правила:
- `Step 1` строго последовательный и является contract gate для всех остальных шагов.
- После freeze возможны только те параллельные ветки, которые не делят write ownership и не меняют один semantic surface.
- High-conflict файлы имеют одного owner на волну.
- Любое изменение frozen contract после merge point требует возврата на coordinator review.

## Execution Waves

1. `Wave 0`: Contract Spine (`Step 1`)
2. `Wave 1`: параллельно
   - Task Runtime Boundary (`Step 2`)
   - Canonical Coding Tool Pack (`Step 3`)
3. `Wave 2`: параллельно
   - Coding Policy Profile (`Step 4`)
   - Compatibility and Fail-Fast Wiring (`Step 7`)
4. `Wave 3`: Persistent Task/Todo Adapters (`Step 5`)
5. `Wave 4`: Coding Context Assembly (`Step 6`)
6. `Wave 5`: Subagent Workflow Sync (`Step 8`)
7. `Wave 6`: Hardening and Regression Closure (`Step 9`)

## Wave Execution Contracts

### High-conflict file ownership map

- `src/swarmline/runtime/thin/runtime.py`: один owner на волну; в `Wave 2`, `Wave 5` и `Wave 6` этот файл не может редактироваться параллельно с другим пакетом.
- `src/swarmline/runtime/ports/thin.py`: owner только у tool-surface пакета; если нужен runtime-level compatibility touch, он проходит только после merge `Wave 1`.
- `src/swarmline/runtime/thin/prompts.py`: owner у context/runtime merge-owner; изменения запрещены параллельно с schema/tool-description rewiring.
- `src/swarmline/orchestration/**`: owner у task-runtime/subagent веток; tool/policy пакеты туда не заходят без coordinator approval.
- `src/swarmline/policy/**`: owner только у policy wave; compatibility/runtime wave не меняет policy files.

### Wave 0 Contract Spine

- Inputs: analysis report, feature plan, `RULES.md`, frozen naming decisions.
- Owner: coordinator / contract-owner.
- Write scope: только contracts, typed dataclasses, contract tests, naming/alias map.
- Tests first: contract tests для profile/task/context/path seams и invalid configuration tests.
- Exit criteria:
  - canonical tool names зафиксированы;
  - alias map зафиксирован;
  - ownership zones зафиксированы;
  - contracts/tests green.
- Merge gate:
  - downstream waves запрещены, пока contracts не смёржены;
  - любой спор по naming/ownership возвращает волну в review.
- Fail-fast stop condition:
  - обнаружен public contract drift;
  - interface > 5 методов;
  - dependency direction нарушен.

### Wave 1A Task Runtime Boundary

- Inputs: merged `Wave 0` contracts.
- Owner: task-runtime package owner.
- Write scope: `src/swarmline/orchestration/**`, `src/swarmline/session/**`, task runtime adapters/tests.
- Tests first: lifecycle integration tests, invalid transition tests, session-task binding tests.
- Exit criteria:
  - один runtime owner для task state;
  - transitions observable and tested;
  - `GraphTaskBoard` остаётся backend.
- Merge gate:
  - пакет не меняет tool schemas/tool descriptions;
  - пакет не заходит в `tools/builtin.py` и `runtime/thin/builtin_tools.py`.
- Fail-fast stop condition:
  - найден второй owner task lifecycle;
  - package требует правки tool surface.

### Wave 1B Canonical Coding Tool Pack

- Inputs: merged `Wave 0` contracts.
- Owner: tool-surface package owner.
- Write scope: `src/swarmline/tools/builtin.py`, `src/swarmline/runtime/thin/builtin_tools.py`, `src/swarmline/runtime/ports/thin.py`, optional `coding_toolpack.py`, tool tests.
- Tests first: visible-vs-executable parity, canonical tool presence, schema consistency, non-coding absence tests.
- Exit criteria:
  - один canonical tool builder;
  - visible surface совпадает с executable surface;
  - shim/stub todo/task path не участвует в active coding flow.
- Merge gate:
  - пакет не трогает orchestration/session ownership zone;
  - canonical names не переопределяются после `Wave 0`.
- Fail-fast stop condition:
  - visible/executable parity не достигнута;
  - появляется вторая реализация тех же инструментов.

### Wave 2A Coding Policy Profile

- Inputs: merged `Wave 1`, canonical tool pack frozen.
- Owner: policy package owner.
- Write scope: `src/swarmline/policy/**`, policy registration/wiring tests.
- Tests first: allow/deny matrix, unknown profile, tool leakage tests.
- Exit criteria:
  - default-deny вне coding profile сохранён;
  - coding profile разрешает только declared tools.
- Merge gate:
  - пакет не меняет prompt/schema/runtime compatibility wiring;
  - tool names не меняются.
- Fail-fast stop condition:
  - policy leakage между profiles;
  - dangerous tool доступен без explicit profile opt-in.

### Wave 2B Compatibility and Fail-Fast Wiring

- Inputs: merged `Wave 1`, canonical tool pack frozen.
- Owner: runtime compatibility owner.
- Write scope: `src/swarmline/runtime/thin/coding_profile.py`, `src/swarmline/runtime/thin/runtime.py`, `src/swarmline/runtime/thin/prompts.py`, compatibility tests.
- Tests first: alias mapping tests, parity tests, unsupported alias fail-fast tests.
- Exit criteria:
  - aliases проходят в canonical implementations;
  - silent fallback отсутствует;
  - runtime errors explicit and typed enough for tests.
- Merge gate:
  - пакет не меняет `policy/**`;
  - prompt/runtime wiring не меняет canonical schema names.
- Fail-fast stop condition:
  - compatibility слой превращается во вторую реализацию;
  - alias semantics расходится с canonical path.

### Wave 3 Persistent Task/Todo Adapters

- Inputs: merged `Wave 2` plus stable task/runtime and policy boundaries.
- Owner: persistence integration owner.
- Write scope: `src/swarmline/todo/**`, `src/swarmline/session/task_session_store.py`, task/todo bridge adapters, persistence tests.
- Tests first: restart/resume tests, todo persistence tests, snapshot roundtrip tests, missing binding/provider tests.
- Exit criteria:
  - task/todo/session path resume-friendly;
  - markdown shim не используется как production persistence path.
- Merge gate:
  - провайдера и binding semantics зафиксированы;
  - restart/resume green before next wave.
- Fail-fast stop condition:
  - missing provider/binding silently degrades;
  - task/todo state не восстанавливается roundtrip.

### Wave 4 Coding Context Assembly

- Inputs: merged `Wave 3` persistence semantics.
- Owner: context assembly owner.
- Write scope: `src/swarmline/context/**`, optional `coding_context_builder.py`, bounded context tests.
- Tests first: slice presence/absence tests, budget cap tests, deterministic omission tests, compaction continuity tests.
- Exit criteria:
  - required slices собраны;
  - budget discipline доказана;
  - coding slices отсутствуют вне coding mode.
- Merge gate:
  - context pack examples и budget tests green;
  - prompt/context wiring reviewed by coordinator.
- Fail-fast stop condition:
  - nondeterministic omission;
  - context leaks into non-coding mode.

### Wave 5 Subagent Workflow Sync

- Inputs: merged `Wave 4` context contract and `Wave 2B` compatibility contract.
- Owner: subagent/runtime sync owner.
- Write scope: `src/swarmline/orchestration/thin_subagent.py`, `src/swarmline/runtime/thin/subagent_tool.py`, minimal coordinated changes in `runtime/thin/runtime.py`, subagent integration tests.
- Tests first: parent-child inheritance tests, task context propagation tests, incompatible inheritance tests.
- Exit criteria:
  - child inherits profile/tools/policy/context;
  - incompatible state fail-fast.
- Merge gate:
  - parent-child semantic surface parity proven;
  - no regression in non-coding subagent flow.
- Fail-fast stop condition:
  - child loses profile or task continuity facts;
  - inheritance path silently degrades to generic thin mode.

### Wave 6 Hardening and Regression Closure

- Inputs: merged `Wave 5` baseline.
- Owner: closure owner.
- Write scope: `tests/**`, narrow production fixes in already-owned zones, validation artifacts.
- Tests first: regression tests for discovered bugs, non-coding no-regression tests, critical-path integration tests.
- Exit criteria:
  - all targeted packs green;
  - `ruff check src/ tests/` green;
  - `mypy src/swarmline/` green;
  - broader regression green.
- Merge gate:
  - final tranche judge verdict is `PASS`;
  - `spec vs code vs tests vs DoD` reconciled.
- Fail-fast stop condition:
  - any broader regression fails;
  - unresolved behavior gap remains in accepted scope.

## Merge Points and Coordination Rules

- `Merge Point A`: после `Step 1`, фиксируются contracts, canonical names, alias map, ownership zones.
- `Merge Point B`: после `Wave 1`, coordinator проверяет отсутствие пересечения между task ownership и tool surface.
- `Merge Point C`: после `Wave 2`, фиксируются policy semantics и compatibility/fail-fast contract.
- `Merge Point D`: после `Step 5`, только после этого допускается финальная coding context assembly.
- `Merge Point E`: после `Step 6` и `Step 7`, только после этого стартует subagent sync.
- `Merge Point F`: перед `Step 9`, общий baseline: targeted tests green, затем broader regression.

### Anti-parallelization constraints

- нельзя параллелить `Step 1` ни с чем;
- нельзя одновременно трогать `runtime/thin/runtime.py` из двух пакетов;
- нельзя одновременно трогать `runtime/ports/thin.py` из `Step 3` и `Step 7`;
- нельзя параллелить `Step 4` и `Step 5`;
- нельзя параллелить `Step 6` и `Step 8`;
- нельзя запускать `Step 9` до финального merge `Step 8`.
- нельзя считать волну завершённой без её `Tests first` и `Exit criteria`.
- нельзя запускать downstream wave от локального snapshot; только от последнего merged baseline.

## Verification Strategy

Verification строится по принципу `contracts first -> targeted tests -> integration proofs -> broader regression -> LLM-as-judge audit`.

Обязательные правила tranche-level verification:

1. Каждый шаг начинается с `Required Tests First`; реализация без этих тестов считается незавершённой.
2. Каждый шаг закрывается `Targeted Verification` до перехода к следующему merge point.
3. `Broader Regression` запускается только при наступлении явно указанных trigger-условий.
4. Каждое решение по шагу должно иметь observable evidence: тесты, статические проверки, артефакты логов или diff ссылку на контракт.
5. LLM-as-Judge используется не вместо тестов, а как дополнительная проверка:
   - сохранён ли architectural intent;
   - не нарушен ли `RULES.md`;
   - не появился ли скрытый semantic drift.
6. `No-regression outside coding profile` проверяется отдельно и обязательно, даже если все coding tests зелёные.
7. Перед финальным закрытием tranche должны быть зелёными:
   - targeted tests по всем 9 шагам;
   - required integration packs;
   - `ruff check src/ tests/`;
   - `mypy src/swarmline/`.

## Step 1 Verification

### Verification Goal

Доказать, что contract spine зафиксирован до runtime wiring и не нарушает `Contract-First`, `ISP`, `Clean Architecture`.

### Required Tests First

- contract tests для `CodingProfileConfig` и всех новых Protocol/dataclass seams;
- tests на canonical tool names и alias map;
- tests на invalid profile configuration и unsupported profile mode.

### Targeted Verification

- запуск contract test files, затрагивающих новые contracts;
- проверка отсутствия imports из infrastructure в application/domain seams;
- `ruff check` и `mypy` по новым contract-файлам.

### Broader Regression Trigger

Запускать broader regression, если:
- изменён существующий public type/export;
- изменены shared protocol files;
- изменены runtime factory signatures.

### LLM-as-Judge Questions

- Все ли новые seams действительно contract-level, а не скрытая implementation logic?
- Не превышает ли какой-либо interface лимит `<= 5` методов?
- Сохранён ли direction dependency `Infrastructure -> Application -> Domain`?
- Зафиксированы ли canonical names и aliases без двусмысленности?

### Evidence Required to Mark Done

- список новых Protocol/dataclass files;
- зелёные contract tests;
- зелёные `ruff` и `mypy` на изменённом contract slice;
- diff/ссылка на documented canonical names и alias map.

## Step 2 Verification

### Verification Goal

Доказать, что task runtime имеет одного owner и не дублирует lifecycle semantics `GraphTaskBoard`.

### Required Tests First

- integration tests на create/ready/in_progress/blocked/completed/failed/cancelled transitions;
- tests на invalid status transition;
- tests на session-to-task binding and resume.

### Targeted Verification

- targeted pytest pack для orchestration/session/task runtime;
- локальная проверка, что task transitions проходят через один runtime facade;
- mypy/ruff по orchestration/session slice.

### Broader Regression Trigger

Запускать broader regression, если:
- изменены общие task board semantics;
- изменены session manager / session persistence paths;
- изменены reusable protocols task lifecycle.

### LLM-as-Judge Questions

- Есть ли один явный owner task runtime state?
- Не появилась ли параллельная lifecycle логика в thin runtime или adapters?
- Совпадает ли lifecycle contract со статусами, зафиксированными в спецификации?
- Остался ли `GraphTaskBoard` backend, а не стал ли он обёрткой над новым engine?

### Evidence Required to Mark Done

- зелёные lifecycle integration tests;
- тест/лог, подтверждающий resume через persisted binding;
- список touched files с одним ownership boundary;
- зелёные `ruff` и `mypy` на slice.

## Step 3 Verification

### Verification Goal

Доказать, что coding tool surface стал canonical и совпадает между visible и executable представлением.

### Required Tests First

- tests на visible vs executable parity;
- tests на canonical tool presence в coding profile;
- negative tests на отсутствие этих tools вне coding profile;
- tests на schema consistency для tool descriptions/inputs.

### Targeted Verification

- targeted pytest pack для `tools/builtin`, `runtime/thin/builtin_tools`, `runtime/ports/thin`;
- smoke integration run, где thin coding profile реально вызывает `read`, `write`, `grep`, `bash`;
- проверка, что `todo`-path больше не идёт через markdown shim.

### Broader Regression Trigger

Запускать broader regression, если:
- изменены shared builtin tool factories;
- изменён tool registry / active_tools builder;
- изменены event/result semantics tool execution.

### LLM-as-Judge Questions

- Есть ли ровно один canonical source of truth для coding tools?
- Совпадает ли tool surface, который видит модель, с реально исполняемым surface?
- Удалены ли shim/stub paths из active coding flow?
- Не появилась ли вторая реализация тех же инструментов под alias именами?

### Evidence Required to Mark Done

- зелёные parity tests visible vs executable;
- лог/smoke output реального tool invocation через thin coding profile;
- доказательство provider-backed todo path;
- зелёные `ruff` и `mypy` на tool slice.

## Step 4 Verification

### Verification Goal

Доказать, что coding policy profile включает только нужные coding tools и не ломает default-deny baseline.

### Required Tests First

- tests на deny dangerous tools вне coding profile;
- tests на allow-list внутри coding profile;
- tests на unknown profile selection;
- tests на tool leakage между profiles.

### Targeted Verification

- targeted pytest pack по `policy/**` и thin policy wiring;
- matrix check: non-coding profile vs coding profile tool permissions;
- static verification затронутых policy registration paths.

### Broader Regression Trigger

Запускать broader regression, если:
- изменена общая `DefaultToolPolicy`;
- изменены shared policy hooks или tool executor pipeline;
- изменён bootstrap/runtime factory policy wiring.

### LLM-as-Judge Questions

- Осталась ли default security posture неизменной вне coding profile?
- Разрешает ли coding profile только явно объявленный набор tools?
- Есть ли хоть один путь, где dangerous tool становится доступен без явного opt-in?
- Все ли unsupported profiles падают явно?

### Evidence Required to Mark Done

- зелёная allow/deny matrix;
- зелёные negative tests на leakage/unknown profile;
- diff policy registration и selection path;
- зелёные `ruff` и `mypy` на policy slice.

## Step 5 Verification

### Verification Goal

Доказать, что task/todo/session persistence работает как один связанный resume-friendly path.

### Required Tests First

- integration tests на restart/resume task state;
- integration tests на сохранение и восстановление todo state;
- tests на typed snapshot roundtrip;
- negative tests на missing provider и missing binding.

### Targeted Verification

- targeted pytest pack по `todo/**`, `session/task_session_store.py`, task adapters;
- smoke сценарий: создать task, записать todo, прервать run, восстановить run, проверить continuity;
- roundtrip verification persisted snapshot artifacts.

### Broader Regression Trigger

Запускать broader regression, если:
- изменены shared todo providers;
- изменены session persistence semantics;
- затронуты resume/load/save пути в session layer.

### LLM-as-Judge Questions

- Существует ли единый persistence path для task/todo/session?
- Удалён ли markdown shim из production coding path?
- Resume действительно восстанавливает состояние, а не только metadata shell?
- Fail-fast ли поведение при missing provider/binding?

### Evidence Required to Mark Done

- зелёные restart/resume integration tests;
- лог/артефакт snapshot roundtrip;
- подтверждение provider-backed todo state;
- зелёные `ruff` и `mypy` на persistence slice.

## Step 6 Verification

### Verification Goal

Доказать, что coding context assembly добавляет обязательные slices, остаётся bounded и не ломает budget discipline.

### Required Tests First

- tests на presence/absence каждого required slice;
- tests на budget cap и deterministic truncation;
- tests на compaction preserving continuity facts;
- tests на non-coding profile without coding slices.

### Targeted Verification

- targeted pytest pack по `context/**` и thin prompt/context wiring;
- fixture-based verification состава context pack при coding profile on/off;
- budget stress tests с малыми лимитами.

### Broader Regression Trigger

Запускать broader regression, если:
- изменён общий `DefaultContextBuilder`;
- изменены prompt assembly semantics;
- изменены session summary или history compaction paths.

### LLM-as-Judge Questions

- Все ли обязательные coding-context slices реально присутствуют и проверяются по отдельности?
- Остаётся ли сборка контекста budget-aware и deterministic под давлением лимита?
- Сохраняются ли continuity facts, нужные для resume?
- Не просачиваются ли coding slices в non-coding mode?

### Evidence Required to Mark Done

- зелёные slice presence/absence tests;
- зелёные budget discipline tests;
- пример assembled context для coding profile и non-coding profile;
- зелёные `ruff` и `mypy` на context slice.

## Step 7 Verification

### Verification Goal

Доказать, что legacy aliases совместимы с canonical behavior и любые unsupported cases fail-fast.

### Required Tests First

- alias-to-canonical mapping tests;
- parity tests на tool result semantics, policy path и error shape;
- negative tests на unsupported alias и broken resolver state.

### Targeted Verification

- targeted pytest pack для compatibility resolver и runtime wiring;
- smoke run через legacy names (`read_file`, `write_file`, `execute`);
- explicit check на отсутствие silent fallback.

### Broader Regression Trigger

Запускать broader regression, если:
- изменены shared tool names в prompts/schemas;
- изменён runtime-level tool dispatch;
- изменён error normalization path.

### LLM-as-Judge Questions

- Все ли legacy aliases достигают того же implementation path, что canonical names?
- Совпадают ли policy checks и error semantics?
- Есть ли хоть один fallback, который маскирует unsupported alias?
- Не превращается ли compatibility layer во вторую реализацию?

### Evidence Required to Mark Done

- зелёные alias parity tests;
- smoke output по legacy names;
- negative test outputs на fail-fast behavior;
- зелёные `ruff` и `mypy` на compatibility slice.

## Step 8 Verification

### Verification Goal

Доказать, что thin subagents наследуют profile, policy и task context без semantic drift.

### Required Tests First

- integration tests parent-to-child inheritance;
- tests на task context propagation;
- tests на inherited tool visibility and execution;
- negative tests на incompatible child configuration.

### Targeted Verification

- targeted pytest pack по thin subagent/runtime inheritance path;
- smoke delegation scenario с parent coding-agent -> child coding-agent;
- assertion на совпадение tool surface и policy surface у parent/child.

### Broader Regression Trigger

Запускать broader regression, если:
- изменён общий subagent tool/runtime wiring;
- затронуты delegation contracts;
- изменён context inheritance path.

### LLM-as-Judge Questions

- Наследует ли child тот же profile, tools и policy, что и parent?
- Пробрасывается ли task context без потери ключевых continuity facts?
- Есть ли mismatch paths, которые должны fail-fast, но сейчас молча деградируют?
- Не ломает ли inheritance existing non-coding subagent behavior?

### Evidence Required to Mark Done

- зелёные parent/child integration tests;
- лог/smoke артефакт delegation flow;
- сравнение visible/executable tools для parent и child;
- зелёные `ruff` и `mypy` на subagent slice.

## Step 9 Verification

### Verification Goal

Доказать, что tranche стабилен и не внёс регрессии в non-coding thin behavior.

### Required Tests First

- regression tests на все найденные баги из Steps 1-8;
- no-regression tests для thin without coding profile;
- final critical-path integration tests по coding profile.

### Targeted Verification

- запуск всех targeted packs по шагам 1-8;
- `ruff check src/ tests/`;
- `mypy src/swarmline/`;
- финальный targeted integration pack для coding profile critical flows.

### Broader Regression Trigger

Всегда запускать broader regression в конце tranche, если выполнен хотя бы один из пунктов:
- менялись runtime, policy, session, context или subagent paths;
- менялись shared builtin tools;
- менялись exports/public configs.

### LLM-as-Judge Questions

- Закрыт ли tranche без открытых semantic gaps внутри scope?
- Доказано ли отсутствие regression вне coding profile?
- Сохранился ли architectural intent: profile, а не новый runtime?
- Нет ли скрытых нарушений `RULES.md`: no new deps, fail-fast, TDD-first, clean boundaries?

### Evidence Required to Mark Done

- полный список зелёных targeted test packs;
- зелёные `ruff check src/ tests/`;
- зелёный `mypy src/swarmline/`;
- зелёный broader regression pack;
- финальная judge-оценка tranche с pass verdict.

## Cross-Cutting Verification Matrix

| Theme | What must be proven | Required evidence |
|---|---|---|
| compatibility | canonical names и aliases ведут себя одинаково в coding mode | alias parity tests, smoke on legacy names, identical policy/error semantics |
| context budget discipline | coding context bounded, deterministic under pressure | budget cap tests, deterministic truncation tests, assembled context examples |
| task/todo persistence | task status, todos и session binding переживают restart/resume | restart/resume integration tests, snapshot roundtrip evidence, provider-backed persistence proof |
| subagent inheritance | parent and child share same coding semantic surface | parent/child integration tests, tool surface comparison, task context propagation logs |
| fail-fast behavior | unsupported profile/alias/binding/path does not silently degrade | negative tests with explicit exception shape, logs showing no fallback |
| no-regression outside coding profile | default thin behavior and security posture unchanged | non-coding thin regression pack, deny-policy tests, non-coding context absence tests |

## Final Tranche Acceptance Verification

### Order of execution

1. Запустить все `Required Tests First` для текущего шага перед кодом.
2. После реализации каждого шага выполнить его `Targeted Verification`.
3. На каждом merge point выполнить scoped LLM-as-Judge review по вопросам для соответствующих шагов.
4. После завершения `Step 8` выполнить объединённый critical-path integration pack:
   - coding profile tool usage
   - task/todo persistence and resume
   - legacy aliases
   - subagent inheritance
   - non-coding thin unchanged
5. Выполнить `ruff check src/ tests/`.
6. Выполнить `mypy src/swarmline/`.
7. Выполнить broader regression по thin/runtime/policy/session/context/subagent контурам.
8. Выполнить финальный tranche-level LLM-as-Judge pass.
9. Сверить `spec vs code vs tests vs DoD`.
10. Только после этого пометить tranche как implementation-ready/complete.

### Final acceptance gate

Tranche принимается только если одновременно выполнены все условия:

- все 9 шагов имеют закрытые `Evidence Required to Mark Done`;
- все acceptance criteria доказаны тестами, логами или статическими проверками;
- coding profile работает end-to-end по critical-path сценарию;
- default thin path без coding profile не изменён по поведению и security posture;
- нет silent fallback в compatibility/persistence/inheritance paths;
- `ruff` и `mypy` зелёные;
- broader regression зелёный;
- финальный judge verdict = `PASS`.

## Final Definition of Done

- есть implementation-ready feature spec, достаточный для execution без архитектурных догадок;
- зафиксированы reuse boundaries: direct reuse, seam adaptation, reference-only;
- зафиксирован compatibility contract;
- зафиксированы task lifecycle и coding context contracts;
- зафиксированы file ownership zones и execution waves;
- зафиксирована verification strategy для каждого шага и для tranche в целом;
- спецификация согласована с `RULES.md`, analysis report и feature plan.
