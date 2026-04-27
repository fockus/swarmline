# Plan: fix — post-review-polish (Stage 8)

**Baseline commit:** 395acb2a2e184a0002f73abd96f45553a21e02de (HEAD of `main`)

**Source review:** [`reports/2026-04-27_review_post-v1.5.0-security-audit-closure.md`](../reports/2026-04-27_review_post-v1.5.0-security-audit-closure.md)

## Context

**Problem:** Multi-perspective review (Security Engineer + Code Reviewer + Reality Checker) of the post-v1.5.0 security-audit closure (commits `3fae1b2..395acb2`) returned verdict **🔴 NEEDS WORK — DO NOT PUBLISH TO PUBLIC PyPI YET**. Engineering layer is clean (5532 pytest passed, ty=0, ruff/format green), but the release-readiness layer has 4 critical blockers. This plan closes the 3 actionable critical blockers (C1, C2, C4) before public sync. C3 (tag/version paradox) is a destructive operator decision — handled separately.

**Expected result:**
- C1: ReDoS-safe URL-userinfo regex in `redaction.py`; 100KB attacker input runs in <100 ms.
- C2: 0 occurrences of `v1.5.1` references in `src/`; `serve/app.py` docstring/error messages reflect hard-fail behaviour against `v1.5.0` audit closure semantics.
- C4: 4 docs files (`docs/migration-guide.md`, `docs/migration/v1.4-to-v1.5.md`, `docs/getting-started.md`, `docs/configuration.md`) updated with breaking-change snippet `create_app(agent, allow_unauthenticated_query=True, host="127.0.0.1")`.
- All 4 CI gates remain green at every stage commit (TDD per project RULES.md).

**Constraints:**
- TDD red → green per stage. Test added BEFORE production code change.
- Atomic commit per stage. Conventional Commits + `Co-Authored-By: Claude Opus 4.7 (1M context)`.
- Per CLAUDE.md "Destructive actions — only after explicit confirmation" — C3 (tag move) is **NOT in this plan**, only C1+C2+C4.
- Backwards compatibility: tests `5532 passed` baseline must not regress. Net new tests OK; net regressions = block.
- Out of scope: serious findings S1-S6 + notes N1-N5 (deferred to follow-up `v1.5.1` patch within 1-2 weeks).

**Related files (Stage 1):**
- `src/swarmline/observability/redaction.py:46` — ReDoS pattern
- `tests/unit/test_observability_redaction.py` — new ReDoS regression test

**Related files (Stage 2):**
- `src/swarmline/serve/app.py:159-161` (docstring), `:163` (comment), `:170` (ValueError)
- `tests/unit/test_serve_app_loopback_enforcement.py` — assertion update

**Related files (Stage 3):**
- `docs/migration-guide.md:54-58`
- `docs/migration/v1.4-to-v1.5.md`
- `docs/getting-started.md:146`
- `docs/configuration.md:65`
- `CHANGELOG.md` — cross-reference verification

---

## Stages

<!-- mb-stage:1 -->
### Stage 1: C1 — ReDoS-safe URL-userinfo regex

**What to do:**
- Open `src/swarmline/observability/redaction.py`. Locate the URL-userinfo pattern at line 46:
  ```python
  (re.compile(r"(\w+://)([^:/@\s]+):([^@/\s]+)@"), r"\1[REDACTED]:[REDACTED]@"),
  ```
- Replace with bounded-quantifier variant that prevents catastrophic backtracking:
  ```python
  (re.compile(r"([a-zA-Z][a-zA-Z0-9+.\-]{0,30}://)([^:@\s/]{1,256}):([^@\s/]{1,256})@"), r"\1[REDACTED]:[REDACTED]@"),
  ```
- Justification:
  - Scheme: `[a-zA-Z][a-zA-Z0-9+.\-]{0,30}` — RFC 3986 spec-conformant, capped at 31 chars (real-world max ~10).
  - Userinfo + password: bounded `{1,256}` — RFC 3986 has no length limit, but no real consumer accepts >256, and bounded quantifiers eliminate ReDoS exposure.
  - Removed `\w+` (which permits `_` ambiguity with `[\w]` class) for explicit alphanumeric scheme.

