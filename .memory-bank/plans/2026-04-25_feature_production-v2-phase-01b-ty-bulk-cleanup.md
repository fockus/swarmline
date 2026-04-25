# Plan: feature — production-v2-phase-01b-ty-bulk-cleanup

**Baseline commit:** 1eb72b595259086a99f4eecdcf9e5334e633f2f9

## Context

**Problem:** Sprint 1A (см. `plans/2026-04-25_feature_production-v2-phase-01a-ty-strict-foundation.md`) завершён: `ty check src/swarmline/` снизился с 75 до **62 diagnostics**, все 11 потенциальных runtime-bug'ов закрыты, CI gate активен (`tests/architecture/test_ty_strict_mode.py` + `.github/workflows/ci.yml`). Остаются ~62 ошибки в ~35 файлах — все они **категоризированы по 3 паттернам решения** (см. `notes/2026-04-25_ty-strict-decisions.md`):

- **OptDep** (~22 ошибок) — `unresolved-import` от опциональных deps (tavily, crawl4ai, ddgs, openshell, docker)
- **DecoratedTool** (~5 ошибок) — `__tool_definition__` и аналогичные атрибуты на декорированных функциях
- **CallableUnion** (~10 ошибок) — `__name__` или attribute access на `partial | callable` union

Остальные ~25 — единичные кейсы (`invalid-argument-type`, `invalid-return-type`, `call-non-callable`), которые требуют per-case анализа.

**Expected result:**
1. `ty check src/swarmline/` → **0 diagnostics** (target: closing release v1.5.0 typing gate из `STATUS.md`)
2. `tests/architecture/ty_baseline.txt` → 0
3. ZERO regressions в существующих 4500+ тестах
4. ZERO новых `# type: ignore` без обязательного reason-комментария
5. ADR-003 outcome: ty strict-mode становится releasable gate для всех будущих PR

**Related files:**
- `plans/2026-04-25_feature_production-v2-phase-01a-ty-strict-foundation.md` — Sprint 1A (foundation, 75 → 62)
- `notes/2026-04-25_ty-strict-decisions.md` — 3 канонических паттерна с примерами кода
- `BACKLOG.md` — `ADR-003 — Use ty in strict mode as sole type checker`
- `tests/architecture/test_ty_strict_mode.py` — meta-test, baseline tracking
- `tests/architecture/ty_baseline.txt` — current value: 62, target: 0
- `.github/workflows/ci.yml` — CI gate (typecheck job, fail-on-error)

**Stage breakdown (refined по факту, после Stage 1+2):**
- Stage 1: ✅ OptDep batch (22 fixes, 16 files) — ty 62 → 40
- Stage 2: ✅ Unresolved-attribute batch (4 fixes, 3 files) — ty 40 → 36
- Stage 3: ⏳ Callable narrow (9 call-non-callable, 6 files) — ty 36 → 27
- Stage 4: ⬜ Argument-type batch (22 mixed) — ty 27 → 5
- Stage 5: ⬜ Точечные остатки (5 misc) — ty 5 → 0
- Stage 6: ⬜ Final verification + lock baseline=0

---

## Stages

<!-- mb-stage:1 -->
### Stage 1: OptDep batch — 22 unresolved-import → 0 ✅ DONE (2026-04-25)

**Result (verified):** ty 62 → 40 (-22, 100% of unresolved-import closed).
Test `tests/unit/test_optdep_imports.py` introduced (82 parametrized cases, 4 invariants).
16 source files touched (not 13 — plan undercounted) covering all 18 distinct optional modules.
Pattern applied: `# ty: ignore[unresolved-import]  # optional dep` (ty-native, since
`respect-type-ignore-comments = false` makes classic `# type: ignore` inert).

**Real diagnostic distribution (verified 2026-04-25 against baseline=62):**
22 unique unresolved-import diagnostics across 12 source files / 18 distinct optional modules:

