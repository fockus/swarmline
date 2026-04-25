# Swarmline v1.4.1 — Production-Readiness & FastAPI-Parity Audit

**Date:** 2026-04-25  •  **Auditor:** 6 parallel exploration agents (DX / Architecture / Production / Multi-agent / Docs / Code-quality)  •  **Scope:** Full source (50K LOC), tests (78K LOC), docs (47 files), examples (32 files)

---

## TL;DR — Executive Summary

| Dimension | Score | Trend |
|---|---|---|
| **FastAPI-similarity (DX)** | **7.0 / 10** | Хороший hello-world, но 34-полевой `AgentConfig` и рассыпанные импорты |
| **Architecture & Clean-Architecture compliance** | **7.5 / 10** | ISP идеален (≤5 методов в 25 протоколах), но Domain тянет Infrastructure |
| **Multi-agent / Swarm depth** | **7.5 / 10** | 5 / 8 паттернов нативно; уникален Graph+Workflow+Team стек |
| **Production safety** | **6.5 / 10** | Default-deny, SSRF, path-traversal — solid; daemon не реализован, RBAC нет |
| **Documentation & DX** | **7.0 / 10** | 47 docs, но `mkdocstrings` настроен и не используется; нет Troubleshooting |
| **Code & test quality** | **5.5 / 10** | Ruff = 0; mypy = 4 ошибки; "4263 теста" → реально 2282 функции |
| **OVERALL — production-readiness** | **6.5 / 10** | "Beta" статус оправдан, до v2.0 prod-grade нужны 3-4 недели работы |

> **Verdict:** Swarmline — **серьёзный enterprise-каркас с уникальной триадой Graph + Workflow + Team**, который **архитектурно сильнее** CrewAI / OpenAI Swarm и **в управлении задачами и persistence — обгоняет LangGraph**. Однако до production-2.0 он не дотягивает по 6 конкретным осям (см. §6). FastAPI-философия "1 импорт + 3 строки" реализована **только на верхнем уровне**; глубже всплывают рассыпанные импорты, конфиг-overload и stub-API-reference.

---

## 1. Что Swarmline есть на самом деле

### Масштаб
- **50 680 строк** production-кода в 30+ модулях
- **78 589 строк** тестов в 352 файлах (`unit/integration/e2e/security`)
- **47 документов** (~430 KB markdown)
- **32 runnable примеров** (от 3-line agent до 519-line nano-CLI)
- **2 282 реальных тест-функции** (число "4263" — параметризованные варианты, **inflation x1.87**)

### Покрываемые форматы агентов
1. **Single-agent** — `Agent(AgentConfig(...))` + `query/stream/conversation`
2. **Workflow DAG** — `WorkflowGraph` со state, conditional edges, `add_parallel`, `add_interrupt` (HITL)
3. **Hierarchical org** — `GraphBuilder` → tree of `AgentNode` с `AgentCapabilities`, `LifecycleMode`, governance
4. **Pipeline** — `Pipeline` с phase-gates + `BudgetTracker`
5. **Team** — flat workers + lead через `ThinTeamOrchestrator / ClaudeTeamOrchestrator / DeepAgentsTeamOrchestrator`
6. **A2A** — `SwarmlineA2AAdapter` (Google A2A spec compliant)

### 4 swappable runtimes
| Runtime | Назначение | Зависимости |
|---|---|---|
| `thin` | Built-in loop, multi-provider | anthropic + openai + google-genai |
| `claude_sdk` | Claude Agent SDK adapter | claude-agent-sdk |
| `deepagents` | LangChain/LangGraph wrapper | langchain + langgraph |
| `cli` | OpenAI Agents SDK / Codex | openai-agents |

---

## 2. FastAPI-parity (developer experience)

### Где Swarmline === FastAPI