**Testing (TDD — tests BEFORE implementation):**
- New test class `TestRedactionReDoSResistance` in `tests/unit/test_observability_redaction.py`:
  - `test_redact_secrets_handles_100kb_userinfo_payload_under_100ms` — generates `https://` + `a` × 50_000 + `:` + `b` × 50_000 + `@host` (100KB attacker input mimicking pathological backtracking trigger). Wraps `redact_secrets(payload)` in `time.perf_counter()`. Asserts wall time < 100 ms (10× safety margin vs 1s SLO).
  - `test_redact_secrets_handles_legitimate_url_with_userinfo` — happy path: `https://user:secret@example.com/path` → result contains `[REDACTED]` (bounded regex still matches normal URLs).
  - `test_redact_secrets_handles_long_legitimate_userinfo_at_boundary` — userinfo at exactly 256 chars (boundary): redacted. At 257 chars: pattern does NOT match (acceptable — pathological case).
  - `test_redact_secrets_handles_unicode_in_userinfo` — `https://пользователь:пароль@example.com` — assert function does not crash; whether it redacts depends on regex (document outcome).
- Verify red phase (write tests first, run, confirm `test_redact_secrets_handles_100kb_userinfo_payload_under_100ms` FAILS or TIMES OUT against current pattern).

**DoD (Definition of Done):**
- [ ] 4 new tests added in `tests/unit/test_observability_redaction.py::TestRedactionReDoSResistance`.
- [ ] Tests run BEFORE pattern change → at minimum the 100KB test fails or times out (>100ms).
- [ ] Pattern in `redaction.py:46` replaced with bounded-quantifier variant.
- [ ] After fix: `pytest tests/unit/test_observability_redaction.py -v` → all green (existing 27 + new 4 = 31 tests pass).
- [ ] `pytest tests/unit/test_observability_redaction.py::TestRedactionReDoSResistance::test_redact_secrets_handles_100kb_userinfo_payload_under_100ms -v` → wall time < 100 ms (verified by `--durations=10`).
- [ ] Full offline `pytest --tb=no -q` → 5536 passed (5532 + 4) or higher; 0 failed; 0 deselected change vs baseline.
- [ ] `ruff check src/ tests/` → All checks passed.
- [ ] `ruff format --check src/ tests/` → 0 files would be reformatted.
- [ ] `ty check src/swarmline/` → 0 diagnostics.
- [ ] Atomic commit: `fix(security): ReDoS-safe URL-userinfo regex in redaction (C1)` with body explaining 50KB→3.4s problem + bounded-quantifier fix + 100KB regression test.

**Code rules:** YAGNI (no broader regex refactor — surgical fix only). KISS (one pattern replacement). Defensive coding boundary: bounded quantifiers in user-input regex.

---

<!-- mb-stage:2 -->
### Stage 2: C2 — Sweep `v1.5.1` references in serve/app.py

**What to do:**
- Open `src/swarmline/serve/app.py`. Update three locations:
  - **Lines 159-161 (docstring):** Currently says *"For backward compatibility, ``host=None`` (the v1.4.x signature) is still accepted but logs a security warning so operators can audit unauthenticated surface area."* — FALSE since consolidation. Replace with: *"As of v1.5.0 (security audit closure), ``host=None`` raises ValueError when ``allow_unauthenticated_query=True``. Operators must explicitly bind to a loopback host or pass ``auth_token=`` for production."*.
  - **Line 163 (comment):** Currently `# v1.5.1: the v1.5.0 deprecation warning for host=None has graduated...`. Replace with `# v1.5.0 (security audit closure): the host=None deprecation warning graduated to a hard ValueError (audit P2 #5).`.
  - **Line 170 (ValueError message):** Currently *"requires an explicit host= argument since v1.5.1."*. Replace with *"requires an explicit host= argument since v1.5.0 (security audit closure)."*.
- Verify exhaustiveness: `grep -rn "v1.5.1" src/swarmline/` must return 0 matches after edit.

