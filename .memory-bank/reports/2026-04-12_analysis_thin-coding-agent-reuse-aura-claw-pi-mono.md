# Анализ переиспользования для Thin coding-agent: swarmline vs aura vs claw-code-agent vs pi-mono

**Дата**: 2026-04-12  
**Контекст**: текущий фокус `ThinRuntime Claude Code Parity` + запрос на развитие `swarmline` как engine для coding agents  
**Источники**:
- локальный аудит `swarmline` / `thin`
- локальный аудит `aura` (`/Users/fockus/Apps/aura`)
- аудит `claw-code-agent` (`https://github.com/HarnessLab/claw-code-agent`, локальный shallow clone)
- аудит `pi-mono/packages/coding-agent` (`https://github.com/badlogic/pi-mono`)
- параллельные сабагенты: `Feynman`, `Lorentz`, `Laplace`

---

## Executive Summary

Главный вывод: `swarmline` уже содержит значительную часть фундамента для coding-agent, но он разложен по нескольким слоям и пока не собран в единый `coding-agent mode`.

Самый высокий ROI дадут не новые абстракции “с нуля”, а сборка уже существующих возможностей в cohesive stack:

1. **Tool surface**: единый first-class pack `read/write/edit/bash/ls/glob/grep + todo/task`
2. **Task runtime**: persistent task state, dependencies, block/unblock, resume, next action
3. **Context assembly**: richer runtime context, compaction, task/session/search/skill summaries

Второй важный вывод: `aura` безопасна как источник literal code reuse (MIT указан в `README.md`), а `claw-code-agent` сейчас лучше использовать как архитектурный reference, а не как source для прямого копирования, потому что в локально проверенном clone не найден явный `LICENSE`/`COPYING`/`NOTICE`.

---

## Что уже есть в swarmline

### 1. Базовый coding-toolchain уже существует

В `swarmline.tools.builtin.create_sandbox_tools()` уже реализованы:
- `bash`
- `read`
- `write`
- `edit`
- `multi_edit`
- `ls`
- `glob`
- `grep`

Файл: `src/swarmline/tools/builtin.py`

Это означает, что базовый file/shell/search слой для coding-agent **уже написан** и не требует переписывания.

### 2. ThinRuntime уже умеет работать с builtin executors

`ThinRuntime.__init__()` подмешивает sandbox builtins в `merged_local_tools`.

Файл: `src/swarmline/runtime/thin/runtime.py`

Следствие: runtime уже может **исполнять** builtin tools.

### 3. Отдельный todo-слой уже реализован

В `src/swarmline/todo/tools.py` есть полноценные:
- `todo_read`
- `todo_write`

С поддержкой provider abstraction (`InMemory`, `FS`, `DB`).

Следствие: в репозитории уже есть нормальная модель todo persistence, и её не нужно проектировать заново.

### 4. Уже есть task/session persistence

В `src/swarmline/session/task_session_store.py` уже реализован binding session state к `(agent_id, task_id)`.

Следствие: resume task-oriented execution уже partially solved.

### 5. Уже есть graph task board

В `src/swarmline/protocols/graph_task.py` и `src/swarmline/multi_agent/graph_task_board.py` уже есть:
- create / checkout / complete
- get_ready_tasks()
- get_blocked_by()
- block / unblock
- cancel
- parent propagation

Следствие: большая часть task lifecycle infrastructure уже есть, просто она пока не подключена как coding-agent-facing task runtime.

### 6. Уже есть context builder

`src/swarmline/context/builder.py` уже умеет layered, budget-aware prompt assembly.

Следствие: контекстный слой не надо заменять целиком; его надо усиливать.

---

## Главные реальные gaps в swarmline

### Gap 1. thin builtin tools не сведены в полноценный coding-agent surface

В `src/swarmline/runtime/thin/builtin_tools.py`:
- `write_todos` сейчас пишет `.todos.md`
- `task` сейчас фактически noop/stub

То есть runtime предлагает surface “как будто task/todo есть”, но фактически это только thin-specific shim, а не настоящий task engine.

### Gap 2. Политика по умолчанию запрещает coding tools

