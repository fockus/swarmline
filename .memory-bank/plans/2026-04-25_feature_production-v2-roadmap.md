# Plan: Swarmline Production v2.0 — Full Framework Roadmap

**Created:** 2026-04-25
**Type:** feature (multi-phase upgrade)
**Owner:** Anton Ivanov
**Status:** DRAFT — awaiting approval
**Source audit:** `.memory-bank/reports/2026-04-25_audit_production-readiness-fastapi-parity.md`

---

## 1. Goal (SMART)

| Criterion | Value |
|---|---|
| **Specific** | Довести swarmline до уровня **полноценного FastAPI-style фреймворка** для production AI-агентов: иерархических, swarm, pipeline, multi-runtime |
| **Measurable** | Production-readiness 6.5 → **9.0**; FastAPI-similarity 7.0 → **9.0**; `ty check` ошибок 75 → **0**; coverage gates: overall ≥85%, core ≥95%, infra ≥70%; security tests 1 → **30+**; E2E tests 7 → **30+**; daemon module реализован; mkdocstrings включён; SwarmlineError иерархия введена |
| **Achievable** | На основе текущего состояния (50K LOC, 2282 тестов, ISP idealen, 159 frozen DC) — это **полировка + достройка**, не rewrite. ~4 человеко-недели сфокусированной работы |
| **Relevant** | Без этого v2.0 не может быть выпущен как production. Текущий "Beta" статус оправдан, но блокирует enterprise-adoption |
| **Time-bound** | 6 sprintов, **22 фазы**, **22 рабочих дня сфокусированной работы**. Календарно — 4-5 недель |

---

## 2. Контекст и предпосылки

### 2.1 Что уже работает (на чём строим)
- **ISP-compliant 25 protocols** (≤5 методов каждый)
- **159 frozen dataclasses** — иммутабельность доменных объектов
- **3 runtimes** под одним `AgentRuntime` контрактом
- **Triple-stack multi-agent** (Graph + Workflow + Team)
- **Default-deny tool policy** + SSRF + path-traversal
- **OpenTelemetry GenAI** semantic conventions
- **Ruff: 0 violations**
- **2282 реальных test-функций**

### 2.2 Что блокирует production (источник аудита)
1. `ty check src/swarmline/` → **75 diagnostics** (после смены strict-режима)
2. Coverage не tracked
3. Daemon module = только `DAEMON-PLAN.md` + stub
4. Bearer auth уязвим к timing attacks
5. Security tests = 1 файл / 1 функция
6. 15+ exceptions без общего корня `SwarmlineError`
7. `AgentConfig` = 34 поля, mixed simple+enterprise+runtime-specific
8. `mkdocstrings` настроен но не используется → API-docs устарели
9. Domain тянет Infrastructure (`protocols/memory.py:7`)
10. Integration tests с MagicMock (нарушение правила "интеграция = реальные deps")

### 2.3 Constraints (нерушимые)
- **Backwards compat:** все 2282 теста зелёные на каждом этапе. Новые поля — optional с None default.
- **TDD:** tests → implementation → refactor. Каждая фаза начинается с red.
- **Contract-first:** Protocol/ABC → contract tests → implementation.
- **Clean Architecture:** Infrastructure → Application → Domain (никогда обратно).
- **ISP:** Protocol ≤ 5 методов.
- **Python 3.11+** (`requires-python = ">=3.11"`).
- **Versioning:** вся работа = **v2.0.0** (один major release, breaking changes консолидированы).
- **Git workflow:** feature branches `feat/v2-phaseNN-<slug>` → squash-merge в `main` после verification.
- **Type checker = ty (только)**. Удалён mypy из `.pipeline.yaml`.

---

## 3. Sprint Overview

| Sprint | Дни | Фазы | Цель |
|---|---|---|---|
| **A — Foundation Hardening** | 5 | 1-5 | ty: 75→0, coverage baseline, top-level exports, dep bounds, SwarmlineError |
| **B — Architecture Cleanup** | 5 | 6-9 | Domain leak fix, AgentConfig split, Pipeline/Orch boundary, ThinRuntime tools immutability |
| **C — Security & Tests** | 5 | 10-13 | hmac auth + security tests 1→30, integration refactor, E2E 7→30 |
| **D — Operational** | 5 | 14-17 | Daemon module, Prometheus metrics, OTel parent-child, K8s templates |
| **E — Docs & Polish** | 3 | 18-21 | mkdocstrings auto-API, Troubleshooting, Error catalog, CI validates examples |
| **F — Multi-agent Completeness** *(opt)* | 3 | 22-24 | Native handoff, critique/reflection, VotingOrchestrator |

**Parallel execution:** фазы 4, 5, 6 — независимы и могут идти в worktrees параллельно. Аналогично 11, 12, 13.

---

# SPRINT A — Foundation Hardening

## Phase 01: ty errors 75 → 0

**Goal:** Sustainable type-safety с `ty` в strict режиме (`respect-type-ignore-comments = false`, `error-on-warning = true`).

**Why now:** блокирует CI; 4 из 75 — потенциальные runtime crashes (`coding_task_runtime.py:163,180,184` вызывают несуществующие методы `GraphTaskBoard`).

### DoD (SMART)
- [ ] `ty check src/swarmline/` → **0 diagnostics** (measurable)
- [ ] CI gate: `ty check` выполняется на каждый PR, fail-on-error (specific)
- [ ] Все `# type: ignore` комментарии заменены на корректные типы или явные `cast()` с reason (`# type: ignore[unresolved-import]  # tavily optional dep` и т.д.) (achievable)
- [ ] Все 4 critical errors из `coding_task_runtime.py` + `project_instruction_filter.py` исправлены с red→green тестом (relevant)
- [ ] `coding_task_runtime.py:163,180,184` — методы либо добавлены в `GraphTaskBoard` Protocol, либо вызовы убраны (relevant)
- [ ] Документировано в `.memory-bank/notes/2026-04-25_ty-strictness-decisions.md` правила обращения с optional deps и type:ignore (time-bound: на этой фазе)

### TDD plan (tests FIRST)
1. `tests/unit/test_coding_task_runtime_methods.py` — red тесты, проверяющие что вызовы `cancel_task / get_ready_tasks / get_blocked_by` либо работают через адаптер, либо защищены от вызова
2. `tests/unit/test_project_instruction_filter_types.py` — red тест для tuple type mismatch
3. `tests/unit/test_ty_strict_mode.py` — мета-тест: `subprocess.run(["ty", "check", "src/swarmline/"])` → exit 0

### Files affected
- `src/swarmline/orchestration/coding_task_runtime.py`
- `src/swarmline/project_instruction_filter.py`
- `src/swarmline/protocols/graph_task.py` (возможно — добавить недостающие методы в Protocol)
- ~30 файлов с `# type: ignore` (по мере появления)
- `.github/workflows/ci.yml` — добавить ty step

### Edge cases
- Optional deps (tavily, crawl4ai, ddgs, openshell) — выделить отдельный паттерн `try/except ImportError` + `if TYPE_CHECKING`
- `provider_options: dict[str, Any]` — оставить как есть (legitimate `Any`), задокументировать

### Verification
```bash
ty check src/swarmline/                    # → 0 diagnostics
pytest -x                                   # → all green
ruff check src/ tests/                      # → 0 violations
```

### Estimate
**1.5 рабочих дня** (12 ч). 4 critical fixes — 3-4 ч, остальные 71 — пакетная обработка.

### Dependencies
None (фаза 1).

---

## Phase 02: Coverage tracking + baseline ≥85/95/70

**Goal:** Coverage запинен в pyproject + CI fail-on-regression.

**Why now:** без baseline нельзя честно оценивать качество остальных фаз; правило проекта требует overall ≥85%, core ≥95%, infra ≥70%.

### DoD (SMART)
- [ ] `[tool.coverage.run]` + `[tool.coverage.report]` в `pyproject.toml`
- [ ] `pytest --cov` интегрирован: `pytest --cov=swarmline --cov-report=term-missing --cov-report=xml`
- [ ] Coverage baseline зафиксирован в `.memory-bank/reports/2026-04-25_coverage_baseline.md`
- [ ] CI step: coverage ≥85% overall, ≥95% для `agent/`, `protocols/`, `bootstrap/`, `domain_types.py`, `types.py`; ≥70% для `runtime/`, `memory/sqlite`, `memory/postgres`, `tools/`
- [ ] CI fail при регрессии coverage > 0.5%
- [ ] `coverage.xml` загружается в Codecov (или `.coveragerc` зеркалирует это)
- [ ] Файлы с `< 60%` coverage задокументированы как "техдолг" с issue в BACKLOG

### TDD plan
N/A — это инфраструктура. Но добавить `tests/integration/test_coverage_config.py`: парсит `pyproject.toml`, проверяет наличие секций.

### Files affected
- `pyproject.toml`
- `.github/workflows/ci.yml`
- `.memory-bank/reports/2026-04-25_coverage_baseline.md` (создать)
- `.memory-bank/BACKLOG.md` (добавить tech-debt entries)