**Testing (TDD):**
- Update `tests/unit/test_serve_app_loopback_enforcement.py`:
  - `test_unauthenticated_query_no_host_raises_in_v151` → rename to `test_unauthenticated_query_no_host_raises_after_v150_audit`. Update assertion strings: `assert "since v1.5.0" in str(exc.value)`, `assert "v1.5.1" not in str(exc.value)`.
  - `test_unauthenticated_query_empty_string_host_raises` — same string-update pattern.
  - Add new test `test_serve_app_source_has_no_v151_references` (mirroring an existing source-invariant test pattern, e.g., `test_optdep_typing_fixes`):
    ```python
    def test_serve_app_source_has_no_v151_references() -> None:
        """C2 closure: after v1.5.0 consolidation, no v1.5.1 strings should
        survive in the source. Catches regressions if someone re-introduces
        the bumped version reference in error messages or docstrings."""
        from pathlib import Path
        import swarmline.serve.app
        source = Path(swarmline.serve.app.__file__).read_text(encoding="utf-8")
        assert "v1.5.1" not in source
    ```
- Verify red phase: run the new test FIRST → it fails because line 163 / 170 still contain `v1.5.1`. Then apply fix → green.

**DoD:**
- [ ] 1 new test added (`test_serve_app_source_has_no_v151_references`); 2 existing tests updated with new assertion strings.
- [ ] `grep -rn "v1.5.1" src/` → 0 matches (confirmed via Bash).
- [ ] `grep -n "since v1.5.0" src/swarmline/serve/app.py` → matches both error message and comment.
- [ ] Docstring at lines 151-161 reflects current behaviour (host=None raises, no warning fallback).
- [ ] `pytest tests/unit/test_serve_app_loopback_enforcement.py -v` → all green.
- [ ] Full offline `pytest --tb=no -q` → 5537 passed (5536 + 1); 0 failed.
- [ ] `ruff check src/ tests/` → All checks passed.
- [ ] `ruff format --check` → clean.
- [ ] `ty check src/swarmline/` → 0 diagnostics.
- [ ] Atomic commit: `fix(serve): drop v1.5.1 references after audit closure consolidation (C2)`.

**Code rules:** DRY (single grep verifies invariant). KISS (string replace, no structural change).

---

<!-- mb-stage:3 -->
### Stage 3: C4 — Docs sweep for breaking change (4 files)

**What to do:**
- **`docs/migration-guide.md:54-58`** — locate the `serve.create_app(allow_unauthenticated_query=True)` example without `host=`. Update to:
  ```python
  # Local-only mode (v1.5.0+)
  app = create_app(
      agent,
      allow_unauthenticated_query=True,
      host="127.0.0.1",  # MANDATORY since v1.5.0 — loopback enforcement
  )
  ```
  Add a paragraph before the snippet explaining: *"The v1.4.x signature ``create_app(agent, allow_unauthenticated_query=True)`` (without ``host=``) is rejected by v1.5.0+. Pass ``host="127.0.0.1"`` for local-only mode, or ``auth_token=...`` for production."* Reference: audit P2 #5.
- **`docs/migration/v1.4-to-v1.5.md`** — currently has zero breaking-change references for this surface. Add a new H2 section `### Breaking: serve.create_app requires explicit host= for unauthenticated mode`:
  - Brief: explicit `host=` is now mandatory when `allow_unauthenticated_query=True`.
  - Before / After code snippets.
  - Migration steps for typical CLI/library callers.
  - Cross-reference: audit closure P2 #5 + commit `0fa523b`.
- **`docs/getting-started.md:146`** — locate `allow_unauthenticated_query` snippet, add `host="127.0.0.1"` to all examples; add inline note: "Local-only mode requires explicit loopback host since v1.5.0."
- **`docs/configuration.md:65`** — same pattern: any example showing `allow_unauthenticated_query=True` MUST include `host=`. Update inline comment / table description.

**Testing (TDD):**
- Add a docs-invariant unit test in `tests/unit/test_docs_breaking_change_examples.py` (new file):
  ```python
  """Ensures published docs reflect v1.5.0 breaking change for serve.create_app.

  C4 closure: any docs example showing ``allow_unauthenticated_query=True``
  MUST include ``host=`` to remain runnable post-v1.5.0.
  """
  from __future__ import annotations
  from pathlib import Path
  import re
  import pytest

  DOCS_TO_AUDIT = [
      "docs/migration-guide.md",
      "docs/migration/v1.4-to-v1.5.md",
      "docs/getting-started.md",
      "docs/configuration.md",
  ]

  @pytest.mark.parametrize("doc_path", DOCS_TO_AUDIT)
  def test_doc_does_not_show_unauthenticated_query_without_host(doc_path: str) -> None:
      repo_root = Path(__file__).resolve().parents[2]
      content = (repo_root / doc_path).read_text(encoding="utf-8")
      # Find every code block (indented or fenced) mentioning allow_unauthenticated_query=True
      hits = re.findall(
          r"create_app\([^)]*allow_unauthenticated_query\s*=\s*True[^)]*\)",
          content,
          flags=re.DOTALL,
      )
      for hit in hits:
          assert "host=" in hit, (
              f"{doc_path}: example with allow_unauthenticated_query=True must include host= "
              f"(breaking change since v1.5.0). Offending snippet: {hit!r}"
          )
  ```