```python
# Swarmline (5 строк, 3 если убрать import и async обёртку):
from swarmline import Agent, AgentConfig
agent = Agent(AgentConfig(system_prompt="You are a helpful assistant.", runtime="thin"))
result = await agent.query("Capital of France?")

# FastAPI (4 строки):
from fastapi import FastAPI
app = FastAPI()
@app.get("/")
def read_root(): return {"Hello": "World"}
```

✅ **Параметрический декоратор `@tool`** инферит JSON Schema из type hints — точно как `@app.get` инферит query/path params.
✅ **Async-first** — `async with agent.conversation() as conv` идиоматично.
✅ **4 runtime под одной `AgentConfig`** — реальная JDBC-style абстракция (FastAPI этого не имеет).
✅ **Frozen `Result` dataclass** с `.ok` property — лучше dict-возврата.

### Где Swarmline ≠ FastAPI (критические DX-боли)

| # | Проблема | Файл / строка | Влияние |
|---|---|---|---|
| 1 | `CostTracker`, `SecurityGuard`, `Middleware`, `Conversation` НЕ экспортированы из `swarmline/__init__.py` — нужно `from swarmline.agent import …` | `src/swarmline/__init__.py:54-106` | Разработчик 15 минут ищет, где живёт CostTracker |
| 2 | `AgentConfig` имеет **34 поля** (vs ~15 у `FastAPI()`); enterprise-only поля (`tool_policy`, `command_registry`, `coding_profile`, `subagent_config`) загромождают IDE autocomplete простого юзера | `src/swarmline/agent/config.py:29-100` | Cognitive overload на старте |
| 3 | **3 способа** structured output: `output_format=dict`, `output_type=Pydantic`, `output_format=extract_pydantic_schema(...)` — нет single canonical way | `docs/getting-started.md:219-224` | "Какой выбрать?" — paralysis |
| 4 | Runtime-specific поля (`betas`, `sandbox`, `thinking`, `permission_mode`, `setting_sources`, `native_config`) живут в общем `AgentConfig` | `src/swarmline/agent/config.py` | При `runtime="thin"` 6+ полей бесполезны, но видны |
| 5 | **Error messages не actionable** — 40% просто констатируют (`"system_prompt must not be empty"`, `"SDK клиент не подключён"`) без recovery hint | `agent/config.py:104`, `runtime/adapter.py:191` | Stack-overflow вместо self-debug |
| 6 | `SwarmlineStack` упомянут в getting-started.md рано (line 542+) — путает: "я просто хочу `query()`" | `docs/getting-started.md` | Когнитивный диссонанс |
| 7 | `require_capabilities` не валидирует runtime в момент конструирования — fail только при первом вызове | `src/swarmline/agent/config.py` | Runtime-error вместо init-error |
| 8 | `Conversation` класс не задокументирован в `docs/api-reference.md` (есть только в примерах) | `docs/api-reference.md` | Discovery-проблема |

### FastAPI-similarity Verdict: **7 / 10**

> Знаком с FastAPI? Поймёшь Swarmline за 5 минут. Но потратишь 15 на поиск нужных импортов и параметров.

---

## 3. Архитектурное здоровье

### Сильные стороны

✅ **ISP идеально соблюдён** — все 25 `Protocol` классов имеют ≤ 5 методов:
- `MessageStore` (4), `FactStore` (2), `SummaryStore` (2), `GoalStore` (2), `SessionStateStore` (2), `UserStore` (2), `PhaseStore` (2), `ToolEventStore` (1)
- `AgentRuntime` (4), `HostAdapter` (4), `GraphOrchestrator` (5), `GraphCommunication` (5), `GraphTaskBoard` (5)

✅ **159 frozen dataclasses** (`grep -c "@dataclass(frozen=True)"`) — последовательная иммутабельность доменных объектов.

✅ **Protocol-first дизайн** — `RuntimePort`, `MemoryProvider`, `ToolPolicy` — реальные контракты, mockable, unit-test-friendly.