### Edge cases
- Тесты `live`-маркера — исключить из coverage (`--cov-fail-under` not applied)
- Optional dep код (`if TYPE_CHECKING`) — исключить через `[tool.coverage.report] exclude_lines`

### Verification
```bash
pytest --cov=swarmline --cov-fail-under=85
# overall ≥85%, не падает
```

### Estimate
**0.5 дня** (4 ч).

### Dependencies
None.

---

## Phase 03: Top-level exports + DX cleanup

**Goal:** FastAPI-style "1 import — всё что нужно".

**Why now:** разработчик при `from swarmline import …` должен получать `Agent, AgentConfig, tool, Result, Conversation, CostTracker, SecurityGuard, Middleware, BudgetExceededError, …`. Сейчас 4 из 9 ключевых требуют `from swarmline.agent import …`.

### DoD (SMART)
- [ ] `swarmline/__init__.py` экспортирует:
  - **Core API:** `Agent`, `AgentConfig`, `Conversation`, `Result`, `tool`, `Message`, `RuntimeConfig`, `RuntimeEvent`, `ToolSpec`
  - **Middleware (бывшие в `swarmline.agent`):** `Middleware`, `CostTracker`, `SecurityGuard`
  - **Errors (новая иерархия из Phase 5):** `SwarmlineError`, `BudgetExceededError`, `RateLimitError`, `TokenLimitError`, `GuardrailError`, `RuntimeAdapterError`
  - **Multi-agent shortcuts:** `GraphBuilder`, `WorkflowGraph`, `AgentNode`, `AgentCapabilities`
- [ ] `__all__` обновлён — отсортирован, без дублей
- [ ] `tests/unit/test_public_api_surface.py` — фиксирует точный список экспортов; падает при **любом** изменении (защита от случайных удалений)
- [ ] `examples/01_agent_basics.py` обновлён: `from swarmline import …` без `from swarmline.agent import`
- [ ] `docs/getting-started.md` обновлён: убраны `from swarmline.agent import CostTracker, SecurityGuard, Middleware`
- [ ] CHANGELOG: "v2.0: top-level exports for CostTracker, SecurityGuard, Middleware, GraphBuilder, WorkflowGraph"

### TDD plan
1. `tests/unit/test_public_api_surface.py` — red:
   ```python
   def test_top_level_exports_complete():
       import swarmline
       expected = {"Agent", "AgentConfig", "Conversation", "Result", "tool",
                   "Middleware", "CostTracker", "SecurityGuard",
                   "SwarmlineError", "BudgetExceededError", "RateLimitError",
                   "GraphBuilder", "WorkflowGraph", "AgentNode", "AgentCapabilities", ...}
       assert expected.issubset(set(swarmline.__all__))
       for name in expected:
           assert hasattr(swarmline, name), f"{name} missing"
   ```
2. После добавления экспортов — тест становится green.

### Files affected
- `src/swarmline/__init__.py`
- `tests/unit/test_public_api_surface.py` (создать)
- `examples/01_agent_basics.py`, `04_middleware_chain.py`, `11_cost_budget.py`
- `docs/getting-started.md`

### Edge cases
- Циклы импорта при добавлении `GraphBuilder` на верх — использовать lazy import через `__getattr__` (PEP 562) если нужно
- Backwards compat: старые пути `from swarmline.agent import CostTracker` **должны продолжить работать** (re-export, не move)

### Verification
```bash
python -c "from swarmline import CostTracker, Middleware, SwarmlineError, GraphBuilder; print('ok')"
pytest tests/unit/test_public_api_surface.py -v
```

### Estimate
**0.5 дня** (4 ч).

### Dependencies
**Soft:** Phase 05 (SwarmlineError) — но можно делать параллельно, мерджить после.

---

## Phase 04: Dependency upper bounds + security update policy

**Goal:** Защита от breaking minor releases в core deps.

**Why now:** `structlog>=25.1.0`, `pyyaml>=6.0.2`, `pydantic>=2.11` — без верхних границ. Если выйдет structlog 30 с breaking changes, swarmline сломается.

### DoD (SMART)
- [ ] `pyproject.toml` обновлён:
  ```toml
  dependencies = [
      "structlog>=25.1.0,<26",
      "pyyaml>=6.0.2,<7",
      "pydantic>=2.11,<3",
  ]
  ```
- [ ] Optional deps также с upper:
  - `anthropic>=0.86,<2`
  - `openai>=2.29,<3`
  - `google-genai>=1.68,<2`
  - `deepagents>=0.4.12,<1`
- [ ] `pip install -e ".[dev,all]"` — устанавливается без конфликтов
- [ ] `pytest -x` зелёный
- [ ] `.github/workflows/ci.yml` — matrix для Python 3.11/3.12/3.13
- [ ] `docs/releasing.md` дополнен правилом: "при апгрейде upper bound — minor bump swarmline"

### TDD plan
N/A — конфигурация. Smoke test: `tests/integration/test_install_compat.py` — проверка `import` основных deps.

### Files affected
- `pyproject.toml`
- `.github/workflows/ci.yml`
- `docs/releasing.md`

### Edge cases
- `langgraph>=1.1.1,<1.2.0` уже жёстко зафиксирован — не трогать
- Если `pip install` ругается — сначала найти какой dep тащит несовместимую версию

### Verification
```bash
pip install -e ".[dev,all]"
pytest -x
ty check src/swarmline/
```

### Estimate
**0.25 дня** (2 ч).

### Dependencies
None.

---

## Phase 05: SwarmlineError hierarchy + typed runtime exceptions

**Goal:** Единая иерархия исключений вместо 15+ разрозненных.

**Why now:** разработчик пишет `try: ... except ???: ...` и не знает какие исключения ловить. Сейчас он должен импортировать `BudgetExceededError, GovernanceError, A2AClientError, ApprovalDeniedError, ThinLlmError, …` — 15 имён из 6 модулей.

### DoD (SMART)
- [ ] Создан `src/swarmline/errors.py` с базовой иерархией:
  ```
  SwarmlineError(Exception)
   ├── ConfigError              ValueError'ы конфига
   ├── RuntimeAdapterError      runtime/* ошибки
   │    ├── RateLimitError      429 от провайдера
   │    ├── TokenLimitError     overflow контекста
   │    ├── ModelNotFoundError  провайдер не знает модель
   │    └── NetworkError        connection / timeout
   ├── ToolError
   │    ├── ToolPolicyDenied    default-deny сработал
   │    ├── ToolExecutionError  тул бросил при run
   │    └── SandboxViolation    выход за периметр
   ├── BudgetExceededError      cost / token budget
   ├── GuardrailError           pre/post LLM tripwire
   ├── GovernanceError          graph rules сработали
   ├── ApprovalDeniedError      HITL отказ
   └── A2AClientError           inter-agent network
  ```
- [ ] **Все 15+ существующих exceptions** наследуются от соответствующих узлов (через MRO; backwards compat сохраняется)
- [ ] ThinRuntime парсинг по строкам (`if "429" in str(exc)`) **удалён** — заменён на `except RateLimitError` или явный mapping в `_normalize_provider_error()`
- [ ] Документация `docs/errors.md` (создать) — таблица: error → причина → recovery hint
- [ ] `__init__.py` экспортирует базовый `SwarmlineError` + 6 ключевых подклассов

### TDD plan (TDD red → green)
1. `tests/unit/test_error_hierarchy.py`:
   ```python
   def test_all_swarmline_errors_inherit_base():
       errors = [BudgetExceededError, GovernanceError, ToolPolicyDenied, ...]
       for E in errors:
           assert issubclass(E, SwarmlineError)

   def test_rate_limit_error_caught_by_runtime_adapter_error():
       try: raise RateLimitError("429")
       except RuntimeAdapterError: pass  # green

   def test_legacy_imports_still_work():
       from swarmline.pipeline.budget_tracker import BudgetExceededError as Old
       from swarmline.errors import BudgetExceededError as New
       assert Old is New  # re-export, not duplicate
   ```
2. `tests/integration/test_runtime_error_mapping.py`:
   ```python
   async def test_anthropic_429_becomes_rate_limit_error():
       runtime = ThinRuntime(...)
       with mock_provider_response(status=429):
           with pytest.raises(RateLimitError):
               async for _ in runtime.run(...): pass
   ```

### Files affected
- `src/swarmline/errors.py` (создать)
- `src/swarmline/pipeline/budget_tracker.py` (re-export из errors.py)
- `src/swarmline/multi_agent/governance.py` (re-export)
- `src/swarmline/policy/tool_policy.py` (новые `ToolPolicyDenied`)
- `src/swarmline/runtime/thin/runtime.py` (заменить string parsing на typed)
- `src/swarmline/runtime/thin/llm_providers.py` (`_normalize_provider_error()`)
- `src/swarmline/runtime/thin/errors.py` (re-export)
- `src/swarmline/__init__.py`
- `docs/errors.md` (создать)
- ~10 других мест с `raise SomeError(...)` — сделать их подклассами `SwarmlineError`