- Run RED: tests fail with current docs (4 failures expected, one per file).
- Apply edits → run again → 4 green.

**DoD:**
- [ ] 4 docs files updated; each has at least 1 example with `host="127.0.0.1"`.
- [ ] New test file `tests/unit/test_docs_breaking_change_examples.py` (4 parametrized cases).
- [ ] `pytest tests/unit/test_docs_breaking_change_examples.py -v` → 4 green.
- [ ] `grep -rn "allow_unauthenticated_query=True" docs/` → 0 occurrences without `host=` on the same expression / nearby line.
- [ ] `docs/migration/v1.4-to-v1.5.md` has a new section explicitly calling out the breaking change.
- [ ] CHANGELOG.md `[1.5.0]` section already mentions this (verified via `grep -A 5 "host=" CHANGELOG.md`); no further CHANGELOG edit required.
- [ ] Full offline `pytest --tb=no -q` → 5541 passed (5537 + 4); 0 failed.
- [ ] `ruff check src/ tests/` → All checks passed.
- [ ] `ruff format --check src/ tests/` → clean.
- [ ] `ty check src/swarmline/` → 0 diagnostics.
- [ ] Atomic commit: `docs: enforce explicit host= in serve examples (C4)` with body listing 4 files + cross-reference to audit P2 #5 + commit `0fa523b`.

**Code rules:** Docs-as-code: mechanically-verifiable invariant via test. DRY (single regex catches all 4 files). KISS (no docs framework changes; pure content edits).

---

## Risks and mitigation

| Risk | Probability | Mitigation |
|------|-------------|------------|
| Bounded-quantifier regex misses a legitimate URL pattern (false negative) | L | Stage 1 happy-path test + boundary test cover RFC 3986 cases; 256-char limit is 10× real-world userinfo |
| Docs test regex (Stage 3) is too narrow → silently passes broken examples | M | Test prints offending snippet via assert message; manual grep confirmation in DoD |
| `v1.5.1` appears in CHANGELOG (intentional historical mention) | L | Stage 2 invariant scoped to `src/`, not docs/CHANGELOG |
| New test files break collection (e.g., naming collision) | L | TDD: tests run RED first → if collection fails, fix structure before proceeding |
| Working tree diverges from `395acb2` during work | M | Each stage = 1 atomic commit; verify `git log --oneline -1` after each commit |
| 3 untracked memory-bank files (security plan + roadmap note + review report) get stale during stages | L | Optional Stage 0: pre-commit them as `chore(memory-bank)` before Stage 1; or batch them into a final `chore` commit after Stage 3. Decision deferred to executor; either approach is safe |

## Gate (plan success criterion)

After Stage 3 commit, all of:

1. **Code/docs:** 0 occurrences of `v1.5.1` in `src/`; 4 docs files have `host=` examples; ReDoS regex pattern in place.
2. **Tests:** 5541 passed (or higher); 0 failed; 9 net new tests vs `395acb2` baseline.
3. **Gates:** `ty check src/swarmline/` 0 diagnostics; `ruff check src/ tests/` clean; `ruff format --check` clean.
4. **Commits:** 3 atomic commits (one per Stage) on `main`, conventional-commit format, signed `Co-Authored-By: Claude Opus 4.7 (1M context)`.
5. **Reachability:** `python -c "import swarmline; print(swarmline.__version__)"` → `1.5.0` (unchanged — version string remains consolidated).

After Gate green: surface user the choice between (a) immediate public sync via `./scripts/sync-public.sh --tags` or (b) defer pending C3 operator decision (tag move vs version bump).

**Out-of-scope:** S1-S6 + N1-N5 from review report → tracked as `v1.5.1` follow-up patch backlog. C3 operator decision (tag/version paradox) → user-driven, not part of this plan.
