# Code Quality Review — swarmline v1.5.0

**Date:** 2026-04-27
**Scope:** `src/swarmline/` (387 .py files, 52 980 LOC) + `tests/` (382 .py files, 85 844 LOC)
**Reviewer:** Code Reviewer subagent
**Prior known:** S4 KISS empty wrapper in orchestration (deferred to v1.5.1); post-audit cleanup C1+C2+C4 already shipped.

## Executive Summary

- **Overall code health:** ⚠️ Healthy core, with three recurring debt clusters that should land in v1.5.1 / v1.6.0.
- **Top 3 strengths:**
  1. **Domain layer is genuinely clean** — `protocols/`, `domain_types.py`, `memory/types.py` import only stdlib + sibling domain files. ISP is enforced (every Protocol in `protocols/` has ≤5 methods).
  2. **Public API is curated** — `__all__` in `swarmline/__init__.py` exposes 12 names; everything else stays accessible but does not leak through `import *`.
  3. **Hygiene markers are clean** — 0 `TODO/FIXME/HACK/XXX` source comments, 0 bare `except:`, 0 mutable default args, no production `print()` outside CLI/daemon entrypoints.
- **Top 3 smells:**
  1. **Three "god" classes (~17 public methods each)** — `PostgresMemoryProvider`, `SQLiteMemoryProvider`, `ThinRuntime.__init__/run` — well past the SRP threshold. Already flagged in `CONCERNS.md`, not yet split.
  2. **DRY violations across persistence backends** — `SqlitePlanStore` ↔ `PostgresPlanStore` share three identical methods (`load`, `list_plans`, `update_step`); `agent.py` ↔ `runtime_dispatch.py` duplicate `build_tools_mcp_server` + `_adapt_handler` verbatim; `budget_store.py` has a duplicated `_emit_event`.
  3. **Application → Infrastructure leak** — `orchestration/workflow_executor.py:11` and `orchestration/thin_subagent.py:25` import the concrete `ThinRuntime` class instead of going through `RuntimeFactoryPort`/`RuntimePort`; same file imports `LocalSandboxProvider`. `agent/runtime_wiring.py:123` does the same.

---

## Critical Smells

None block the v1.5.0 release. The release gate (ty=0, 5452 tests green, ruff clean) is intact. All findings below are technical debt, not correctness/security blockers.

---

## SRP Violations

| File | Lines | Public Methods | Recommendation |
|------|------:|---------------:|----------------|
| `src/swarmline/memory/postgres.py` | 662 | 17 | Split `PostgresMemoryProvider` along the 8 protocols it implements (MessageStore / FactStore / SummaryStore / GoalStore / SessionStateStore / UserStore / PhaseStore / ToolEventStore). One class per store, sharing a thin `_PostgresSession` mixin. v1.6.0 candidate. |
| `src/swarmline/memory/sqlite.py` | 650 | 17 | Identical split. After both are split, the duplicated `_session()` helper goes into `memory/_shared.py` (already partially exists). |
| `src/swarmline/runtime/thin/runtime.py` | 636 | 3 | Already partially decomposed (helpers in `runtime_support.py`). The remaining work: extract `__init__` (143 L) into a `ThinRuntimeBuilder`/`ThinRuntimeAssembly`, and split `run()` (319 L) into a pipeline (`PreCallChecks → ModeDispatch → EventLoop → PostCallHooks`). The single class is fine for now; the two long methods are the real SRP debt. |
| `src/swarmline/multi_agent/graph_task_board_postgres.py` | 633 | 15 | 80 % shared logic with `graph_task_board_sqlite.py` (590 L). Already noted in `CONCERNS.md`. Path forward: move SQL-agnostic parts into `graph_task_board_shared.py` (file already exists; underused). |
| `src/swarmline/multi_agent/graph_task_board_sqlite.py` | 590 | 15 | Same as above. |
| `src/swarmline/agent/agent.py` | 581 | 8 | `Agent` class itself is well-shaped (8 public methods, ~3 of "different nature"). The size comes from helpers (`build_tools_mcp_server`, `_adapt_handler`, `apply_before_query`, `collect_stream_result`, `_RuntimeEventAdapter`, `_ErrorEvent`). Extract the event-adapter classes into `agent/event_adapters.py` and the result-collector into `agent/stream_collect.py`. Drops 100+ lines from the facade. |
| `src/swarmline/runtime/thin/llm_providers.py` | 558 | per-adapter 3-3-3 | Three adapters in one module is acceptable; if it grows past 700 lines, split per-provider. Watch item. |
| `src/swarmline/pipeline/budget_store.py` | 518 | 4-5-6 | Three classes, each cohesive. Acceptable; flagged only because `_emit_event` is duplicated. |
| `src/swarmline/cli/init_cmd.py` | 508 | 1 click cmd | False positive — 80 % of the file is template literals. Acceptable. |
| `src/swarmline/tools/builtin.py` | 503 | factory functions | Move from "one big factory module" to one file per tool family in v1.6.0. Low priority. |
| `src/swarmline/orchestration/thin_subagent.py` | 470 | per-class 1-7-1 | `ThinSubagentOrchestrator` (7 public methods) is on the boundary. Acceptable. |
| `src/swarmline/runtime/thin/react_strategy.py` | 431 | 1 (`run_react`, 389 L) | One single 389-line function. **The most obvious long-method violation in the repo.** Split into `_initial_call` / `_handle_tool_calls` / `_finalize` / `_react_loop_step` and re-compose. v1.6.0 priority. |