`src/swarmline/policy/tool_policy.py` содержит `ALWAYS_DENIED_TOOLS`, куда входят:
- `Bash/Read/Write/Edit/Glob/Grep/LS`
- snake_case варианты
- todo/web инструменты

Это хорошо как secure default, но мешает идее “thin как coding-agent” без отдельного policy profile.

### Gap 3. builtin executors и builtin tool specs живут в разных полуплоскостях

`ThinRuntime` подмешивает builtin executors в `local_tools`, но `ThinRuntimePort._build_active_tools()` строит tool list только из переданных `local_tools` и не делает отдельного unified merge через canonical builtin pack.

Следствие: часть builtins может быть исполнимой, но не всегда становится полноценной, согласованной частью модельного tool surface.

### Gap 4. Нет полноценного task runtime для coding-agent

В репозитории уже есть:
- `todo` layer
- `task session store`
- `graph task board`

Но нет одной cohesive runtime abstraction, которая бы давала coding-agent:
- create/update/reprioritize task
- mark in-progress/completed/blocked/cancelled
- list next-ready tasks
- persist state between runs
- map task state into context

### Gap 5. Context engineering уже есть, но ещё не coding-agent grade

`DefaultContextBuilder` уже умеет layered packs и budget, но пока не собирает полноценно такие срезы:
- active task summary
- plan summary
- workspace summary
- recent search summary
- active skill summary
- tool-state summary
- compaction artifacts для длинных coding-task runs

---

## Что можно переносить кодом прямо сейчас

## A. Из самого swarmline

Это первый и самый безопасный reuse.

### 1. Переиспользовать `todo/tools.py` внутри thin вместо stub `write_todos`

Что делать:
- убрать thin-specific markdown shim
- подключить `todo_read/todo_write` как canonical coding-agent tools
- thin aliases (`TodoRead`/`TodoWrite`) маппить на настоящий provider-backed layer

Почему:
- функциональность уже есть
- это устраняет самый очевидный внутренний дубль

### 2. Переиспользовать `GraphTaskBoard` как backend для task runtime

Что делать:
- не писать отдельный “task engine” с нуля
- использовать `GraphTaskBoard + TaskSessionStore` как state substrate

Почему:
- статусная модель и dependency handling уже реализованы
- архитектурно это соответствует текущему direction `swarmline`

### 3. Переиспользовать sandbox tools из `tools/builtin.py`

Что делать:
- сделать их canonical coding tools
- thin-специфичные имена (`read_file`, `write_file`, `edit_file`, `execute`) оставить как alias layer, а не как отдельную реализацию

Почему:
- один executor layer лучше, чем два частично пересекающихся

---

## B. Из aura

`aura` стоит рассматривать как источник **точечных seams**, а не как систему для wholesale port.

### 1. PathService

Файл:
- `packages/aura-agent/aura_agent/domain/services/path_service.py`

Что даёт:
- каноническая нормализация путей
- явное различение workspace roots / task roots / sandbox roots
- снижение риска path confusion и traversal bugs

Рекомендация:
- **прямой кандидат на перенос или tight adaptation**

### 2. Code execution contracts

Файлы:
- `packages/aura-agent/aura_agent/domain/code_execution/models.py`
- `packages/aura-agent/aura_agent/domain/code_execution/ports.py`
- `packages/aura-agent/aura_agent/domain/code_execution/policies.py`
- `packages/aura-agent/aura_agent/infrastructure/sandbox/local_sandbox.py`

Что даёт:
- чистое отделение file edits от command execution
- лимиты, политики, execution artifacts
- паттерн `script -> file -> execute`

Рекомендация:
- **сильный кандидат на перенос/адаптацию**
- особенно полезно для отделения `bash tool` от более общего code-exec backend

### 3. Code-agent domain contracts

Файлы:
- `packages/aura-agent/aura_agent/domain/code_agent/ports.py`
- `packages/aura-agent/aura_agent/domain/code_agent/models.py`

Что даёт:
- компактный доменный seam для code-agent logic
- можно положить поверх `thin`, не раздувая runtime core

Рекомендация:
- **прямой кандидат на reuse в адаптированном виде**

