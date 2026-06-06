# Refactor — mode routing: structural only, `detect_mode` REMOVED

**Type:** refactor (Strangler Fig — behaviour-preserving for the with-tools path)
**Created:** 2026-06-06
**Status:** ✅ DONE (2026-06-06). `detect_mode` deleted; mode resolution structural. swarmline 5253 passed (0 new regressions; 26 pre-existing optional-dep), faberlic 616/92.98%, live e2e 3/3, ruff+ty clean. Not committed.
**Source:** faberlic maintainer review. `detect_mode` regex as the execution-mode gate is a footgun — it cost a prod bug (tool-equipped agent silently denied its tools), and the tool-aware default was bolted on as a post-hoc patch.

**Decision (escalated 2026-06-06, per maintainer):** do NOT merely demote `detect_mode` — **delete it entirely**. Its regex heuristic (both react- and planner-keyword patterns) has zero production callers and only ever decided the tool-less + no-hint case, where the right default is simply `conversational`. Mode becomes purely structural.

## Root design smell
`ThinRuntime.run()` resolved mode as `detect_mode(user_text, mode_hint, ...)` FIRST, then patched it: `if mode_hint is None and active_tools and mode != "react": mode = "react"`. Consequences:
- The regex heuristic was conceptually the default; tool-aware was a correction bolted on top.
- `detect_mode` ran even when the answer was predetermined (tools present ⇒ must be react).
- `detect_mode` inferred `planner` from the substring «план»/«plan» (a user asking «какой у вас **план** тарифов?» was hijacked into the multi-step planner).

**Verified blast radius (safe to delete):** `detect_mode` is imported only by `runtime.py` + `test_thin_modes.py`. `react_patterns`/`planner_patterns` (ThinRuntime ctor → detect_mode) have **zero** production callers (no swarmline `src/`, no faberlic). `VALID_MODES` is reused (kept). All planner EXECUTION in the suite is reached via explicit `mode_hint="planner"` or by testing `ThinPlannerMode` directly — never by keyword.

## Goal
1. Mode resolution is purely structural & explicit: **explicit (valid) `mode_hint` > tools present → `react` > `conversational`**. No regex, ever.
2. Delete `detect_mode`, `_REACT_PATTERNS`, `_PLANNER_PATTERNS`, and the dead `react_patterns`/`planner_patterns` params on `ThinRuntime`. Keep `VALID_MODES`.
3. `planner` reachable ONLY via explicit `mode_hint="planner"`.

## Non-goals (YAGNI)
- Do NOT change planner EXECUTION (`run_planner`) or the set of `VALID_MODES`.
- Do NOT add a speculative chit-chat fast-path flag (separate concern).
- Do NOT touch `llm_providers` / `react_strategy` / `finalization`.

## Stages (TDD)

### Stage 1 — RED
Files: `tests/unit/test_thin_modes.py`, `tests/unit/test_thin_runtime.py`.
- `test_thin_modes.py`: collapse to a single `TestValidModes` (all `detect_mode` tests removed — the function is gone).
- `test_thin_runtime.py` (`TestThinRuntimeToolAwareDefault`): replace the detect-mode spy test with `test_tool_less_react_keyword_no_hint_stays_conversational` — NO tools, NO `mode_hint`, react-keyword text («Найди…») ⇒ assert the `Mode:` status event is `"Mode: conversational"` (not `react`). Keep the existing tools→react and explicit-hint tests.
DoD: the new runtime test FAILS on current code (`Mode: react`, because the react regex still matches «Найди»).

### Stage 2 — GREEN
Files: `src/swarmline/runtime/thin/modes.py`, `src/swarmline/runtime/thin/runtime.py`.
- `modes.py`: reduce to a module docstring + `VALID_MODES`. Delete `detect_mode`, `_REACT_PATTERNS`, `_PLANNER_PATTERNS`, and the now-unused `re`/`Sequence` imports.
- `runtime.py`: import `VALID_MODES` (was `detect_mode`); drop the now-unused `import re`; drop `react_patterns`/`planner_patterns` ctor params + `self._react_patterns`/`self._planner_patterns`; replace the mode block with:
  ```python
  if mode_hint is not None and mode_hint in VALID_MODES:
      mode = mode_hint
  elif active_tools:
      mode = "react"
  else:
      mode = "conversational"
  ```
DoD: Stage-1 tests GREEN; all explicit `mode_hint=…` tests + `TestValidModes` GREEN.

### Stage 3 — Verify (no regressions, both repos)
- swarmline `uv run pytest -m "not live" -q` (via faberlic uv env) — no NEW failures vs baseline (5269 passed + 26 pre-existing optional-dep). `ruff check` clean; `ty check src/swarmline` clean.
- faberlic `uv run python -m pytest -q` green (coverage ≥85%); real-runtime routing test green; `ruff` + `ty check src/` clean.
- MB: report saved to swarmline `reports/`, `progress.md` appended.

## Edge cases
- `mode_hint="conversational"` + tools → honored → no tools run.
- `mode_hint="planner"` (± tools) → honored → `run_planner`.
- invalid `mode_hint` + tools → falls through to `react`; + no tools → `conversational`.
- no tools + react/planner keyword («найди…», «план…») → **conversational** now (was react/planner) — the targeted change.
- tools + no hint → react (structural).

## Rollback
Revert `modes.py` + `runtime.py` (re-add `detect_mode` + patterns + the patch form) and the two test files together.