**Methods > 50 LOC:** 100 across the codebase. Top offenders:

| LOC | File | Function |
|----:|------|----------|
| 389 | `runtime/thin/react_strategy.py:36` | `run_react` |
| 319 | `runtime/thin/runtime.py:255` | `ThinRuntime.run` |
| 290 | `runtime/thin/conversational.py:30` | `run_conversational` |
| 218 | `mcp/_server.py:78` | `create_server` |
| 191 | `runtime/thin/planner_strategy.py:30` | `run_planner` |
| 187 | `multi_agent/graph_tools.py:18` | `create_graph_tools` |
| 186 | `agent/runtime_wiring.py:29` | `build_portable_runtime_plan` |
| 185 | `runtime/deepagents.py:77` | `DeepAgentsRuntime.run` |
| 178 | `context/builder.py:128` | `DefaultContextBuilder.build` |
| 160 | `runtime/thin/finalization.py:96` | `finalize_with_validation` |
| 152 | `pipeline/pipeline.py:165` | `_run_single_phase` |
| 143 | `runtime/thin/runtime.py:55` | `ThinRuntime.__init__` |

Across the three "strategy" runners (`run_react`, `run_conversational`, `run_planner`) there is ~870 lines of imperative orchestration sharing common shape (LLM call → optional tool execution → guardrail/budget post-processing). This is the single highest-value refactor target in the codebase.

---

## ISP Violations

| Protocol | Methods | Excess | Split Direction |
|----------|--------:|-------:|-----------------|
| `orchestration/coding_task_ports.py:CodingTaskBoardPort` | 7 | +2 | **Already documented as deliberate composition** in the docstring (lines 88–112): aggregates `GraphTaskBoard` (4) + `GraphTaskScheduler` (2) + backend `cancel_task` (1) for the runtime's single-parameter API. Underlying canonical protocols stay narrow. **Acceptable as-is**; ISP is preserved in `protocols/graph_task.py`. |

All 26 Protocols inside `src/swarmline/protocols/` are ISP-clean (≤5 methods each). All 67 Protocols outside `protocols/` (sub-package internal contracts) are ≤5 methods. **Net: 0 actionable ISP violations** beyond the one with explicit justification.

---

## DIP Violations

| File:Line | Concrete Dep | Should Be |
|-----------|--------------|-----------|
| `src/swarmline/orchestration/workflow_executor.py:11` | `from swarmline.runtime.thin.runtime import ThinRuntime` | Inject `RuntimePort` / accept `RuntimeFactoryPort`. Concrete `ThinRuntime` is infrastructure; orchestration layer should not bind to it. |
| `src/swarmline/orchestration/thin_subagent.py:25` | `from swarmline.runtime.thin.runtime import ThinRuntime` | Same. The orchestrator owns the lifecycle of subagent runtimes — give it a factory protocol. |
| `src/swarmline/orchestration/thin_subagent.py:414` (lazy) | `from swarmline.tools.sandbox_local import LocalSandboxProvider` | Inject `SandboxProvider` Protocol. Lazy-import is a partial mitigation; not a fix. |
| `src/swarmline/agent/runtime_wiring.py:123` (lazy) | `from swarmline.tools.sandbox_local import LocalSandboxProvider` | Same. |
| `src/swarmline/bootstrap/stack.py:138` | `runtime_factory = RuntimeFactory()` | **Acceptable.** This is the composition root — the documented single assembly point. DIP applies above this line. |
| `src/swarmline/agent/runtime_factory_port.py:63` | `return RuntimeFactory()` (in `build_runtime_factory`) | **Acceptable.** This is the default factory builder — caller can inject a custom `RuntimeFactoryPort` to override. |