### 4. SkillManager / skill metadata pattern

Файл:
- `packages/aura-agent/aura_agent/application/components/context/skill_manager.py`

Что даёт:
- системный слой активации skill instructions
- контроль того, какие tool groups и инструкции реально попадают в context

Рекомендация:
- **адаптировать**, не копировать как есть

### 5. Context compiler

Файл:
- `packages/aura-agent/aura_agent/application/components/context/compiler.py`

Что даёт:
- layered context assembly
- compression / saturation / stable prefix patterns

Рекомендация:
- **использовать как reference architecture и частично портировать логику**
- не заменять `swarmline.context.builder` wholesale

### 6. Prometheus metrics

Файл:
- `packages/aura-agent/aura_agent/infrastructure/observability/prometheus_metrics.py`

Что даёт:
- richer metrics around llm/tool/task/delegation flows

Рекомендация:
- **можно переносить позже**, после стабилизации core coding-agent surface

---

## Что можно брать только как reference

## A. Из claw-code-agent

Технически это самый полезный референс для coding-agent UX и runtime shape, но юридически пока unsafe для literal copying.

### 1. `src/agent_tools.py`

Лучший reference для:
- coherent coding tool pack
- shape tool responses
- file/search/bash/todo/task UX
- streaming tool events

Использовать как:
- **эталон целевого surface**, не как copy source

### 2. `src/bash_security.py`

Очень полезный pattern для:
- command classification
- destructive command deny
- read-only mode
- special handling `git/find/grep/diff/test`

Использовать как:
- **reference для собственной bash policy layer**

### 3. `src/agent_context.py` + `src/agent_prompting.py`

Очень полезны как образец:
- richer system context
- workspace/session/plugin/tool summaries
- task-aware prompt sections

Использовать как:
- **reference для усиления `swarmline.context.builder`**

### 4. `src/task_runtime.py` + `src/plan_runtime.py`

Сильные patterns:
- dependency-aware task activation
- plan sync
- status transitions
- next-action semantics

Использовать как:
- **reference для task runtime над существующим `GraphTaskBoard`**

### 5. `src/compact.py` + session/context files

Сильный reference для:
- compaction
- session replay
- context snapshotting

Использовать как:
- **reference для long-horizon coding tasks**

---

## B. Из pi-mono/packages/coding-agent

Это не источник архитектуры engine, а источник **качественного tool UX**.

### 1. File mutation queue

Файл:
- `/tmp/pi-mono/packages/coding-agent/src/core/tools/file-mutation-queue.ts`

Ключевая идея:
- сериализовать мутации **по одному и тому же файлу**
- не блокировать операции по разным файлам

Рекомендация:
- перенести сам pattern в Python
- это особенно полезно для `write/edit/multi_edit`

### 2. Read tool UX

Файл:
- `/tmp/pi-mono/packages/coding-agent/src/core/tools/read.ts`

Ключевые идеи:
- `offset` / `limit`
- truncation metadata
- actionable continuation hints
- image-aware read path
- tool-specific prompt guidelines

Рекомендация:
- использовать как reference для улучшения `read` UX в `swarmline`

### 3. Общая дисциплина tool descriptions

Что полезно:
- short explicit descriptions
- направляющие подсказки “use this tool instead of bash/cat”
- bounded outputs and continuation protocol

Рекомендация:
- перенести подход в descriptions и schemas для builtin tools

---

## Что не стоит тащить

### Из aura
- `services/api-gateway/*`
- `services/auth-service/*`
- `services/tools-service/*`
- `devtools/chainlit-ui/*`
- app-specific storage models
- deployment glue
- verbatim prompt templates

### Из claw
- remote/account/worktree runtimes целиком
- plugin runtime целиком
- app shell / CLI orchestration целиком
- prompt texts буквально

### Из pi-mono
- весь framework/runtime shape
- TUI/rendering layer
- TS-specific abstractions как есть

---

## Юридический статус reuse

### aura

Проверка:
- `README.md` содержит указание на `MIT`

Вывод:
- `aura` можно считать **допустимым источником для осознанного code reuse**, при сохранении обычной инженерной осторожности