### Edge cases
- Старый код у пользователей: `except Exception` продолжает работать
- Старые импорты `from swarmline.pipeline import BudgetExceededError` — должны работать
- Provider-specific exceptions (anthropic.RateLimitError) — НЕ наследуем от наших; маппим в `_normalize_provider_error()`

### Verification
```bash
pytest tests/unit/test_error_hierarchy.py tests/integration/test_runtime_error_mapping.py -v
ty check src/swarmline/
grep -rn "if \"429\"\|if \"rate_limit\"" src/swarmline/  # → пусто
```

### Estimate
**1.5 дня** (12 ч).

### Dependencies
None (можно параллельно с Phase 03, 04).

---

# SPRINT B — Architecture Cleanup

## Phase 06: Domain → Infrastructure leak fix

**Goal:** Domain слой не импортирует из Infrastructure.

**Why now:** `protocols/memory.py:7` импортирует `from swarmline.memory.types` — нарушение Clean Architecture, защищаемого `.pipeline.yaml:38-39 architecture_rules`.

### DoD (SMART)
- [ ] `protocols/memory.py` НЕ импортирует из `swarmline.memory.*`
- [ ] `protocols/runtime.py` НЕ импортирует из `swarmline.runtime.*` (даже под TYPE_CHECKING — переносим типы в `domain_types.py`)
- [ ] `protocols/graph_*.py` НЕ импортируют из `swarmline.multi_agent.*`
- [ ] Все доменные типы (`MemoryMessage`, `GoalState`, `MemoryFact`, `MemorySummary`, `SessionState`, …) живут в `src/swarmline/domain_types.py`
- [ ] Architectural test добавлен: `tests/architecture/test_layering.py` через `pytest-archon` или ручной AST-парсер:
  ```python
  def test_domain_does_not_import_infra():
      domain_files = ["src/swarmline/protocols/", "src/swarmline/types.py", "src/swarmline/domain_types.py"]
      for f in walk(domain_files):
          imports = parse_imports(f)
          forbidden = ["swarmline.memory.", "swarmline.runtime.", "swarmline.tools.", "swarmline.multi_agent."]
          for imp in imports:
              assert not any(imp.startswith(f) for f in forbidden), f"{f}: forbidden {imp}"
  ```
- [ ] CI gate: architectural test fail → block merge
- [ ] `.pipeline.yaml architecture_rules` enforced скриптом, не только декларативно

### TDD plan
1. `tests/architecture/test_layering.py` — red изначально (текущие нарушения видны)
2. Рефакторинг по одному файлу за раз; тесты проходят инкрементально
3. После всех правок — green

### Files affected
- `src/swarmline/domain_types.py` (расширить)
- `src/swarmline/protocols/memory.py`
- `src/swarmline/protocols/runtime.py`
- `src/swarmline/memory/types.py` (re-export из domain_types для backwards compat)
- `src/swarmline/runtime/types.py` (re-export)
- `tests/architecture/test_layering.py` (создать)
- `tests/architecture/__init__.py`

### Edge cases
- Циклы при перемещении: проверить что `domain_types.py` не зависит ни от чего проектного
- `RuntimeEvent`, `RuntimeConfig` — тонкий случай; они одновременно используются в Protocol (Domain) и в реализациях (Infra). Решение: `RuntimeEvent` → `domain_types.py`, специфичные конфиги (например `ThinRuntimeConfig`) — остаются в `runtime/`

### Verification
```bash
pytest tests/architecture/ -v
ty check src/swarmline/
pytest -x
```

### Estimate
**1 день** (8 ч).

### Dependencies
**Hard:** None.
**Soft:** Phase 01 (ty errors) — должны быть исправлены, чтобы рефакторинг не создавал новых.

---

## Phase 07: AgentConfig split (basic / advanced / runtime-specific)

**Goal:** Понизить когнитивную нагрузку с 34 полей до **8 базовых** + nested advanced configs.

**Why now:** разработчик с `runtime="thin"` видит `betas, sandbox, permission_mode, setting_sources, native_config` в IDE autocomplete — путаница. Простой агент должен иметь простой config.

### DoD (SMART)
- [ ] **`AgentConfig` (базовый)** — 8 полей: `system_prompt, model, runtime, tools, middleware, hooks, max_turns, output_format`
- [ ] **`AgentConfig.advanced: AgentAdvancedConfig | None`** — nested:
  ```python
  @dataclass(frozen=True)
  class AgentAdvancedConfig:
      max_budget_usd: float | None = None
      structured_mode: Literal["prompt", "tool", "native"] = "prompt"
      structured_strict: bool = True
      max_model_retries: int | None = None
      cwd: Path | None = None
      env: dict[str, str] = field(default_factory=dict)
      thinking: ThinkingConfig | None = None
      max_thinking_tokens: int | None = None
      fallback_model: str | None = None
      tool_policy: ToolPolicy | None = None
      subagent_config: SubagentConfig | None = None
      command_registry: CommandRegistry | None = None
      coding_profile: str | None = None
      feature_mode: Literal["portable", "native"] = "portable"
  ```
- [ ] **`AgentConfig.runtime_options: RuntimeOptions | None`** — nested, runtime-specific:
  ```python
  @dataclass(frozen=True)
  class ClaudeSDKOptions:
      betas: tuple[str, ...] = ()
      sandbox: SandboxConfig | None = None
      permission_mode: Literal[...] = "bypassPermissions"
      setting_sources: tuple[str, ...] = ()

  @dataclass(frozen=True)
  class DeepAgentsOptions:
      allow_native_features: bool = False
      native_config: dict[str, Any] = field(default_factory=dict)
  ```
- [ ] **Backwards compat:** старый flat `AgentConfig(system_prompt=..., betas=..., sandbox=...)` продолжает работать — через `__post_init__` миграция в nested
- [ ] **Deprecation warnings:** при использовании старых flat полей — `DeprecationWarning` со ссылкой на migration guide
- [ ] `docs/migration-guide.md` дополнен — раздел "v1.4 → v2.0: AgentConfig split"
- [ ] Все примеры в `examples/` обновлены на новый API (но старые pattern проверены тестами)

### TDD plan
1. `tests/unit/test_agent_config_v2_split.py`:
   ```python
   def test_basic_config_has_8_fields():
       fields = {f.name for f in dataclasses.fields(AgentConfig)
                 if not f.name.startswith("_")}
       basic = {"system_prompt", "model", "runtime", "tools", "middleware",
                "hooks", "max_turns", "output_format", "advanced", "runtime_options"}
       assert fields == basic

   def test_legacy_flat_config_still_works():
       cfg = AgentConfig(system_prompt="x", runtime="claude_sdk", betas=("alpha",))
       # backwards compat — поле betas мигрирует в runtime_options.betas
       assert cfg.runtime_options.betas == ("alpha",)
       # warning emitted
   
   def test_advanced_config_optional():
       cfg = AgentConfig(system_prompt="x", runtime="thin")
       assert cfg.advanced is None  # default

   def test_nested_advanced_works():
       cfg = AgentConfig(
           system_prompt="x", runtime="thin",
           advanced=AgentAdvancedConfig(max_budget_usd=5.0)
       )
       assert cfg.advanced.max_budget_usd == 5.0
   ```
2. `tests/integration/test_agent_config_v2_runtime_routing.py` — проверка что `Agent(cfg).query(...)` работает на любом из 4 runtimes с новым split-config

### Files affected
- `src/swarmline/agent/config.py` (heavy refactor)
- `src/swarmline/agent/runtime_wiring.py` (читать новые nested поля)
- `src/swarmline/__init__.py` (экспортировать `AgentAdvancedConfig`, `ClaudeSDKOptions`, `DeepAgentsOptions`)
- 32 файла в `examples/` (обновить — но не все, оставить flat-style как deprecated demo)
- `docs/migration-guide.md`
- `docs/agent-facade.md`
- `docs/configuration.md`

### Edge cases
- `__post_init__` миграция flat → nested: должен быть идемпотентным
- `tests/unit/test_agent_runtime_wiring.py` — все 12+ тестов должны зеленеть
- `Agent.query` сигнатура НЕ меняется
- Если оба указаны (flat + nested) → `ConfigError` "specify either flat field or runtime_options.X, not both"

### Verification
```bash
pytest tests/unit/test_agent_config_v2_split.py tests/integration/test_agent_config_v2_runtime_routing.py -v
pytest tests/  # все 2282+ тестов green
python -W error::DeprecationWarning -c "from swarmline import Agent, AgentConfig; cfg = AgentConfig(system_prompt='x', runtime='claude_sdk', betas=('a',))"
# DeprecationWarning должен быть raised
```

### Estimate
**2 дня** (16 ч). Самая трудозатратная фаза в Sprint B.

### Dependencies
**Soft:** Phase 03 (top-level exports) — после этой фазы экспортируем новые `AgentAdvancedConfig`, `ClaudeSDKOptions`.

---

## Phase 08: Pipeline ↔ Orchestration unification

**Goal:** Чёткая граница между `pipeline/` и `orchestration/`, либо deprecation одного.