✅ **Унифицированный runtime-контракт** — все 3 runtime реализуют `async def run(...) -> AsyncIterator[RuntimeEvent]`. 90% бизнес-кода runtime-agnostic.

### Архитектурные нарушения (4 критичных)

#### 🔴 1. Domain → Infrastructure leak
```
src/swarmline/protocols/memory.py:7      → from swarmline.memory.types import …
src/swarmline/protocols/runtime.py:15    → from swarmline.runtime.types import …  (TYPE_CHECKING — менее болезненно)
```
**Фикс:** `MemoryMessage`, `GoalState`, `Message`, `ToolSpec` должны жить в `domain_types.py`. Сейчас их тащит из infra.

#### 🟡 2. Application → Infrastructure прямая зависимость
`src/swarmline/agent/agent.py` имеет 5 импортов из `swarmline.runtime.*`; `agent/runtime_wiring.py` импортирует `swarmline.tools.sandbox_local`.

**Фикс:** Agent должен зависеть от `AgentRuntime` Protocol, а не от конкретных классов.

#### 🟡 3. ThinRuntime мутирует `active_tools` внутри `run()`
`src/swarmline/runtime/thin/runtime.py:289-308` динамически добавляет MCP/subagent specs. Нарушает контракт "tools передаются перед run".

**Фикс:** `runtime_hints` в `RuntimeConfig` или builder pattern, не in-flight mutation.

#### 🟡 4. Двойной engine: `pipeline/` vs `orchestration/`
- `pipeline/` (10 файлов) — фазы + budget-gates
- `orchestration/` (35 файлов) — plans + teams + workflow + subagents

Оба умеют `execute_plan`. Граница не задокументирована.

**Фикс:** Pipeline должен быть **построен на** orchestration, либо явный roadmap-deprecation одного из них.

### Architecture Verdict: **7.5 / 10**

---

## 4. Multi-agent / Swarm возможности

### Карта стека (3 ортогональных слоя)

```
┌──────────────────────────────────────────────────────────────┐
│ LAYER 1: HIERARCHY  (multi_agent/, 39 files, ~3.5K LOC)      │
│  GraphBuilder → AgentNode tree → DefaultGraphOrchestrator    │
│  + GraphTaskBoard (DAG, atomic checkout, propagation)        │
│  + GraphGovernance (max_agents/depth, can_hire, can_delegate)│
│  + GraphCommunication (direct/broadcast_subtree/escalate)    │
│  + InMemory / SQLite / Postgres backends                     │
├──────────────────────────────────────────────────────────────┤
│ LAYER 2: WORKFLOW  (orchestration/, 35 files, ~2.5K LOC)     │
│  WorkflowGraph: add_node + add_edge + add_conditional_edge   │
│  add_parallel(then=…) + add_interrupt() (HITL)               │
│  TeamOrchestrator (3 flavors) + SubagentOrchestrator (3)     │
├──────────────────────────────────────────────────────────────┤
│ LAYER 3: PIPELINE  (pipeline/, 10 files, ~500 LOC)           │
│  Phase-based with budget gates per phase                     │
└──────────────────────────────────────────────────────────────┘
+ a2a/  — SwarmlineA2AAdapter (Google A2A spec)
+ routing/ — KeywordRoleRouter (simple keyword dispatch)
```

### Покрытие 8 multi-agent паттернов

| Паттерн | Status | Реализация |
|---|---|---|
| **Hierarchical / Supervisor** | ✅ Native | `DefaultGraphOrchestrator` + `GraphBuilder` |
| **Pipeline / Sequential** | ✅ Native | `WorkflowGraph.add_edge()` |
| **Router / Dispatcher** | ✅ Native | `KeywordRoleRouter` + `add_conditional_edge` |
| **Parallel / Fan-out** | ✅ Native | `WorkflowGraph.add_parallel(node_ids, then=…)` |
| **Peer-to-peer** | ⚠️ Partial | `broadcast_subtree` есть, P2P между siblings нет |
| **Hand-off (OpenAI Swarm style)** | ❌ Missing | Эмулируется `escalate()` + delegate, нет native API |
| **Voting / Debate** | ❌ Missing | Можно собрать вручную из workflow |
| **Reflection / Critique** | ❌ Missing | Можно собрать вручную из workflow loop |