Net: **2 real DIP violations** (`thin_subagent.py`, `workflow_executor.py`), both resolved by introducing a `SubagentRuntimeFactory` Protocol and injecting it.

---

## Clean Architecture Violations

Layer rule: **Infrastructure → Application → Domain** (never reverse).

| Source File | Violating Import | Layer |
|-------------|------------------|-------|
| `src/swarmline/orchestration/workflow_executor.py:11` | `from swarmline.runtime.thin.runtime import ThinRuntime` | Application → Infrastructure (concrete) |
| `src/swarmline/orchestration/thin_subagent.py:25` | `from swarmline.runtime.thin.runtime import ThinRuntime` | Application → Infrastructure (concrete) |
| `src/swarmline/orchestration/thin_subagent.py:32,410-415` | `coding_profile`, `coding_toolpack`, `LocalSandboxProvider`, `SandboxConfig` | Application → Infrastructure (concrete, lazy) |
| `src/swarmline/agent/runtime_wiring.py:119,123-124` | `coding_toolpack`, `LocalSandboxProvider`, `SandboxConfig` | Application → Infrastructure (concrete, lazy) |
| `src/swarmline/agent/config.py:21-22` | `coding_profile`, `subagent_tool` (TYPE_CHECKING only) | Application → Infrastructure types — **acceptable** because guarded behind `TYPE_CHECKING`. |

**Domain purity verified:**
- `src/swarmline/protocols/*.py`: imports only stdlib + `swarmline.domain_types` + `swarmline.memory.types`. ✅
- `src/swarmline/domain_types.py`: stdlib only (`uuid`, `dataclasses`, `typing`). ✅
- `src/swarmline/types.py`: only `swarmline.domain_types`. ✅
- `src/swarmline/memory/types.py`: stdlib only. ✅

Net: **4 actionable Clean Arch violations**, all in the orchestration/agent layer reaching into `runtime/thin` or `tools/`. Same shape as the DIP violations above; the fix is the same — introduce ports.

---

## DRY Violations