**Why now:** оба умеют `execute_plan`, разработчик путается. Source code review показал — `pipeline/` это спец-случай orchestration с phase-budget-gates.

### DoD (SMART)
- [ ] **Решение зафиксировано как ADR** в `.memory-bank/BACKLOG.md` с auto-ID `ADR-NNN`
- [ ] **Вариант A (предпочтительный):** `pipeline/` строится поверх `orchestration/`:
  - `Pipeline` → внутри использует `WorkflowGraph` с `add_interrupt` между фазами для budget-gates
  - `BudgetTracker` остаётся как отдельный middleware/observer
  - Удалена дубликация sequential execution
- [ ] **Вариант B (если A слишком инвазивен):** документация чётко разделяет use-cases:
  - `pipeline/` = "phase-based business processes с budget-gates" (CI/CD-like)
  - `orchestration/` = "graph-based agent flows с conditional routing"
  - Cross-reference в обеих docs
- [ ] `docs/orchestration.md` и `docs/pipeline.md` имеют top-section "When to use which" с decision tree
- [ ] Примеры обновлены: `examples/22_task_queue.py` использует pipeline; `examples/20_workflow_graph.py` использует orchestration — без перекрёстных импортов
- [ ] `tests/integration/test_pipeline_orchestration_boundary.py` — проверка отсутствия cross-imports

### TDD plan
1. `tests/integration/test_pipeline_orchestration_boundary.py`:
   ```python
   def test_no_pipeline_imports_in_orchestration():
       check_no_imports("src/swarmline/orchestration/", forbidden_prefix="swarmline.pipeline.")
   def test_no_circular_imports():
       import swarmline.pipeline
       import swarmline.orchestration
       # не должно быть RecursionError
   ```
2. Если выбран вариант A — `tests/integration/test_pipeline_built_on_workflow_graph.py` проверяет что `Pipeline.run()` использует `WorkflowGraph` под капотом (white-box, через mock).

### Files affected
- `src/swarmline/pipeline/pipeline.py` (если вариант A — refactor; если B — comments)
- `docs/pipeline.md`, `docs/orchestration.md`
- `.memory-bank/BACKLOG.md` (ADR entry)

### Edge cases
- Variant A — risk of breaking 12+ существующих pipeline тестов; тщательная backwards-compat проверка
- Variant B — проще, но не убирает дубликат

### Verification
```bash
pytest tests/integration/test_pipeline_orchestration_boundary.py -v
pytest tests/integration/test_pipeline*.py -v
pytest tests/integration/test_orchestration_*.py -v
```

### Estimate
**Variant A: 2 дня** (16 ч).
**Variant B: 0.5 дня** (4 ч).
**Default plan:** B сейчас, A — в backlog как post-v2.0.

### Dependencies
None.

---

## Phase 09: ThinRuntime tools immutability + runtime_hints

**Goal:** Убрать leaky abstraction — `ThinRuntime.run()` мутирует `active_tools` (line 289-308).

**Why now:** контракт `AgentRuntime.run()` говорит "tools передаются перед run". Текущая реализация добавляет MCP/subagent specs внутри run — race condition risk + нарушение контракта.

### DoD (SMART)
- [ ] `RuntimeConfig` расширен полем `runtime_hints: RuntimeHints | None = None`
- [ ] `RuntimeHints` (frozen dataclass): `additional_tools: tuple[ToolSpec, ...] = ()`, `additional_mcp_servers: tuple[McpServerSpec, ...] = ()`
- [ ] `ThinRuntime._build_tool_list()` собирает финальный список из `active_tools + runtime_hints.additional_tools` **до** вызова LLM, не во время
- [ ] Удалена in-flight мутация `active_tools` в `runtime/thin/runtime.py:289-308`
- [ ] Добавлен contract test: `tests/contract/test_runtime_tools_immutability.py`:
  ```python
  async def test_thin_runtime_does_not_mutate_active_tools(thin_runtime):
      tools = (ToolSpec(name="x", ...),)
      original = list(tools)
      async for _ in thin_runtime.run(messages=..., active_tools=tools, ...): pass
      assert list(tools) == original  # tuple immutable, but no in-place mutation
  ```
- [ ] Тот же contract test применён к `claude_sdk` и `deepagents` runtimes (parametrize)

### TDD plan
1. Contract test (parametrized по runtime) — red
2. Refactor ThinRuntime — green
3. Проверить claude_sdk + deepagents — должны проходить (вероятно, и так не мутируют)

### Files affected
- `src/swarmline/runtime/types.py` (`RuntimeConfig`, `RuntimeHints`)
- `src/swarmline/runtime/thin/runtime.py`
- `src/swarmline/runtime/thin/_helpers.py` (новый `_build_tool_list`)
- `tests/contract/test_runtime_tools_immutability.py` (создать)
- `tests/contract/__init__.py`

### Edge cases
- Backwards compat: старые `ThinRuntime(...)` без `runtime_hints` → `runtime_hints=None` → старое поведение через явный путь
- Performance: tuple concatenation — O(n+m), приемлемо для tools (<100)

### Verification
```bash
pytest tests/contract/ -v
pytest tests/integration/test_thin_runtime*.py -v
```

### Estimate
**1 день** (8 ч).

### Dependencies
**Hard:** None.

---

# SPRINT C — Security & Tests

## Phase 10: hmac.compare_digest auth + auth tests

**Goal:** Защита bearer auth от timing attacks.

**Why now:** `serve/app.py:26-54` сравнивает токен через `==` — leaks длину/совпадение по таймингам; OWASP-критично.

### DoD (SMART)
- [ ] `_BearerAuthMiddleware._verify_token()` использует `hmac.compare_digest(provided, expected)` вместо `==`
- [ ] Token storage: env var `SWARMLINE_AUTH_TOKEN` или явный `auth_token` в `create_app(auth_token=...)`
- [ ] Если `auth_token` not set И `allow_unauthenticated_query=False` → `create_app()` бросает `ConfigError("auth_token required when allow_unauthenticated_query=False")`
- [ ] Логирование auth-failures в `structlog` с уровнем WARNING + IP (`request.client.host`)
- [ ] Rate limiting на `/v1/query`: 60 запросов/минуту/IP via `slowapi` или встроенная in-memory limiter
- [ ] Тесты:
  - `tests/security/test_auth_timing_attack.py` — measure variance с `time.perf_counter`, проверить что `compare_digest` использован (через `mock.patch("hmac.compare_digest")` + assert called)
  - `tests/security/test_auth_missing_token.py` — `create_app()` без token + `allow_unauthenticated_query=False` → ConfigError
  - `tests/security/test_auth_rate_limit.py` — 61-й запрос за минуту → 429

### TDD plan
1. Все 3 теста — red
2. Implementation: `hmac.compare_digest`, ConfigError, rate limiter
3. Green

### Files affected
- `src/swarmline/serve/app.py`
- `src/swarmline/serve/middleware.py` (новый файл, или extend existing)
- `tests/security/test_auth_*.py` (3 файла, создать)
- `pyproject.toml` (если slowapi → optional dep)

### Edge cases
- `slowapi` опциональная зависимость → если не установлена, fallback на in-memory dict с TTL
- Rate limit для health check НЕ применяется (`/v1/health` всегда 200)

### Verification
```bash
pytest tests/security/test_auth_*.py -v
ty check src/swarmline/serve/
```

### Estimate
**0.75 дня** (6 ч).

### Dependencies
**Hard:** Phase 05 (нужен `ConfigError` из новой иерархии).

---

## Phase 11: Security test suite expansion 1 → 30+

**Goal:** Покрыть 8 security-категорий минимум 4 тестами каждая.

**Why now:** для фреймворка с sandbox/permissions/multi-agent текущий 1 тест неприемлем.

### DoD (SMART)
- [ ] **`tests/security/`** содержит минимум **30 функций** в **8 категориях**:
  1. **SSRF & DNS** (`test_ssrf_*.py`): URL→IP resolution, metadata blocking, DNS rebinding, redirect chains, http→https mismatch (≥4 тестов)
  2. **Path traversal** (`test_path_*.py`): `..`, symlinks, NUL bytes, unicode normalization, Windows separators (≥4)
  3. **Tool policy** (`test_tool_policy_*.py`): default-deny, case-sensitivity, MCP override, allowed_skills inheritance (≥4)
  4. **Sandbox escape** (`test_sandbox_*.py`): docker network=none, cap_drop, mem_limit, host_exec=False (≥4)
  5. **Auth & secrets** (`test_auth_*.py`): timing attack, missing token, rate limit, secret redaction в логах (≥4)
  6. **Prompt injection** (`test_prompt_injection_*.py`): system override, tool poisoning, instruction smuggling, multi-turn jailbreak (≥4)
  7. **Multi-agent governance** (`test_governance_*.py`): max_agents, max_depth, can_hire violation, capability escalation (≥4)
  8. **A2A & inter-process** (`test_a2a_*.py`): auth_token required, request size limit, replay protection (≥3)