### Где Swarmline впереди конкурентов

1. **Governance**: `max_agents`, `max_depth`, per-agent `can_hire / can_delegate / can_delegate_authority`, capability inheritance — **нет аналогов** в LangGraph/CrewAI/AutoGen/Swarm.
2. **Persistence first-class**: SQLite + Postgres backends для graph, task board, registry. LangGraph даёт только checkpointing, остальные — никак.
3. **Triple-stack** Graph + Workflow + Team одновременно: можно строить enterprise-org charts (Graph) поверх state-machine flows (WorkflowGraph) с flat worker pools (Team).
4. **Built-in budget tracking** + `BudgetTracker` per-phase — ни у кого нет.
5. **A2A protocol поддержка** — первый среди main-stream Python агентских фреймворков.

### Где Swarmline отстаёт

1. **Hand-off mechanism** — OpenAI Swarm имеет `Agent → Agent` нативно; здесь нужно эмулировать.
2. **Real-time chat coordination** — AutoGen group-chat первоклассен; здесь graph-first.
3. **Maturity ecosystem** — у LangGraph/CrewAI больше community, integrations, видеотуториалов.

### Multi-agent Verdict: **7.5 / 10**

---

## 5. Production safety, observability, reliability

### Security Posture (7.5 / 10)

✅ **Default-deny tool policy**: 26 tools (Bash/Read/Write/WebFetch и др.) запрещены по умолчанию (`src/swarmline/policy/tool_policy.py:79-179`).
✅ **SSRF protection** с DNS resolution + metadata-service blocking (169.254.169.254, 100.100.100.200) (`network_safety.py`).
✅ **Path traversal**: `.resolve() + is_relative_to()` атомарно — заменили старый `startswith()` (`path_safety.py`).
✅ **Composable guardrails**: pre/post-LLM checks выполняются параллельно через `asyncio.gather` (`guardrails.py`).
✅ **Secure-by-default v1.4.0**: `enable_host_exec=False`, `allow_host_execution=False`, `allow_unauthenticated_query=False`.

🔴 **Bearer token auth уязвим к timing attacks** — обычное `==` сравнение в `serve/app.py:26-54`. Нужен `hmac.compare_digest()`.
🔴 **Security tests = 1 файл, 1 функция** — критически мало для фреймворка с sandbox/permissions/multi-agent.
🟡 **Local sandbox = path-only isolation**, не container. Не годится для prod без Docker/E2B.
🟡 **Нет RBAC**: `AgentCapabilities` только parent/child, нет ролей/cross-team permissions.

### Error Model (6 / 10)

`RuntimeErrorData` (`domain_types.py:168-196`) — 12 видов ошибок типизированы. Это хорошо.

🔴 **Но нет base `SwarmlineError`** — 15+ exceptions разбросаны без общей иерархии:
- `GovernanceError` (multi_agent), `BudgetExceededError` (pipeline), `SandboxViolation` (tools), `A2AClientError` (a2a), `ApprovalDeniedError` (hitl), `DeepAgentsModelError` (deepagents), `ThinLlmError` (thin), …

🔴 **Rate limit detection через парсинг строк**: `if "429" in str(exc)` — brittle.

🔴 **Token-limit overflow = silent failure** — только event, не exception.

### Observability (7 / 10)

✅ **structlog везде** (~63 файла) + **OpenTelemetry GenAI Semantic Conventions** (`observability/otel_exporter.py:55-244`).
✅ **EventBus** с InMemory/Redis/NATS backends.
✅ **ActivityLog** — durable audit trail (max 10K entries).
✅ **JSONL sink** с redaction секретов (новый, ещё не вмёрженный — есть в текущем рабочем дереве).