| Module(s) | File(s) | Errors |
|---|---|---|
| `tavily` | `tools/web_providers/tavily.py` | 1 |
| `crawl4ai`, `crawl4ai.markdown_generation_strategy` | `tools/web_providers/crawl4ai.py` | 2 |
| `trafilatura` | `tools/web_httpx.py` | 1 |
| `pymupdf4llm`, `fitz`, `nbformat` | `tools/extractors.py` | 3 |
| `claude_code_sdk` (×2) | `runtime/agent_sdk_adapter.py` | 2 |
| `agents`, `agents.mcp` | `runtime/openai_agents/runtime.py` | 2 |
| `nats` | `observability/event_bus_nats.py` | 1 |
| `redis.asyncio` | `observability/event_bus_redis.py` | 1 |
| `nats` | `multi_agent/graph_communication_nats.py` | 1 |
| `redis.asyncio` | `multi_agent/graph_communication_redis.py` | 1 |
| `opentelemetry`, `opentelemetry.trace` | `observability/otel_exporter.py` | 2 |
| `e2b_code_interpreter` | `tools/sandbox_e2b.py` | 1 |
| `openshell` | `tools/sandbox_openshell.py` | 1 |
| `docker` | `tools/sandbox_docker.py` | 1 |
| `fastmcp` | `mcp/_server.py` | 1 |
| `agents` | `runtime/openai_agents/tool_bridge.py` | 1 |
| **Total** | **13 files** | **22** |

**Discovery 2026-04-25:** `respect-type-ignore-comments = false` makes classic `# type: ignore[...]` comments INERT under ty strict-mode. Use ty-native `# ty: ignore[unresolved-import]` instead (verified to suppress diagnostics on a one-line probe).

**What to do:**
- Apply OptDep pattern (from `notes/2026-04-25_ty-strict-decisions.md`) to each module:
  ```python
  from typing import TYPE_CHECKING

  if TYPE_CHECKING:
      from <module> import <symbols>          # ty resolves through stubs

  try:
      from <module> import <symbols>          # runtime — real install
  except ImportError:
      <symbols> = None  # type: ignore[unresolved-import,assignment]  # optional dep
  ```
- Reason-comments are mandatory (`# optional dep`) per project policy on `type: ignore`.
- Idempotency: if a file already has TYPE_CHECKING block → only enrich it; do not duplicate.
- Where the same module is imported twice in one file (e.g. `claude_code_sdk` in `agent_sdk_adapter.py` lines 45+85) — only the import statement(s) need patching; downstream usage already gates on `<symbol> is not None`.

**Testing (TDD — tests BEFORE implementation):**
- New `tests/unit/test_optdep_imports.py` parametrized over (module, file, public symbol):
  - `test_module_importable_when_installed` — installs only what's available; asserts import path resolves and the public symbol is non-None.
  - `test_module_falls_back_to_none_when_missing` — uses `monkeypatch.setitem(sys.modules, '<module>', None)` (sentinel pattern from `test_import_isolation.py`); asserts the affected swarmline module imports without raising and exposes `None` for the missing symbol.
  - `test_no_naked_type_ignore` — source-level scan: every `# type: ignore[unresolved-import,assignment]` is followed by a reason-comment containing "optional dep".
- Reuse the established `test_import_isolation.py` style for monkeypatching `sys.modules`.
- No integration tests required — pattern is mechanical and unit-testable.

**DoD (Definition of Done) — SMART:**
- [ ] `ty check src/swarmline/ 2>&1 | grep "unresolved-import" | wc -l` → **0** (verified by re-running after each file)
- [ ] `ty check src/swarmline/ 2>&1 | grep "Found .* diagnostics"` → **≤40** (62 − 22 = 40, no regressions)
- [ ] `tests/architecture/ty_baseline.txt` updated to **40**
- [ ] `tests/unit/test_optdep_imports.py` exists, all parametrized cases green (≥18 cases × 3 = 54 assertions minimum)
- [ ] Full offline `pytest -q` green (5200+ tests, no regressions)
- [ ] `ruff check src/swarmline/ tests/` clean
- [ ] `ruff format --check src/swarmline/ tests/` clean
- [ ] No new `# type: ignore` without `# optional dep` reason-comment (grep audit)
- [ ] `git diff --stat src/` shows changes only in the 12 listed files (scope discipline)

**Code rules:** SOLID, DRY (single canonical pattern), KISS (no abstractions over plain try/except), YAGNI, Clean Architecture (touches Infrastructure layer only — domain/protocols/types untouched).