- [ ] Каждый тест имеет docstring с **CWE/OWASP id** где применимо
- [ ] CI gate: `pytest tests/security/ -v` — must be green
- [ ] Coverage `tests/security/` → ≥85% для соответствующих исходников
- [ ] Создан `docs/security/threat-model.md` — категория → угроза → митигация → тест

### TDD plan
1. Создать пустые файлы `test_*.py` с failing assertion (red)
2. Имплементировать тесты по категориям
3. При обнаружении реальных уязвимостей — фиксы кода

### Files affected
- `tests/security/test_ssrf_*.py` (4 файла)
- `tests/security/test_path_*.py`
- `tests/security/test_tool_policy_*.py`
- `tests/security/test_sandbox_*.py`
- `tests/security/test_auth_*.py` (созданы в Phase 10)
- `tests/security/test_prompt_injection_*.py`
- `tests/security/test_governance_*.py`
- `tests/security/test_a2a_*.py`
- `docs/security/threat-model.md` (создать)

### Edge cases
- Prompt injection тесты — proxy через mock LLM, не реальные API ключи
- Sandbox тесты с Docker — `@pytest.mark.requires_docker`, skip в CI без Docker daemon

### Verification
```bash
pytest tests/security/ -v --tb=short
echo "тест функций: $(pytest tests/security/ --collect-only -q | grep -c '::test_')"
# ≥ 30
```

### Estimate
**3 дня** (24 ч). Самая трудозатратная фаза в Sprint C.

### Dependencies
**Hard:** Phase 10 (auth tests).
**Soft:** Phase 05 (typed errors для `pytest.raises`).

---

## Phase 12: Integration tests refactor (remove MagicMock)

**Goal:** Integration tests = реальные in-memory deps + только LLM мокирован.

**Why now:** Project rule violation — `tests/integration/` содержит 176 строк `MagicMock`, что нарушает правило "интеграция = реальные зависимости".

### DoD (SMART)
- [ ] `grep -rn "MagicMock\|AsyncMock" tests/integration/ | grep -v "fake_llm\|mock_provider"` → **≤ 0 строк**
- [ ] Допустимое исключение: моки **только для LLM-провайдеров** (`fake_anthropic`, `fake_openai_client`) с явным naming `fake_*` или `stub_*`
- [ ] Все `MemoryProvider` → используют `InMemoryMemoryProvider` или `SQLiteMemoryProvider(":memory:")`
- [ ] Все `Sandbox` → `LocalSandboxProvider` с tempdir
- [ ] Все `WebProvider` → реальный `HttpxWebProvider` с `respx` для mock HTTP responses (не MagicMock)
- [ ] Документ `tests/integration/CONVENTIONS.md` — what's mock-allowed, what's not
- [ ] Linter правило: `tests/integration/conftest.py` имеет fixture `_no_magicmock` autouse — fails on detection

### TDD plan
1. Создать `_no_magicmock` autouse fixture — все integration тесты падают
2. По одному файлу — заменять MagicMock на real impls
3. Зелёный pytest

### Files affected
- ~15 файлов в `tests/integration/` (то которые с MagicMock)
- `tests/integration/conftest.py`
- `tests/integration/CONVENTIONS.md` (создать)

### Edge cases
- LLM моки — оставлены, но переименованы в `fake_*` для явности
- HTTP — `respx` (или `httpx_mock`) для запросов, а не MagicMock провайдера

### Verification
```bash
pytest tests/integration/ -v
grep -rn "MagicMock\|AsyncMock" tests/integration/ | grep -v "fake_\|stub_" | wc -l
# = 0
```

### Estimate
**2 дня** (16 ч).

### Dependencies
None.

---

## Phase 13: E2E test suite expansion 7 → 30+

**Goal:** End-to-end coverage для full-stack scenarios.

**Why now:** только 7 E2E функций — критически мало для фреймворка.

### DoD (SMART)
- [ ] **`tests/e2e/`** содержит ≥**30 функций** в **6 сценариях**:
  1. **Single-agent full-flow** (≥5): query/stream/conversation × thin/claude_sdk/deepagents runtimes, structured output, retries, fallback
  2. **Multi-agent hierarchical** (≥5): `GraphBuilder` → 5-agent tree → delegate task → wait for all → result aggregation
  3. **Workflow with HITL** (≥4): `WorkflowGraph.add_interrupt` → pause → resume(human_input) → continue
  4. **Pipeline with budget gates** (≥4): 3-phase pipeline → trigger budget exceed → graceful failure
  5. **Memory persistence cross-session** (≥4): SQLite/Postgres → write session 1 → reload → session 2 reads → assert continuity
  6. **A2A inter-agent** (≥4): два swarmline процесса → SwarmlineA2AAdapter → message exchange → assert delivery
  7. **Tool execution full-flow** (≥4): `@tool` → registered → called by LLM → output validated → policy check → audit log
- [ ] CI: nightly `live` job — те же тесты с `@pytest.mark.live` на реальных Anthropic/OpenAI keys
- [ ] Каждый тест выполняется в <30 секунд (с моками); live job — <10 минут

### TDD plan
1. Заглушки `test_*.py` с `pytest.skip` на основе TODO — позволяет постепенно
2. Имплементация по сценариям
3. Каждый сценарий имеет swarmline-prod-like setup

### Files affected
- `tests/e2e/test_single_agent_*.py` (5 файлов)
- `tests/e2e/test_multi_agent_*.py` (5)
- `tests/e2e/test_workflow_hitl_*.py` (4)
- `tests/e2e/test_pipeline_budget_*.py` (4)
- `tests/e2e/test_memory_persistence_*.py` (4)
- `tests/e2e/test_a2a_*.py` (4)
- `tests/e2e/test_tool_full_flow_*.py` (4)
- `.github/workflows/nightly-live.yml` (создать — live tests)

### Edge cases
- A2A тесты с двумя процессами — pytest fixture spawn'ит subprocess, teardown убивает
- Postgres E2E — `@pytest.mark.requires_postgres`, fixture с `testcontainers-python` или skip если PG_DSN env не задан

### Verification
```bash
pytest tests/e2e/ -v --tb=short
echo "E2E функций: $(pytest tests/e2e/ --collect-only -q | grep -c '::test_')"
# ≥ 30
```

### Estimate
**3 дня** (24 ч).

### Dependencies
**Hard:** Phases 5, 6, 7 (тесты используют новые errors, types, config).

---

# SPRINT D — Operational Maturity

## Phase 14: Daemon module implementation

**Goal:** Production daemon mode для 24/7 autonomous operation.

**Why now:** `DAEMON-PLAN.md` (335 строк) есть, но код = stub. Без daemon фреймворк не годится для long-running production agents.

### DoD (SMART)
- [ ] Реализовано **5 модулей** согласно `DAEMON-PLAN.md`:
  - `src/swarmline/daemon/runner.py` — main async loop с graceful shutdown (SIGTERM/SIGINT)
  - `src/swarmline/daemon/scheduler.py` — task scheduling (interval, cron, on-demand) — uses `apscheduler` или встроенный async scheduler
  - `src/swarmline/daemon/health.py` — health/readiness probes (HTTP `/health`, `/ready`)
  - `src/swarmline/daemon/pid.py` — PID file management, lock detection
  - `src/swarmline/daemon/config.py` — DaemonConfig (port, workers, log_dir, …)
- [ ] CLI: `swarmline daemon start --config daemon.yaml`, `swarmline daemon stop`, `swarmline daemon status`
- [ ] Graceful shutdown: SIGTERM → 30s timeout → cancel running tasks → flush logs → exit 0
- [ ] Logging: rotating file logs (`structlog` + `RotatingFileHandler` 100MB × 10 files)
- [ ] **systemd unit file** `deploy/systemd/swarmline.service` — production deployment template
- [ ] **Docker image** `Dockerfile.daemon` — multi-stage build (~150MB)
- [ ] Тесты:
  - `tests/integration/test_daemon_runner.py` — start → request → graceful stop
  - `tests/integration/test_daemon_health.py` — `/health` + `/ready` корректны
  - `tests/integration/test_daemon_pid_lock.py` — двойной запуск → второй fail с ясным ERROR
  - `tests/e2e/test_daemon_e2e.py` — полный цикл systemd-style (start/reload/stop)
- [ ] Документация `docs/deployment.md` (создать) — systemd, Docker, k8s

### TDD plan
1. Сначала контрактные тесты (`Daemon.start/stop/status`) — red
2. PID lock — red, потом impl
3. Health endpoint — red, потом impl
4. Scheduler — red, потом impl
5. Runner — связывает всё, last

### Files affected
- `src/swarmline/daemon/__init__.py`
- `src/swarmline/daemon/runner.py`
- `src/swarmline/daemon/scheduler.py`
- `src/swarmline/daemon/health.py`
- `src/swarmline/daemon/pid.py`
- `src/swarmline/daemon/config.py`
- `src/swarmline/cli/commands/daemon_cmd.py` (создать)
- `deploy/systemd/swarmline.service`
- `Dockerfile.daemon`
- `tests/integration/test_daemon_*.py` (4 файла)
- `tests/e2e/test_daemon_e2e.py`
- `docs/deployment.md`
- `pyproject.toml` (если apscheduler → optional dep)