🔴 **Нет агрегированных метрик** — token/cost/latency tracked per-call, но нет Prometheus/Datadog экспорта.
🔴 **OTel span name неоднозначен**: `swarmline.llm.{model}` без provider — не группируется по облаку.
🔴 **Distributed tracing мульти-агент-цепочек неполон** — есть `correlation_id`, нет parent-child relationship для иерархических spawn'ов.
🟡 **Нет SLO/SLA defaults** — docs не дают пороги.

### Operational (6.5 / 10)

✅ **CLI** — `swarmline init`, `swarmline run`, `swarmline mcp-serve`.
✅ **HTTP serve** — Starlette ASGI app (`/v1/health`, `/v1/info`, `/v1/query`).

🔴 **Daemon module НЕ РЕАЛИЗОВАН** — `DAEMON-PLAN.md` (335 строк) описывает архитектуру, но `daemon/runner.py`, `daemon/scheduler.py`, `daemon/health.py`, `daemon/pid.py` **отсутствуют**. Только `cli_entry.py` (7.2K) — stub.
🔴 **Нет TLS по умолчанию** — полагается на reverse proxy.
🔴 **Нет Kubernetes артефактов** — ConfigMap/Secret templates, health probes, resource limits gudiance.
🔴 **Secrets только через env-vars** — нет vault integrations.

### Production-safety Verdict: **6.5 / 10**

---

## 6. Code & test quality

### Real Numbers
- **Реально 2282 test-функций** (не 4263 — это параметризованные варианты)
- **Unit: 273 файла / 2140 функций** — отлично
- **Integration: 63 файла / 134 функции**
- **E2E: 15 файлов / 7 функций** (!) — критически мало для full-stack framework
- **Security: 1 файл / 1 функция** (!) — критически мало

### Coverage
🔴 **`[tool.coverage]` НЕ настроен в pyproject.toml** — coverage не tracked, baseline неизвестен.

### Lint & Types
✅ **ruff: 0 violations** — отлично.
🔴 **mypy: 4 ошибки**, 2 из которых — потенциальные runtime crashes:
```
src/swarmline/orchestration/coding_task_runtime.py:163 [attr-defined]
  "GraphTaskBoard" has no attribute "cancel_task"
src/swarmline/orchestration/coding_task_runtime.py:180 [attr-defined]
  "GraphTaskBoard" has no attribute "get_ready_tasks"
src/swarmline/orchestration/coding_task_runtime.py:184 [attr-defined]
  "GraphTaskBoard" has no attribute "get_blocked_by"
src/swarmline/project_instruction_filter.py:90 [arg-type]
  Argument 1 to "append" has incompatible type "tuple[int, list[str]]";
  expected "tuple[int, str]"
```

### Mock hygiene
- **Unit (правильно):** 1178 строк MagicMock/AsyncMock — изоляция OK.
- **Integration (нарушение):** 176 строк MagicMock — по правилам проекта integration не должен мокать ничего кроме LLM.

### Dependency hygiene
🔴 **Core deps без upper bounds:**
```toml
"structlog>=25.1.0",   # NO upper
"pyyaml>=6.0.2",       # NO upper
"pydantic>=2.11",      # NO upper
```
✅ Хороший пример — `langgraph>=1.1.1,<1.2.0`.

### Code & Quality Verdict: **5.5 / 10**

---

## 7. Документация

✅ **47 файлов**, mkdocs material theme, Mermaid диаграммы, структурированная навигация.
✅ **32 примера** покрывают весь спектр от 3-line agent до production workflows (24-27 — реальные multi-step).