### claw-code-agent

Проверка локального shallow clone:
- не найден `LICENSE`
- не найден `COPYING`
- не найден `NOTICE`
- README использует wording “open-source”, но это не равно лицензии

Вывод:
- **literal copy code из claw сейчас не рекомендуется**
- использовать как reference можно
- копировать код только после явного license clearance

---

## Приоритетный backlog: что делать в swarmline

## P0 — собрать Thin coding-agent profile

### P0.1 Unified tool pack

Сделать единый набор:
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
- `task_*` surface

Подход:
- executors брать из `tools/builtin.py`, `todo/tools.py`, task runtime layer
- thin aliases оставить как совместимый facade

### P0.2 Replace thin stubs

Убрать thin shim:
- `write_todos` markdown persistence
- `task` noop

Заменить на:
- provider-backed todo tools
- persistent task runtime

### P0.3 Coding-agent policy profile

Не ломать `DefaultToolPolicy`.

Добавить:
- `CodingToolPolicyProfile`
- или `ToolPolicyProfile(coding_agent=True)`

Требование:
- secure-by-default для library сохраняется
- coding-agent mode включается явно

### P0.4 Canonical active tool assembly

Сделать так, чтобы builtin coding tools:
- не только исполнялись
- но и всегда стабильно попадали в `active_tools` / prompt surface / subagent inheritance

---

## P1 — усилить execution и context engineering

### P1.1 Introduce PathService

Вынести canonical path normalization layer:
- workspace root
- task root
- safe resolve
- optional sandbox root

### P1.2 Bash policy / command classifier

По мотивам `claw/bash_security.py`:
- destructive denylist
- read-only mode
- explicit command classification
- more structured errors for denied commands

### P1.3 File mutation queue

Сделать per-file serialization для:
- `write`
- `edit`
- `multi_edit`

### P1.4 Richer context compiler

Усилить `DefaultContextBuilder` слоями:
- current task summary
- ready tasks summary
- plan summary
- workspace summary
- active skills summary
- recent search / file activity summary
- compaction summary

---

## P2 — превратить thin в полноценный coding-agent engine

### P2.1 Task runtime facade

Сделать единый task API поверх:
- `GraphTaskBoard`
- `TaskSessionStore`
- `todo` layer

### P2.2 Code delegation workflow

Интегрировать:
- `spawn_agent`
- task tracking
- verify / rework loop
- completion status propagation

### P2.3 Rich tracing

Добавить:
- task lifecycle events
- tool rationale / policy decisions
- context saturation / compaction events
- delegation metrics

---

## Финальная рекомендация

Если цель — чтобы `thin` стал coding-agent по качеству и при этом `swarmline` остался clean library, то оптимальная стратегия такая:

1. **Не писать новый runtime**
2. **Не тащить чужие application graphs**
3. **Собрать internal seams `swarmline` в отдельный coding-agent profile**
4. **Из aura забрать path/code-exec/context seams**
5. **Из claw взять формы runtime/context/task UX как reference**
6. **Из pi-mono взять tool UX discipline и mutation queue**

Коротко:
- лучший reuse сейчас: **из `swarmline` и `aura`**
- лучший reference сейчас: **`claw` и `pi-mono`**
- biggest win: **task runtime + context compiler + policy profile**

---

## Recommended next implementation plan

### Phase 1
- unify builtin coding tools
- replace thin stubs
- wire todo/task persistence
- add coding-agent policy profile

### Phase 2
- add PathService
- add bash command classifier
- add file mutation queue
- enrich context builder with task/session/search summaries

### Phase 3
- add task runtime facade
- connect spawn/delegate/verify workflow
- add tracing/metrics for coding-agent flows

---

## Decision

**Recommendation**: развивать `thin` как canonical `swarmline` coding-agent runtime через composition existing seams, а не через новый отдельный runtime и не через прямой перенос кода из `claw`.

Это даёт:
- минимальный архитектурный риск
- максимальный reuse уже написанного кода
- чистое соответствие текущему direction `swarmline`
- хорошую базу для context engineering и agent engineering без разрастания core API