### Edge cases
- Multiple workers: `workers > 1` — каждый process с своим PID, master tracker
- Reload без downtime: SIGHUP → re-read config → graceful restart workers
- Crashes: child process restart с exponential backoff (max 5 attempts in 60s window)

### Verification
```bash
pytest tests/integration/test_daemon_*.py tests/e2e/test_daemon_e2e.py -v
swarmline daemon start --config tests/fixtures/daemon.yaml &
sleep 2
curl http://localhost:8800/health  # → {"status": "ok"}
swarmline daemon stop
```

### Estimate
**3 дня** (24 ч). Most complex phase в Sprint D.

### Dependencies
**Hard:** Phase 05 (`SwarmlineError` для daemon errors).

---

## Phase 15: Prometheus metrics endpoint

**Goal:** Production monitoring через Prometheus.

**Why now:** структурированные logs + OTel есть, но нет агрегированных метрик. SRE-команды используют Prometheus как стандарт.

### DoD (SMART)
- [ ] `src/swarmline/observability/metrics.py` — модуль с метриками (`prometheus_client`):
  - **Counters:**
    - `swarmline_llm_calls_total{provider, model, status}`
    - `swarmline_tool_calls_total{tool_name, status}`
    - `swarmline_agent_spawned_total{role}`
    - `swarmline_errors_total{kind, recoverable}`
    - `swarmline_budget_exceeded_total{config_id}`
  - **Histograms:**
    - `swarmline_llm_latency_seconds{provider, model}` — buckets [0.1, 0.5, 1, 2, 5, 10, 30]
    - `swarmline_tool_duration_seconds{tool_name}`
  - **Gauges:**
    - `swarmline_active_agents` — текущее число живых
    - `swarmline_budget_remaining_usd{config_id}`
- [ ] Endpoint `/metrics` в `serve/app.py` (доступен без auth) → text/plain Prometheus format
- [ ] CLI: `swarmline daemon` exposes metrics на отдельном порту (default 9100)
- [ ] `MetricsCollector` подписан на `EventBus` — конвертирует events → метрики, no overhead в hot path
- [ ] `docs/observability.md` дополнен разделом "Prometheus" + sample Grafana dashboard JSON в `deploy/grafana/`
- [ ] Тесты:
  - `tests/integration/test_metrics_collector.py` — emit event → assert metric incremented
  - `tests/integration/test_metrics_endpoint.py` — GET /metrics → 200 + parseable

### TDD plan
1. Contract test: `MetricsCollector.handle_event(LLMCallEvent)` → counter +=1 — red
2. Endpoint test — red
3. Grafana dashboard — manual

### Files affected
- `src/swarmline/observability/metrics.py` (создать)
- `src/swarmline/serve/app.py` (`/metrics` route)
- `pyproject.toml` (`prometheus_client>=0.20`)
- `deploy/grafana/swarmline-dashboard.json` (создать)
- `tests/integration/test_metrics_*.py`
- `docs/observability.md`

### Edge cases
- High-cardinality labels (`session_id`, `user_id`) — НЕ использовать как label
- Multi-process daemon — `prometheus_client.multiprocess` mode

### Verification
```bash
pytest tests/integration/test_metrics_*.py -v
curl http://localhost:9100/metrics | grep swarmline_
```

### Estimate
**1.5 дня** (12 ч).

### Dependencies
**Hard:** Phase 14 (daemon endpoint).

---

## Phase 16: OpenTelemetry parent-child + provider in span name

**Goal:** Distributed tracing для multi-agent цепочек.

**Why now:** OTelExporter emit'ит spans, но нет parent-child relationship для иерархических spawn'ов; имена spans `swarmline.llm.{model}` не группируются по provider.

### DoD (SMART)
- [ ] Span naming: `swarmline.llm.{provider}.{model}` (anthropic.claude-sonnet, openai.gpt-4, …)
- [ ] Parent-child links для multi-agent:
  - `Agent.query()` → root span
  - `agent.delegate(child)` → child span с `parent_span_id` = root
  - `tool_call` → child span текущего LLM span
- [ ] OTel context propagation через `RuntimeEvent` (`event.trace_context: TraceContext | None`)
- [ ] Тесты:
  - `tests/integration/test_otel_parent_child.py` — assert child span имеет правильный parent_id
  - `tests/integration/test_otel_span_naming.py` — все 4 provider правильно отражены в имени
- [ ] `examples/28_opentelemetry_tracing.py` обновлён — показывает hierarchy (Jaeger UI screenshot в docs)
- [ ] `docs/observability.md` дополнен — OTel настройка для Jaeger/Tempo/Honeycomb

### TDD plan
1. Test: `mock_tracer = MockTracer()` → spawn 3-agent hierarchy → assert spans[1].parent_id == spans[0].span_id — red
2. Implementation в OTelExporter
3. Green

### Files affected
- `src/swarmline/observability/otel_exporter.py`
- `src/swarmline/runtime/types.py` (`RuntimeEvent.trace_context`)
- `src/swarmline/multi_agent/graph_orchestrator.py` (propagate context)
- `examples/28_opentelemetry_tracing.py`
- `tests/integration/test_otel_*.py`
- `docs/observability.md`

### Edge cases
- Parallel spawns — все имеют один parent
- Missing parent context (root agent) — `parent_id = None`, span = root

### Verification
```bash
pytest tests/integration/test_otel_*.py -v
python examples/28_opentelemetry_tracing.py
# Проверить в OTel Collector что spans с правильными parent_id
```

### Estimate
**1 день** (8 ч).

### Dependencies
**Hard:** Phase 14 (daemon).

---

## Phase 17: K8s + production deployment artifacts

**Goal:** Out-of-the-box deployable на Kubernetes.

**Why now:** enterprise adoption требует helm chart / kustomize / готовых templates.

### DoD (SMART)
- [ ] `deploy/kubernetes/`:
  - `deployment.yaml` — 3 replicas, resource limits (1 CPU / 2GB RAM default), liveness/readiness probes
  - `service.yaml` — ClusterIP для daemon API + Prometheus
  - `configmap.yaml` — DaemonConfig template
  - `secret.yaml.example` — API keys template
  - `hpa.yaml` — HorizontalPodAutoscaler (CPU 70%)
  - `prometheus-monitor.yaml` — ServiceMonitor для Prometheus Operator
- [ ] `deploy/helm/swarmline/` — Helm chart (Chart.yaml, values.yaml, templates/)
- [ ] `Dockerfile` — multi-stage, distroless final image, non-root user
- [ ] `docker-compose.yaml` для локальной отладки (swarmline + Postgres + Prometheus + Grafana)
- [ ] `docs/deployment.md` дополнен: K8s, Helm, Docker Compose, systemd
- [ ] CI: smoke test `kubectl apply -f deploy/kubernetes/` на kind cluster в GitHub Actions

### TDD plan
N/A — infrastructure. Smoke test через `kubectl apply --dry-run=server`.

### Files affected
- `deploy/kubernetes/*.yaml` (6 файлов)
- `deploy/helm/swarmline/` (Helm chart)
- `Dockerfile`
- `docker-compose.yaml`
- `docs/deployment.md`
- `.github/workflows/k8s-smoke.yml`

### Edge cases
- Image размер — distroless должен быть <200MB
- Helm values — secret refs через ExternalSecrets/SealedSecrets, не plaintext

### Verification
```bash
docker build -f Dockerfile.daemon -t swarmline:dev .
docker-compose up -d  # → all services healthy
kubectl apply --dry-run=client -f deploy/kubernetes/
helm lint deploy/helm/swarmline/
```

### Estimate
**1.5 дня** (12 ч).

### Dependencies
**Hard:** Phase 14, 15.

---

# SPRINT E — Documentation & DX Polish

## Phase 18: mkdocstrings auto-generated API reference

**Goal:** Один источник истины — docstrings в коде.

**Why now:** `mkdocstrings` настроен в `mkdocs.yml:109-122`, но `docs/api/agent.md` = 310 байт (заглушка); ручной `api-reference.md` (20KB) устаревает без CI-валидации.

### DoD (SMART)
- [ ] Все файлы в `docs/api/*.md` заменены на 1-line `::: swarmline.<module>` директивы для mkdocstrings
- [ ] Удалены все ручные API descriptions из `api-reference.md` — заменены на автогенерированный
- [ ] **Все public docstrings** (Agent, AgentConfig, tool, Result, Conversation, GraphBuilder, WorkflowGraph, …) **дополнены примерами** в Google-style:
  ```python
  class Agent:
      """High-level facade for AI agent.
      
      Examples:
          Quick start:
          >>> agent = Agent(AgentConfig(system_prompt="You are helpful.", runtime="thin"))
          >>> result = await agent.query("Capital of France?")
          >>> print(result.text)
          'Paris.'
      """
  ```
- [ ] Coverage docstrings: `pydocstyle src/swarmline/agent/` + `src/swarmline/__init__.py` exports → ≥95% покрыто docstring
- [ ] CI step: `mkdocs build --strict` — fail при missing references
- [ ] Site опубликован на ReadTheDocs/GitHub Pages