🔴 **`mkdocstrings` настроен в `mkdocs.yml:109-122`, но НЕ используется** — `docs/api/agent.md` = 310 байт (заглушка). API-reference написан вручную и устаревает.
🔴 **Нет Troubleshooting guide** — критичный gap для production.
🔴 **Нет Performance tuning** — нет советов по latency/cost.
🔴 **Нет Common mistakes / Error catalog** — каждая ошибка живёт в коде, без рецепта recovery.
🔴 **Примеры не валидируются в CI** — могут устаревать.

### Documentation Verdict: **7 / 10**

---

## 8. Top 20 Production Blockers (приоритизированный список)

### P0 — БЛОКЕРЫ release v2.0 (нельзя выпускать без)

1. **Fix 4 mypy errors** — потенциальные runtime crashes в `coding_task_runtime.py` и `project_instruction_filter.py`. **Effort: 2 ч.**
2. **Daemon module реализовать** — `runner.py / scheduler.py / health.py / pid.py`. Без этого 24/7 autonomous mode невозможен. **Effort: 800 LOC, ~3 дня.**
3. **`hmac.compare_digest()` для bearer auth** — фикс timing-attack уязвимости. **Effort: 30 мин.**
4. **Coverage tracking + baseline ≥85% (core ≥95%)** — добавить `[tool.coverage]`, fail CI если ниже. **Effort: 1 день, фикс gaps — 2-3 дня.**
5. **Базовый `SwarmlineError` + иерархия** — рефакторинг 15+ exceptions под общий корень с типизированными подклассами `RateLimitError`, `TokenLimitError`, `NetworkError`. **Effort: 2 дня.**
6. **Security test suite ≥30 тестов** в `tests/security/` — сейчас 1 файл. SSRF, path traversal, RBAC, sandbox escape, prompt injection. **Effort: 3 дня.**

### P1 — Должно быть к v2.0 (критично для prod-grade)

7. **Domain → Infrastructure leak fix** — переместить `MemoryMessage`, `GoalState` в `domain_types.py`; `protocols/memory.py` не должен импортировать из `swarmline.memory.*`. **Effort: 4 ч.**
8. **Auto-generated API reference** — включить `mkdocstrings`, удалить ручные `docs/api/*.md` стабы. **Effort: 1 день.**
9. **Top-level exports**: `from swarmline import CostTracker, SecurityGuard, Middleware, Conversation, BudgetExceededError, …` — добавить в `__init__.py`. **Effort: 2 ч.**
10. **`AgentConfig` split**: `AgentConfig(basic) → AgentAdvancedConfig (enterprise) → AgentRuntimeConfig (runtime-specific)`. Без breaking changes — через nested dataclass. **Effort: 1 день.**
11. **Integration tests refactor** — убрать `MagicMock` из `tests/integration/`, заменить на реальные in-memory backends. **Effort: 2 дня.**
12. **Upper bounds на deps** — `structlog<26`, `pyyaml<7`, `pydantic<3`. **Effort: 30 мин.**
13. **E2E tests расширить** — сейчас 7 функций, нужно ≥30 для full-stack scenarios (multi-runtime, multi-agent flows, HITL, persistence). **Effort: 3 дня.**
14. **Error catalog в docs** — каждый error type + when raised + 2 recovery steps. **Effort: 1 день.**
15. **Troubleshooting guide** — top-15 common issues с решениями. **Effort: 1 день.**

### P2 — Sprint к v2.0.x (желательно)

16. **OTel span naming**: `swarmline.llm.{provider}.{model}` для группировки.
17. **Prometheus metrics endpoint** — token/cost/latency/error_rate aggregation.
18. **Production hardening checklist** в docs (10-item).
19. **Pipeline ↔ Orchestration unification** — либо явная иерархия, либо deprecation одного.
20. **Hand-off mechanism** — нативный `agent.handoff(target_agent_id)` API для OpenAI-Swarm-style патернов.

---

## 9. Top 10 Production Wins (что уже отлично)

