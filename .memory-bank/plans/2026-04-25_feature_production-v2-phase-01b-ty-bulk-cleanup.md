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

**Stage breakdown (preliminary, must be refined в отдельной сессии):**
- Stage 1: OptDep batch (~22 fixes, ~5-7 файлов)
- Stage 2: DecoratedTool batch (~5 fixes, 2-3 файла)
- Stage 3: CallableUnion batch (~10 fixes, 4-6 файлов)
- Stage 4: Single-case errors (~25 fixes, по группам severity)
- Stage 5: Final verification + lock baseline at 0 + remove "outdated baseline" warning logic if any

**Refinement note:** этот план — **scaffold, не финальный**. Перед началом Sprint 1B запустить отдельную `/mb plan feature` сессию для детального наполнения каждой Stage с TDD/SMART DoD/edge cases (как делалось для Sprint 1A).

---

## Stages

<!-- mb-stage:1 -->
### Stage 1: <!-- title -->

**What to do:**
- <!-- concrete actions -->

**Testing (TDD — tests BEFORE implementation):**
- <!-- unit tests: what they verify, edge cases -->
- <!-- integration tests: which components interact -->

**DoD (Definition of Done):**
- [ ] <!-- concrete, measurable criterion (SMART) -->
- [ ] tests pass
- [ ] lint clean

**Code rules:** SOLID, DRY, KISS, YAGNI, Clean Architecture

---

<!-- mb-stage:2 -->
### Stage 2: <!-- title -->

**What to do:**
-

**Testing (TDD):**
-

**DoD:**
- [ ]

---

## Risks and mitigation

| Risk | Probability | Mitigation |
|------|-------------|------------|
| <!-- risk --> | <!-- H/M/L --> | <!-- how to prevent it --> |

## Gate (plan success criterion)

<!-- When the plan is considered fully complete -->