### TDD plan
N/A — docs. Smoke test: `mkdocs build` → 0 warnings.

### Files affected
- `docs/api/agent.md`, `docs/api/runtime.md`, `docs/api/protocols.md`, `docs/api/memory.md`, … (все)
- `docs/api-reference.md` — большая чистка
- `src/swarmline/agent/agent.py`, `config.py`, `result.py`, `conversation.py` — docstrings с examples
- `src/swarmline/multi_agent/graph_builder.py`, `multi_agent/graph_orchestrator.py`
- `mkdocs.yml` (если нужно — strict mode)
- `.github/workflows/docs.yml` (build на каждый PR)

### Edge cases
- Optional deps: `langchain` — mkdocstrings нужно вижу `from langchain import …` без падения. Использовать `paths: [src]` + autocomplete optional через `try/except`
- Russian docstrings → English (фреймворк публичный)

### Verification
```bash
mkdocs build --strict
echo "API doc files: $(find docs/api -name '*.md' | wc -l) > 0"
```

### Estimate
**1 день** (8 ч).

### Dependencies
**Hard:** Phase 03 (top-level exports — для autodoc).

---

## Phase 19: Troubleshooting + Error Catalog + Runtime Decision Tree

**Goal:** Документация уровня FastAPI — actionable.

**Why now:** **Top-3 docs gap** из аудита. Без этого разработчик застревает на любой ошибке.

### DoD (SMART)
- [ ] **`docs/troubleshooting.md`** — top-15 issues с recovery:
  1. "ImportError: cannot import X" → причина + 2 решения
  2. "Agent.query() возвращает empty Result" → причина (часто — нет ANTHROPIC_API_KEY)
  3. "RateLimitError при первом запросе" → backoff, fallback model
  4. "TokenLimitError" → context compaction или модель с большим контекстом
  5. "ToolPolicyDenied: Bash" → как добавить tool в policy
  6. "BudgetExceededError" → как increment budget или fallback
  7. "Multiple agents stuck" → max_agents check, deadlock detection
  8. "MCP server timeout" → debugging + увеличение timeout
  9. "SQLite locked" → check_same_thread настройки
  10. "Postgres connection pool exhausted" → tuning
  11. "OTel spans не появляются" → endpoint + insecure flag
  12. "Conversation losing context" → MessageStore TTL
  13. "Tool decorator: invalid schema" → type hints проверка
  14. "Streaming зависает" → cancellation patterns
  15. "Daemon не стартует" → PID lock + logs
- [ ] **`docs/errors.md`** — полная таблица: error class → когда raised → fields → 2 recovery actions
- [ ] **`docs/runtime-selection.md`** — decision tree (mermaid):
  ```mermaid
  graph TD
      A[Start] -->|simple agents, multi-provider| B[thin]
      A -->|need Claude SDK features| C[claude_sdk]
      A -->|LangChain ecosystem| D[deepagents]
      A -->|OpenAI / Codex| E[cli]
  ```
- [ ] **`docs/common-mistakes.md`** — 10 типовых ошибок начинающего (5 строк каждая)
- [ ] Cross-references: каждая страница в Build/Recipes секциях ссылается на Troubleshooting/Errors где relevant
- [ ] Search-индекс mkdocs Material покрывает новые страницы

### TDD plan
N/A — docs.

### Files affected
- `docs/troubleshooting.md` (создать, ~500 строк)
- `docs/errors.md` (создать, ~300 строк — может авто-генерироваться из docstrings)
- `docs/runtime-selection.md` (создать, ~150 строк)
- `docs/common-mistakes.md` (создать, ~200 строк)
- `mkdocs.yml` (nav обновить)

### Edge cases
- Errors auto-gen — script `scripts/build_error_catalog.py` парсит `errors.py` + docstrings → `docs/errors.md`

### Verification
```bash
mkdocs build --strict
# Manual review: full read-through
```

### Estimate
**2 дня** (16 ч).

### Dependencies
**Hard:** Phase 05 (errors hierarchy для error catalog).

---

## Phase 20: Performance + Production Hardening guides

**Goal:** Operational excellence guides.

**Why now:** аудит выявил полное отсутствие SLO/SLA defaults и performance tuning.

### DoD (SMART)
- [ ] **`docs/performance-tuning.md`**:
  - Token budget стратегии (compaction, summarization)
  - Cost optimization (model selection, batching, fallback chains)
  - Latency: streaming, parallel tool calls, response caching
  - Memory: connection pool sizing для Postgres
  - Конкретные numbers: typical p95 latency для thin runtime → 1.2s; для claude_sdk → 3.5s