---

<!-- mb-stage:2 -->
### Stage 2: Unresolved-attribute batch — 4 mixed fixes ✅ DONE (2026-04-25)

**Result (verified):** ty 40 → 36 (-4, 100% of unresolved-attribute closed).
Test `tests/unit/test_attribute_resolution_fixes.py` introduced (8 cases, 3 invariants).
3 source files touched. Pattern split: 3× ty-native ignore (`# ty: ignore[unresolved-attribute]`),
1× structural cast (Sprint 1A's `cast(CursorResult, result).rowcount`). Bonus cleanup: removed
2 dead `# type: ignore[union-attr]` (lines 349/350 pre-format) in llm_providers.py while in the file.

**Real distribution (verified 2026-04-25 against baseline=40):**
4 unresolved-attribute diagnostics, **three distinct patterns** (not all DecoratedTool as the scaffold suggested):

| # | Location | Pattern | Approach |
|---|---|---|---|
| 1 | `runtime/thin/executor.py:280` | Manual marker assignment (`fn.__tool_definition__ = True`) on plain function | ty-native ignore (no decorator → no Protocol opportunity; rewriting flow is out-of-scope cleanup) |
| 2 | `runtime/thin/llm_providers.py:418` | `response.text` after `await` — runtime is duck-typed, no Protocol available | ty-native ignore |
| 3 | `runtime/thin/llm_providers.py:478` | `content.parts` on `Unknown \| Content \| None` (Google Gemini SDK return) | ty-native ignore (gated by `response.candidates` truthy check at runtime) |
| 4 | `session/backends_postgres.py:61` | `result.rowcount` on abstract `Result[Any]` — IDENTICAL to Sprint 1A `agent_registry_postgres.py` Stage 3 fix | `cast(CursorResult, result).rowcount` — structural, type-safe |

**What to do:**
- Cases 1-3: replace dead `# type: ignore[attr-defined|return-value|union-attr]` with ty-native `# ty: ignore[unresolved-attribute]  # <reason>`. Each reason explains *why* a structural fix is unwarranted (e.g. duck-typed third-party SDK return, runtime-gated invariant).
- Case 4: apply Sprint 1A's CursorResult cast pattern verbatim:
  - Add `from typing import cast`
  - Add `from sqlalchemy import CursorResult` (next to existing `text` import)
  - Replace `result.rowcount > 0  # type: ignore[attr-defined]` → `cast(CursorResult, result).rowcount > 0`
- Same canonical reason-comment policy as Stage 1 (`# optional dep` → here `# <pattern reason>`), enforced by tests.

**Testing (TDD — tests BEFORE implementation):**
- New `tests/unit/test_attribute_resolution_fixes.py` parametrized over the 4 locations:
  - `test_each_location_has_expected_fix` — line content matches expected token (`# ty: ignore[unresolved-attribute]` for cases 1-3; `cast(CursorResult` for case 4).
  - `test_no_dead_mypy_attr_codes_in_affected_files` — sweep the 3 affected files for `# type: ignore[attr-defined]`, `# type: ignore[union-attr]`, `# type: ignore[return-value]` referencing these contexts; cleanup invariant.
  - `test_backends_postgres_imports_cursor_result_and_cast` — source-level guard that the structural fix (case 4) actually pulls in `cast` and `CursorResult` at module top.

**DoD (Definition of Done) — SMART:**
- [ ] `ty check src/swarmline/ 2>&1 | grep "unresolved-attribute" | wc -l` → **0**
- [ ] `ty check src/swarmline/ 2>&1 | grep "Found .* diagnostics"` → **≤36** (40 − 4 = 36, no regressions in other categories)
- [ ] `tests/architecture/ty_baseline.txt` updated to **36**
- [ ] `tests/unit/test_attribute_resolution_fixes.py` exists, all parametrized cases green
- [ ] Full offline `pytest -q` green (5200+ tests, no regressions)
- [ ] `ruff check` and `ruff format --check` clean on touched files
- [ ] `git diff --stat src/` shows changes only in 3 listed files (scope discipline)

**Code rules:** SOLID, DRY (mirror Sprint 1A's CursorResult pattern verbatim), KISS, YAGNI.

---

<!-- mb-stage:3 -->
### Stage 3: Callable narrow — 9 call-non-callable → 0 ✅ DONE (2026-04-25)

**Result (verified):** ty 36 → 27 (-9, 100% of call-non-callable closed).
Test `tests/unit/test_callable_narrow_fixes.py` introduced (16 cases: 9 location asserts
+ 1 mypy-misc cleanup invariant + 6 no-naked-ignore parametrized scans).
6 source files touched. Pattern uniform: ty-native `# ty: ignore[call-non-callable]`
+ reason-comment per location. Bonus cleanup: dead `# type: ignore[misc]` removed
from compaction.py (inert under `respect-type-ignore-comments = false`).

**Real fix locations (post-format line numbers):**
- `compaction.py:167` — Optional Callable hook (replaces dead `[misc]`)
- `multi_agent/graph_orchestrator.py:363, 393` — hasattr-narrow on `_task_board.cancel_task`
- `orchestration/generic_workflow_engine.py:53, 61` — hasattr-narrow on Protocol-or-Callable
- `orchestration/manager.py:39` — hasattr-narrow on optional Protocol method
- `tools/web_providers/crawl4ai.py:52, 53` — Optional class instantiation gated by sibling None check
- `tools/web_providers/tavily.py:51` — nested-function scope loses outer narrow

**Line drift note:** Initial draft used pre-format lines (319, 345, 59, 37). After
`ruff format` reflowed multi-line `def`/method calls in 3 files, the test was updated
to post-format positions. The line-drift detector (the test itself) caught all 4 shifts.



**Real distribution (verified 2026-04-25 against baseline=36):**
9 `call-non-callable` diagnostics across 6 source files, **three distinct narrowing failures**:

| # | Location | Pattern | Why ty cannot narrow |
|---|---|---|---|
| 1 | `compaction.py:167` | Optional Callable hook (`Unknown \| ((str, str, /) -> Awaitable[str]) \| None`) | `_llm_call` typed as Optional Callable; runtime guard at instantiation, not call site |
| 2 | `multi_agent/graph_orchestrator.py:319` | `hasattr(self._task_board, "cancel_task")` then `await self._task_board.cancel_task(...)` | ty does not narrow on `hasattr` — `_task_board` typed as object-Protocol without `cancel_task` |
| 3 | `multi_agent/graph_orchestrator.py:345` | identical to #2 (excepting `asyncio.CancelledError` branch) | same |
| 4 | `orchestration/generic_workflow_engine.py:53` | `hasattr(self._executor, "execute")` then `await self._executor.execute(...)` | duck-typed Protocol-or-Callable union; `hasattr` doesn't narrow |
| 5 | `orchestration/generic_workflow_engine.py:59` | `hasattr(self._verifier, "verify")` then `await self._verifier.verify(...)` | same |
| 6 | `orchestration/manager.py:37` | `hasattr(self._store, "set_namespace")` then `self._store.set_namespace(...)` | optional Protocol method extension via duck typing |
| 7 | `tools/web_providers/crawl4ai.py:52` | `CrawlerRunConfig(...)` after `if AsyncWebCrawler is None` guard | three optional symbols share one try/except, but ty narrows only the explicitly-checked name |
| 8 | `tools/web_providers/crawl4ai.py:53` | `DefaultMarkdownGenerator()` after same guard | same |
| 9 | `tools/web_providers/tavily.py:51` | `TavilyClient(...)` inside nested `_sync_search` after outer `if TavilyClient is None` guard | nested-function scope loses outer narrowing |

**What to do (uniform ty-native ignore + reason — minimum-viable diff):**

All 9 cases are runtime-correct duck-typed call sites that ty cannot narrow through. Three approaches were considered:
1. ty-native `# ty: ignore[call-non-callable]` + reason  ← chosen (consistency with Stage 1/2)
2. Structural narrow (`assert ... is not None`) — works for compaction/tavily but adds runtime asserts
3. Protocol declarations with optional methods + isinstance — out-of-scope for Sprint 1B (refactor, not closure)

Decision: **uniform ty-native ignore** (option 1). Behavioral parity is preserved (zero runtime change), and the trailing reason-comment documents WHY the fix is mechanical:
- For #2-6 (hasattr-narrow): `# ty: ignore[call-non-callable]  # hasattr-narrow not propagated by ty`
- For #1 (compaction): `# ty: ignore[call-non-callable]  # Optional Callable gated by caller config` (also replaces dead `# type: ignore[misc]`)
- For #7-8 (crawl4ai): `# ty: ignore[call-non-callable]  # gated by AsyncWebCrawler is None check above`
- For #9 (tavily): `# ty: ignore[call-non-callable]  # nested function — outer narrow lost`

This mirrors Stage 1/2 where ty-native ignores carry mandatory reason-comments. NO `assert` statements are introduced — they would change runtime behavior subtly under PYTHONOPTIMIZE/-O and add noise to call graphs without removing the underlying type-system limitation.

**Testing (TDD — tests BEFORE implementation):**
- New `tests/unit/test_callable_narrow_fixes.py` parametrized over the 9 locations:
  - `test_each_location_has_call_non_callable_ignore` — line content includes `# ty: ignore[call-non-callable]` AND a reason-comment substring (per location).
  - `test_no_dead_mypy_misc_in_compaction` — source-level guard: `compaction.py` no longer carries `# type: ignore[misc]` near `_llm_call(` invocation (cleanup invariant — would otherwise stay inert).
  - `test_no_naked_call_non_callable_ignores` — every `# ty: ignore[call-non-callable]` in touched files has at least 10 chars of reason comment after it.

**DoD (Definition of Done) — SMART:**
- [ ] `ty check src/swarmline/ 2>&1 | grep "call-non-callable" | wc -l` → **0**
- [ ] `ty check src/swarmline/ 2>&1 | grep "Found .* diagnostics"` → **≤27** (36 − 9 = 27, no regressions in other categories)
- [ ] `tests/architecture/ty_baseline.txt` updated to **27**
- [ ] `tests/unit/test_callable_narrow_fixes.py` exists, all 9+ parametrized cases green
- [ ] Full offline `pytest -q` green (no regressions in 5200+ tests)
- [ ] `ruff check` and `ruff format --check` clean on touched files
- [ ] `git diff --stat src/` shows changes only in 6 listed files (scope discipline)

**Code rules:** SOLID, DRY (single canonical `# ty: ignore[call-non-callable]` + reason pattern), KISS (no asserts, no Protocol redesigns), YAGNI, Clean Architecture (touches Infrastructure/Application — domain/protocols untouched).

---

<!-- mb-stage:4 -->
### Stage 4: Argument-type batch — 22 mixed → 5 ⬜ TODO

Distribution will be detailed before execution. Categories from baseline=27 ty output:
- 17× `invalid-argument-type`
- 3× `unknown-argument`
- 2× `no-matching-overload`

Per-case point fixes (annotation/overload corrections — not pattern-uniform).

**Target:** ty 27 → 5.

---

<!-- mb-stage:5 -->
### Stage 5: Точечные остатки — 5 misc → 0 ⬜ TODO

5 misc diagnostics:
- 2× `invalid-return-type`
- 2× `invalid-assignment`
- 1× `not-iterable`

Per-case fixes after Stage 4 settles.

**Target:** ty 5 → 0.

---

<!-- mb-stage:6 -->
### Stage 6: Final verification + lock baseline=0 ⬜ TODO

- [ ] `ty check src/swarmline/` → **Found 0 diagnostics**
- [ ] `tests/architecture/ty_baseline.txt` = **0**
- [ ] STATUS.md release gate updated (`ty check` green)
- [ ] checklist.md Sprint 1B section closed
- [ ] progress.md append for Sprint 1B completion (6 stages, ~50+ tests)
- [ ] ADR-003 outcome: ty strict-mode = sole release gate confirmed

---

## Risks and mitigation

| Risk | Probability | Mitigation |
|------|-------------|------------|
| <!-- risk --> | <!-- H/M/L --> | <!-- how to prevent it --> |

## Gate (plan success criterion)

<!-- When the plan is considered fully complete -->