1. **Default-deny tool policy** — 26 опасных tools заблокированы из коробки.
2. **SSRF + DNS resolution + metadata blocking** — реально хорошо.
3. **Path traversal** через `.resolve() + is_relative_to()` — атомарно и правильно.
4. **ISP всех 25 protocols ≤ 5 методов** — на годы вперёд testable.
5. **159 frozen dataclasses** — последовательная иммутабельность.
6. **Triple-stack Graph + Workflow + Team** — уникальное в экосистеме.
7. **Enterprise-grade governance** (max_depth, can_hire, capability inheritance) — nobody else has it.
8. **Persistence first-class** (SQLite + Postgres for graph/task-board/registry).
9. **OpenTelemetry GenAI Semantic Conventions** — современный стандарт.
10. **Migration guide v1.3→v1.4 + secure-by-default 1.4 stabilization** — release discipline уже есть.

---

## 10. Roadmap к Production v2.0 (~3 недели работы)

### Sprint A — Critical Fixes (3-4 дня)
- [ ] Fix 4 mypy errors → коммит, CI gate.
- [ ] `hmac.compare_digest` для bearer auth.
- [ ] Coverage tracking + первый baseline; CI fail на регрессию.
- [ ] Upper bounds на core deps.
- [ ] Top-level exports в `__init__.py` (CostTracker, SecurityGuard, Middleware, Conversation, errors).

### Sprint B — Foundation (5-6 дней)
- [ ] `SwarmlineError` иерархия + рефакторинг 15+ exceptions.
- [ ] Domain layer cleanup — переместить shared types в `domain_types.py`.
- [ ] `AgentConfig` split на basic / advanced / runtime-specific.
- [ ] Integration tests refactor — убрать MagicMock.
- [ ] Daemon module: `runner.py / scheduler.py / health.py / pid.py`.

### Sprint C — Production Operations (4-5 дней)
- [ ] Security test suite ≥30 (SSRF, path, RBAC, sandbox, prompt injection).
- [ ] E2E tests ≥30 scenarios.
- [ ] Prometheus metrics endpoint + observability dashboard guide.
- [ ] OTel span naming с provider.
- [ ] Production hardening checklist + Kubernetes templates.

### Sprint D — Documentation & DX (3-4 дня)
- [ ] Включить `mkdocstrings` для auto API-reference, удалить stub'ы.
- [ ] Troubleshooting guide (top-15 issues).
- [ ] Error catalog (каждый error + recovery).
- [ ] Runtime selection decision tree.
- [ ] Performance tuning guide.
- [ ] Validate examples in CI.

### Sprint E — Multi-agent completeness (опционально, 2-3 дня)
- [ ] Native `Agent.handoff(target)` API.
- [ ] `Agent.critique(other)` для reflection pattern.
- [ ] `VotingOrchestrator` для consensus.

---

## 11. Финальный Verdict

> **Swarmline v1.4.1 — это серьёзный enterprise-каркас, обогнавший CrewAI / OpenAI Swarm по архитектурной чистоте и persistence, и обогнавший LangGraph по governance и task management. Для FastAPI-style радости пользователя нужны 3 недели полировки экспортов, конфигов, ошибок и документации.**

**Production-readiness score: 6.5 / 10** ("Beta justified, не production-grade без Sprint A+B").

**После Sprint A+B+C+D (~3 недели) → 9 / 10** — реальный production-2.0 уровень.

**Уникальная позиция:** не "ещё один LangChain wrapper", а полноценный фреймворк со своей философией (Graph + Workflow + Team триада, governance-first, runtime-agnostic). При закрытии 6 P0-блокеров — **серьёзный кандидат на стандарт для enterprise multi-agent систем в Python**.

---

*Полные данные исследования (6 параллельных агентов) — в .memory-bank/reports/2026-04-25_audit_production-readiness-fastapi-parity.raw.md (если потребуется).*