- [ ] **`docs/production-hardening-checklist.md`** — 15-item checklist:
  - [ ] auth_token set в env
  - [ ] `allow_unauthenticated_query=False`
  - [ ] `enable_host_exec=False` (если не нужно)
  - [ ] `max_budget_usd` set
  - [ ] Tool policy: только нужные tools allowed
  - [ ] Rate limiting на /v1/query
  - [ ] TLS terminator (reverse proxy + Let's Encrypt)
  - [ ] OTel collector configured
  - [ ] Prometheus metrics scraped
  - [ ] Sentry/error tracking
  - [ ] Log retention policy
  - [ ] Database backups (Postgres)
  - [ ] Resource limits в K8s
  - [ ] Network policies (egress whitelist)
  - [ ] Secret rotation policy
- [ ] **`docs/slo-sla-defaults.md`** — рекомендованные пороги:
  - p95 latency < 5s
  - error rate < 1%
  - availability > 99.5%
  - cost per request < $0.05
- [ ] **`docs/cost-optimization.md`** — patterns: model fallback, prompt caching (Anthropic), batch API

### TDD plan
N/A — docs. Manual review.

### Files affected
- `docs/performance-tuning.md` (создать)
- `docs/production-hardening-checklist.md` (создать)
- `docs/slo-sla-defaults.md` (создать)
- `docs/cost-optimization.md` (создать)
- `mkdocs.yml` (nav)

### Edge cases
- Numbers (latency, cost) — based on benchmarks; запустить `benchmarks/` и зафиксировать в docs

### Verification
```bash
mkdocs build --strict
```

### Estimate
**1 день** (8 ч).

### Dependencies
**Soft:** Phase 15 (metrics для measuring real numbers).

---

## Phase 21: CI validates examples

**Goal:** Примеры не устаревают.

**Why now:** 32 примера могут быть broken после refactors; нет автоматической проверки.

### DoD (SMART)
- [ ] `tests/examples/test_examples_runnable.py` — параметризованный по всем `examples/*.py`:
  - Stub LLM responses (mock anthropic/openai/google)
  - `python examples/<file>.py` — должен exit 0
  - Time limit 30s per example
- [ ] CI step: `pytest tests/examples/ -v` — green required
- [ ] Каждый пример имеет header `# RUNS WITH MOCK LLM (no API keys needed)` или `# REQUIRES ANTHROPIC_API_KEY`
- [ ] Примеры с реальными API keys → `@pytest.mark.live` нигде не упоминаются в default `pytest`

### TDD plan
1. `test_examples_runnable.py` — параметризован, изначально все пропускают
2. Заполнить mock fixture для LLM, по одному примеру делать runnable
3. Green на всех 32

### Files affected
- `tests/examples/test_examples_runnable.py` (создать)
- `tests/examples/conftest.py` (mock fixtures)
- `examples/<various>.py` — некоторые примеры могут потребовать упрощения для runnable
- `.github/workflows/ci.yml` (новый step)

### Edge cases
- Async examples — `asyncio.run()` обёртка
- Examples с user input → пропустить (mark.skip с reason "interactive only")

### Verification
```bash
pytest tests/examples/ -v
echo "Examples: $(ls examples/*.py | wc -l), runnable: $(pytest tests/examples/ --collect-only -q | grep -c '::test_')"
```

### Estimate
**1 день** (8 ч).

### Dependencies
**Soft:** Phase 03 (top-level exports — примеры обновлены).

---

# SPRINT F — Multi-agent Completeness (OPTIONAL)

## Phase 22: Native handoff API

**Goal:** OpenAI-Swarm-style `agent.handoff(target)` без эмуляции.

**Why now:** аудит выявил отсутствующий паттерн; для полноты multi-agent коллекции.

### DoD (SMART)
- [ ] `Agent.handoff(target_agent_id: str, message: str | None = None) -> HandoffResult` — публичный метод
- [ ] `HandoffResult` (frozen DC): `accepted: bool, target: str, reason: str | None`
- [ ] `RuntimeEvent.kind = "handoff"` — новый event type
- [ ] LLM может вызвать `__handoff__` tool → runtime обрабатывает → передаёт control + context
- [ ] `examples/34_handoff_pattern.py` — triage agent → specialist (billing/tech/sales)
- [ ] `tests/integration/test_handoff.py` — context preservation, max_handoff_depth (anti-loop)
- [ ] `docs/multi-agent.md` — раздел "Handoff pattern"

### TDD plan
1. Contract test: `Agent.handoff()` → returns HandoffResult — red
2. Tool registration: `__handoff__` в active_tools — red
3. Runtime processes handoff event — green progressively

### Files affected
- `src/swarmline/agent/agent.py` (`.handoff()`)
- `src/swarmline/multi_agent/handoff.py` (создать)
- `src/swarmline/runtime/types.py` (`HandoffEvent`)
- `src/swarmline/runtime/thin/runtime.py` (handle handoff)
- `examples/34_handoff_pattern.py` (создать)
- `tests/integration/test_handoff.py`
- `docs/multi-agent.md`

### Edge cases
- Loop prevention: `max_handoff_depth=5` default
- Target not found → `HandoffResult(accepted=False, reason="agent_not_registered")`

### Verification
```bash
pytest tests/integration/test_handoff.py -v
python examples/34_handoff_pattern.py
```

### Estimate
**1.5 дня** (12 ч).

### Dependencies
**Hard:** Phase 05, 09.

---

## Phase 23: Critique / reflection orchestrator

**Goal:** Built-in self-improvement через critique loop.

### DoD (SMART)
- [ ] `CritiqueOrchestrator` (новый класс в `orchestration/`):
  - `async def run(prompt, draft_agent, critic_agent, max_iterations=3) -> CritiqueResult`
  - Loop: draft → critique → revise → critique-stop-condition
- [ ] `CritiqueResult`: `final_text, iterations, history: tuple[CritiqueIteration, ...]`
- [ ] `examples/35_reflection_pattern.py` — writer + editor
- [ ] `tests/integration/test_critique_orchestrator.py`
- [ ] `docs/multi-agent.md` — раздел "Reflection pattern"

### Estimate
**1 день** (8 ч).

### Dependencies
**Soft:** Phase 22.

---

## Phase 24: VotingOrchestrator (consensus)

**Goal:** Multi-model voting / consensus pattern.

### DoD (SMART)
- [ ] `VotingOrchestrator`:
  - `async def run(prompt, voters: list[Agent], strategy: Literal["majority", "unanimous", "weighted"]) -> VotingResult`
- [ ] `VotingResult`: `winner, votes: dict[Agent, str], confidence: float`
- [ ] `examples/36_voting_pattern.py` — Claude vs GPT-4 vs Gemini → consensus
- [ ] `tests/integration/test_voting_orchestrator.py`

### Estimate
**1 день** (8 ч).

### Dependencies
**Soft:** Phase 22, 23.

---

# 4. Risk Register

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| 1 | `ty` в strict mode (75 ошибок) — рефакторинг провоцирует regression | **High** | Phase 01 — атомарные коммиты по 5-10 errors с тестами; CI gate |
| 2 | `AgentConfig` split (Phase 07) ломает 200+ usages в тестах/примерах | **High** | Backwards compat через `__post_init__` + DeprecationWarning; миграция `examples/` инкрементально |
| 3 | Daemon (Phase 14) — недооценка сложности (signal handling, multi-process) | **Med** | DAEMON-PLAN.md уже есть; начать с single-worker MVP |
| 4 | E2E tests (Phase 13) с двумя процессами для A2A — flaky | **Med** | Использовать `pytest-asyncio`, `respx` для HTTP, deterministic seeds |
| 5 | Documentation refactor (Phase 18, 19) — большой объём, легко закопаться | **Med** | Time-box каждый под-документ 2 ч; шаблоны заранее |
| 6 | Postgres E2E тесты (Phase 13) требуют CI infra | **Low** | `testcontainers-python` + GitHub Actions services |
| 7 | Sprint F (handoff/critique/voting) — может быть отложен | **Low** | Optional sprint; v2.0 без них допустим |
| 8 | Backwards compat для error hierarchy (Phase 05) | **Med** | re-export старых имён + 2 версии deprecation cycle |

---

# 5. Success Metrics (как измерить v2.0)

| Metric | Before (v1.4.1) | After (v2.0) | Source |
|---|---|---|---|
| `ty check src/` diagnostics | 75 | **0** | Phase 01 |
| Coverage overall | not tracked | **≥85%** | Phase 02 |
| Coverage core | not tracked | **≥95%** | Phase 02 |
| Top-level exports count | 35 (из 50+ нужных) | **≥50** | Phase 03 |
| Dependency upper bounds | 0/3 core | **3/3 core** | Phase 04 |
| `SwarmlineError` subclasses | 0 (нет иерархии) | **15+ под общим корнем** | Phase 05 |
| Domain → Infra import violations | 2+ | **0** | Phase 06 |
| `AgentConfig` базовых полей | 34 (mixed) | **8 + nested** | Phase 07 |
| Security tests | 1 функция | **≥30** | Phase 11 |
| Integration tests с MagicMock | ~176 строк | **0 (вне fake_llm)** | Phase 12 |
| E2E tests | 7 функций | **≥30** | Phase 13 |
| Daemon module | stub | **runner+scheduler+health+pid** | Phase 14 |
| Prometheus metrics | none | **/metrics endpoint + 12 metrics** | Phase 15 |
| OTel parent-child spans | implicit | **explicit hierarchy** | Phase 16 |
| K8s deployment artifacts | none | **kubernetes/ + helm + Dockerfile** | Phase 17 |
| Auto-generated API reference | manual stub | **mkdocstrings live** | Phase 18 |
| Troubleshooting / Error catalog | absent | **15+ entries each** | Phase 19 |
| Production-hardening checklist | absent | **15-item checklist** | Phase 20 |
| Examples validated in CI | no | **yes (32 examples)** | Phase 21 |

---

# 6. Verification Pipeline (запускается на каждом этапе)

```bash
# Quality gates (must all pass)
ty check src/swarmline/                     # 0 diagnostics
ruff check src/ tests/                      # 0 violations
ruff format --check src/ tests/             # formatted
pytest -m "not live" --cov=swarmline \
       --cov-fail-under=85                  # coverage ≥85%
pytest tests/architecture/ -v               # layering OK
pytest tests/contract/ -v                   # contracts OK
pytest tests/security/ -v                   # security tests green
mkdocs build --strict                       # docs valid

# Integration smoke (per-sprint)
pytest tests/integration/ -v                # all green
pytest tests/e2e/ -v                        # all green

# Live (nightly only)
pytest -m live -v                            # real LLM calls
```

---

# 7. Branching strategy (по правилам проекта)

```
main (always green, releasable)
  ├── feat/v2-phase01-ty-strict          ← Sprint A
  ├── feat/v2-phase02-coverage-baseline
  ├── feat/v2-phase03-top-level-exports
  ├── feat/v2-phase04-dep-upper-bounds
  ├── feat/v2-phase05-error-hierarchy
  ├── feat/v2-phase06-domain-cleanup     ← Sprint B
  ├── feat/v2-phase07-agentconfig-split
  ├── ...
  └── release/v2.0.0                      ← когда все фазы зелёные
```

**Worktree parallelism:** фазы 4, 5, 6, 9 — независимы → можно параллельно через `git worktree add ../worktree-phaseNN`.

---

# 8. Rollout & Release

1. **v2.0.0-beta1** — после Sprint A+B (Phase 1-9) — публикация на TestPyPI, фидбек 1 неделя
2. **v2.0.0-beta2** — после Sprint C+D (Phase 10-17) — публикация на TestPyPI
3. **v2.0.0-rc1** — после Sprint E (Phase 18-21) — публикация на PyPI как pre-release
4. **v2.0.0** — после 2 недель stability в rc — публичный релиз
5. **v2.1.0** — Sprint F (Phase 22-24) — multi-agent completeness

**Deprecation policy для v1 → v2:**
- v2.0.x — старый flat `AgentConfig` работает с `DeprecationWarning`
- v2.1.0 — `DeprecationWarning` → `FutureWarning`
- v3.0.0 — flat config удалён

---

# 9. Out of Scope (явно НЕ в v2.0)

- ❌ UI (web playground / Streamlit dashboard) — backlog
- ❌ Полная RBAC (роли, права, JWT) — backlog v2.x
- ❌ Voice / multimodal native support
- ❌ Persistent agent memory across restarts (только session, не память) — backlog
- ❌ Visual workflow builder
- ❌ Hosted inference endpoint — отдельный проект

---

# 10. Sign-off Checklist (перед v2.0 GA)

- [ ] Все 21 phase из Sprint A-E завершены и merged в main
- [ ] All quality gates green в CI (ty, ruff, coverage, security, e2e)
- [ ] CHANGELOG обновлён с полным списком breaking changes
- [ ] Migration guide v1.4 → v2.0 опубликован
- [ ] Beta1, Beta2, RC1 прошли без critical issues
- [ ] PyPI Trusted Publishing настроен (OIDC)
- [ ] ReadTheDocs site опубликован, поиск работает
- [ ] Demo video (optional but recommended) для top-3 use cases
- [ ] Twitter/X + HN + Reddit launch posts подготовлены

---

**End of plan.**

Estimated total: **22 рабочих дня** of focused work (~4-5 календарных недель с buffer и code review).