| Pattern | Occurrences | Files | Suggested Helper |
|---------|------------:|-------|------------------|
| `build_tools_mcp_server` + `_adapt_handler` duplicated 100 % | 2 | `agent/agent.py:360`, `agent/runtime_dispatch.py:34` | Move both to `agent/mcp_bridge.py`; `agent.py` already imports from `runtime_dispatch.py` for other helpers. |
| `_emit_event` duplicated 100 % | 2 | `pipeline/budget_store.py:168` (InMemory), `pipeline/budget_store.py:495` (Sqlite) | Extract to module-level `_emit_budget_event(event_bus, event)` helper or `BudgetEventEmitter` mixin. |
| `__getattr__` lazy-loader pattern duplicated | 3 | `memory/__init__.py:55`, `runtime/ports/__init__.py:36`, `skills/__init__.py:36` | Extract to `swarmline._lazy_module(__name__, mapping)` helper. Common pattern, easy win. |
| `SqlitePlanStore.load / list_plans / update_step` ≡ `PostgresPlanStore.load / list_plans / update_step` | 2 | `orchestration/plan_store.py:219/233/253` and `:322/336/356` | Extract abstract base `_BasePlanStore` with `load/list_plans/update_step` (engine-agnostic — they don't issue Postgres-specific SQL). Subclasses keep only `save()` (which differs: `INSERT OR REPLACE` vs `INSERT … ON CONFLICT`). |
| `_run_runtime` duplicated | 2 | `runtime/ports/thin.py:85`, `runtime/ports/deepagents.py:102` | Extract to `runtime/ports/_shared.py`. |
| `__init__` of `Agent._RuntimeEventAdapter` duplicated | 2 | `agent/agent.py:567`, `agent/runtime_dispatch.py:329` | Same fix as `build_tools_mcp_server` — move once into `agent/event_adapters.py`. |
| `adapted` async wrapper for MCP handler duplicated | 2 | `agent/agent.py:380`, `agent/runtime_dispatch.py:228` | Same module. |
| 80 % shared logic between `SqliteGraphTaskBoard` and `PostgresGraphTaskBoard` | 2 | `multi_agent/graph_task_board_sqlite.py`, `multi_agent/graph_task_board_postgres.py` | Already partially started in `multi_agent/graph_task_board_shared.py`. Continue Strangler-Fig migration. |
| `SqliteMemoryProvider` and `PostgresMemoryProvider` ≈ identical structure | 2 | `memory/sqlite.py`, `memory/postgres.py` | Some overlap already lifted into `memory/_shared.py`. After splitting per-protocol (see SRP), the divergence is just dialect SQL — which can live in dialect-specific helpers. |

Net: **8 distinct DRY clusters**, all within infrastructure (memory backends, plan stores, MCP bridge, ports, budget store).

---

## KISS Violations

1. **`ThinRuntime.__init__` does too much** (143 lines). Subagent wiring, native-tool adapter detection, MCP resource tool spec assembly, cost tracker setup, and merge-tool logic all live in one constructor with three nested `if` branches. Extract to a builder; the single class can stay.
2. **Three "strategy" runners are imperative orchestration loops** (`run_react`, `run_conversational`, `run_planner`). Each implements the same shape: pre-call → LLM call (with retry/checkpoint) → optional tool exec → post-call (guardrails, budget, structured-output). Same shape, three slightly different bodies. The shape is begging for a strategy interface + a shared driver — but only after the methods are first split.
3. **`runtime/thin/runtime.py` lazy-imports inside both branches of `__init__`** (lines 103-109, 119-121, 173-175, 186-189). The lazy imports are correct (deferred optional deps), but stacked four-deep they obscure dependency direction. A small `_thin_runtime_imports.py` module that resolves them at top would simplify reading.
4. **`_RuntimeEventAdapter` and `_ErrorEvent`** in `agent/agent.py` (lines 540–579): two single-purpose internal classes inlined into the Agent module, then duplicated in `runtime_dispatch.py`. Extract.

---

## YAGNI Violations

Light scan. Most "configuration knobs" trace to legitimate call sites. Findings:

1. **`agent/agent.py:46` `self._runtime: Any = None`** — class-level attribute that is **never read inside `Agent`** (verified via grep). The runtime is created per-call inside `_execute_*`. Drop it.
2. **`Agent._merge_hooks`** is a 1-line method that just calls module-level `merge_hooks(...)` and is invoked once. Inline it.
3. **No code-on-spec parameters were detected in the protocol layer.** Domain layer is YAGNI-clean.

---

## Code Smells

- **TODO / FIXME / HACK / XXX in `src/`:** **0** (verified). The 34 grep hits are all `TaskStatus.TODO` enum values.
- **Bare `except:`:** 0.
- **Mutable default arguments:** 0.
- **Bare `print()` in production code:** 0 outside CLI/daemon entry-points (those use `# noqa: T201`).
- **Catch-all `except Exception`:** 167 occurrences — almost all are tagged `# noqa: BLE001` and surrounded by event-emit + re-raise / fallback. Spot-checks (graph_orchestrator.py:354, pipeline/pipeline.py:269, pipeline/typed.py:243) confirm intentional. Acceptable cluster.
- **`# type: ignore` comments:** **20** (per `CONCERNS.md`); reduction is on the post-v1.5 backlog. None mask real bugs — they're optional-import shims (`trafilatura`, `tavily`, `crawl4ai`, `ddgs`, `langgraph`) plus 4 narrow assignment/return suppressions where ty cannot reason about runtime polymorphism.
- **`Any` in domain protocols:** 11 hits in `protocols/memory.py` (mostly `dict[str, Any]` for unknown JSON payloads coming back from storage). Acceptable — alternatives are `TypedDict` schemas which would couple the protocol to specific shapes.
- **Magic numbers:** sparse and well-named. Defaults like `max_stream_len=10000`, `token_budget=4000`, `DEFAULT_BUDGET_TOKENS=500` are top-level constants/parameters with intent in their names.
- **Empty function bodies:** 162 — all `...` Protocol method stubs and noqa'd `pass` in defensive `try/except`. Verified clean.
- **Outdated docstrings:** module docstrings on the largest files often read "Llm Providers module." or "Runtime module." — boilerplate that the auto-formatter inserted. Cosmetic only; ruff doesn't flag because `D100/D200` are off.
- **`isinstance` on `Mock`/`MagicMock` in production:** 0. Test scaffolding stays in tests.

---

## Test Quality Issues

- **Test/source LOC ratio:** 1.62 (85 844 test LOC vs 52 980 source LOC). Healthy — well above the 1.0 floor.
- **Test count:** 5452 passed offline + 31 explicit integration + 5 live. Mock-heavy units: **19 tests with > 5 mock invocations** — top offenders:

| Mocks | Test |
|------:|------|
| 16 | `test_native_tools.py:424 test_google_adapter_call_with_tools_function_call` |
| 15 | `test_native_tools.py:375 test_google_adapter_call_with_tools_text_only` |
| 10 | `test_native_tools.py:319 test_openai_adapter_call_with_tools_tool_calls` |
| 10 | `test_cli_runtime.py:427 test_cli_runtime_cancel_running_process_yields_cancelled_error` |
| 8 | 6× `test_cli_runtime.py` + 2× `test_native_tools.py` + 2× `test_web_providers.py` |

Both clusters (CLI runtime, native tool adapters) are ports to subprocess / SDK boundaries — converting to integration tests would mean spawning real `claude` / hitting real OpenAI / real Gemini, which is what `tests/integration/` and `live` markers already cover. **Recommendation:** keep as unit tests; they exercise marshalling logic. Watch list, not action item.

- **Test naming:** `@pytest.mark.parametrize` used 81×. About 19 tests use the short `test_<what>` form (e.g. `test_protocol_checkable`, `test_aggregate_delta`, `test_empty_object`). These are inside `class TestX:` containers so the class name supplies the "context" — readable in pytest output. Acceptable.

- **Brittle exact-string asserts:** ~10 spots like `assert result == "openrouter:anthropic/claude-3.5-haiku"` (`test_examples_smoke.py:137,151`). These are model-name normalisation tests — exact match is the contract. Acceptable.

- **AAA pattern adherence:** spot-checked; clean.

---

## Top 10 Refactor Targets (prioritized)

| Priority | File | Effort | Impact | Type |
|---------:|------|-------:|-------:|------|
| 1 | `runtime/thin/react_strategy.py` (`run_react` 389 L) | M | High | KISS / SRP |
| 2 | `runtime/thin/runtime.py` (`run` 319 L + `__init__` 143 L) | M | High | SRP / KISS |
| 3 | `memory/postgres.py` + `memory/sqlite.py` (8-protocol god classes) | L | High | SRP |
| 4 | `agent/agent.py` ↔ `agent/runtime_dispatch.py` duplicates (`build_tools_mcp_server`, `_adapt_handler`, `_RuntimeEventAdapter.__init__`, `adapted`) | S | Medium | DRY |
| 5 | `orchestration/{thin_subagent,workflow_executor}.py` direct `ThinRuntime` import → port | S | Medium | DIP / Clean Arch |
| 6 | `multi_agent/graph_task_board_{sqlite,postgres}.py` consolidation via `graph_task_board_shared.py` | M | Medium | DRY |
| 7 | `orchestration/plan_store.py` (`SqlitePlanStore` ↔ `PostgresPlanStore`: lift `load`/`list_plans`/`update_step` to a base) | S | Medium | DRY |
| 8 | `pipeline/budget_store.py` (`_emit_event` duplicated; `SqlitePersistentBudgetStore` 14-method class) | S | Low | DRY / SRP |
| 9 | `runtime/thin/conversational.py` (`run_conversational` 290 L) | M | Medium | KISS / SRP |
| 10 | `runtime/ports/{thin,deepagents}.py` (`_run_runtime` duplicated) + `__getattr__` lazy-loader (3×) | XS | Low | DRY |

---

## Health Metrics

| Metric | Value |
|--------|------:|
| LOC `src/swarmline/` | 52 980 |
| LOC `tests/` | 85 844 |
| Test/code ratio | 1.62 |
| Source files | 387 |
| Test files | 382 |
| Files > 300 lines | 34 |
| Files > 500 lines | 11 |
| Files > 600 lines | 5 |
| Methods > 50 lines | 100 |
| Methods > 100 lines | 20 |
| Methods > 200 lines | 5 |
| Methods > 300 lines | 2 (`run_react` 389, `ThinRuntime.run` 319) |
| Protocols total | ≈ 93 (26 in `protocols/`, ≈ 67 outside) |
| Protocols > 5 methods | **1** (`CodingTaskBoardPort`, deliberate composition) |
| TODO / FIXME / HACK / XXX | **0** |
| `# type: ignore` | 20 |
| Bare `except:` | 0 |
| Mutable default args | 0 |
| Tests with > 5 mocks | 19 |
| Coverage (per `STATUS.md`) | 89 %+ overall |
| Cyclomatic hotspots | `run_react` (~30 branches), `ThinRuntime.run` (~25), `run_conversational` (~22), `run_planner` (~18) |

---

## Recommendations

### v1.5.1 — quick wins (XS / S, ≤ 1 day total)

1. **DRY: extract `agent/mcp_bridge.py`** for `build_tools_mcp_server`, `_adapt_handler`, `_RuntimeEventAdapter`, `_ErrorEvent`. Removes ~120 duplicated lines across `agent/agent.py` + `agent/runtime_dispatch.py`. (Refactor target #4)
2. **DRY: lift `_BasePlanStore.load/list_plans/update_step`** into `orchestration/plan_store.py`. Removes 3 × 2 duplicated methods. (Target #7)
3. **DRY: extract `_emit_budget_event` helper** in `pipeline/budget_store.py`. (Target #8)
4. **DRY: extract `swarmline._lazy_module()` helper** for the three `__getattr__` lazy loaders.
5. **YAGNI: drop `Agent._runtime: Any = None`** + inline `Agent._merge_hooks`.
6. **Already-deferred S4 KISS:** address the empty wrapper class in orchestration as planned.

### v1.6.0 — substantial refactors (M / L, multi-day)

1. **Split `run_react` / `run_conversational` / `run_planner`** along the shared shape. Then introduce a `RuntimeStrategy` Protocol so `ThinRuntime.run` becomes `await self._strategy.execute(...)`. (Targets #1, #2, #9)
2. **Split `PostgresMemoryProvider` / `SQLiteMemoryProvider` per protocol.** 8 small classes with a `_PostgresSession` / `_SQLiteSession` mixin. Drives both memory providers under 250 LOC each. (Target #3)
3. **Introduce `SubagentRuntimeFactory` Protocol.** Eliminates `from swarmline.runtime.thin.runtime import ThinRuntime` in orchestration. (Target #5)
4. **Continue `graph_task_board_shared.py` Strangler-Fig migration.** (Target #6)
5. **Reduce `# type: ignore` count from 20 → ≤ 5** as part of normal maintenance.

### v2.0.0 — architectural shifts

- **Boundary cleanup:** if v1.6.0 ports work lands, the only remaining App → Infra leak is in `agent/runtime_wiring.py` (sandbox provider construction). Move sandbox construction into `bootstrap/capabilities.py` (where it already partially lives) and have `runtime_wiring` accept a fully-formed `SandboxProvider`. After that, `src/swarmline/{agent,orchestration,bootstrap}` will import only domain protocols + sibling application modules — true Clean Arch.
- **Consider a `MemoryProvider` aggregate Protocol** for backward-compatibility while the per-store split in v1.6.0 is rolled out, then deprecate the aggregate in v2.0.

### Non-recommendations

- **Do not** rewrite `cli/init_cmd.py` — its size is 80 % template literals; refactor would add complexity without real gain.
- **Do not** convert the 19 mock-heavy unit tests into integration tests as a class — the marshalling logic they cover (Anthropic / OpenAI / Google native tool-call adapters; CLI subprocess parsing) is not naturally reachable through integration without real provider keys, which `tests/integration/` and `live` already cover.
- **Do not** chase the `Any` types in `protocols/memory.py` — they are dict-of-JSON shapes from external storage; tightening them to `TypedDict` would couple the protocol to a single payload schema.

---

## Verdict

`swarmline v1.5.0` is **ready to ship** and `main` is healthy: domain layer is pure, public API is curated, hygiene is clean, tests are dense. The debt is **localized, named, and well-understood** — the same three clusters (long thin/* methods, memory provider god classes, app-layer leaks into thin runtime) that `CONCERNS.md` already tracks. None of the findings here is a release blocker. The v1.5.1 wins are mechanical (move duplicated helpers); the v1.6.0 wins are the real refactor and unlock test/maintenance velocity for v2.0.
