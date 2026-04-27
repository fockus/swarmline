# Code Review Report — post-v1.5.0 Security Audit Closure
Date: 2026-04-27 02:37
Files reviewed: 11 src + 9 tests (12 commits, range `3fae1b2..395acb2`)
Lines changed: +932 / -80

Multi-perspective review by 3 parallel independent agents:
- **Security Engineer** (audit verification + new vulnerabilities)
- **Code Reviewer** (SOLID / Clean Architecture / DRY / KISS / YAGNI)
- **Reality Checker** (production readiness, default verdict NEEDS WORK)

## Verdict

**🔴 NEEDS WORK — DO NOT PUBLISH TO PUBLIC PyPI YET.**

All four CI gates are green (pytest 5532, ty=0, ruff clean, format clean). Engineering quality of the audit fixes is solid (TDD, atomic commits, 80 new tests). However, three follow-up issues block public release: (1) Security review found a **HIGH-severity ReDoS** in the new URL-userinfo regex (3.4s on 50KB input — DoS amplifier on attacker-controlled error messages). (2) Reality checker found **5 documentation/source artefacts referencing a non-existent v1.5.1**, and a **tag/source version paradox** (`v1.5.0` tag points at the pre-audit `3fae1b2`, while `pyproject.toml` says `1.5.0` at HEAD `395acb2` too). (3) Architecture review found two SERIOUS findings — cross-provider inconsistency in sandbox denylist enforcement (LSP smell across E2B vs Docker/OpenShell) and a now-meaningless wrapper `_build_subprocess_env` in `cli/runtime.py`.

## Critical (release blockers)

### C1. ReDoS in `redaction.py` URL-userinfo pattern — HIGH security
**File:** `src/swarmline/observability/redaction.py:46`
**Pattern:** `(\w+://)([^:/@\s]+):([^@/\s]+)@`
**Evidence:** 50KB input → 3.4s; 100KB → ~15s catastrophic backtracking. Reachable from every redacted error path: `serve/app.py:131` (HTTP 500), `runtime/thin/errors.py:50` (provider crash), `runtime/cli/runtime.py:248` (CLI stderr). A single attacker-controlled URL embedded in a provider exception or stderr buffer can stall the event loop.
**Recommendation:** Replace with bounded-quantifier variant:
```python
re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]{0,30}://)([^:@\s/]{1,256}):([^@\s/]{1,256})@")
```
Add regression test asserting <50ms on 100KB input.

### C2. `serve/app.py` references non-existent `v1.5.1` — HIGH consistency
**Files:**
- `src/swarmline/serve/app.py:163` (comment) — *"v1.5.1: the v1.5.0 deprecation warning..."*
- `src/swarmline/serve/app.py:170` (user-facing `ValueError`) — *"requires an explicit host= argument since v1.5.1"*
- `src/swarmline/serve/app.py:159-161` (docstring) — still says *"host=None still accepted but logs warning"* (false; now raises)
**Evidence:** After consolidation commit `395acb2`, no `v1.5.1` exists. Anyone hitting the error message will search the changelog and find nothing.
**Recommendation:** Replace `since v1.5.1` → `since v1.5.0 (security audit closure)` or final shipping version. Refresh docstring lines 151-161.

### C3. Tag/version paradox — HIGH consistency
**Evidence:** Local tag `v1.5.0` → `3fae1b2` (pre-audit). HEAD `395acb2` also has `pyproject.toml: version = "1.5.0"`. Two distinct commits report the same wheel version. PyPI cache poisoning / consumer integrity confusion is a real risk on public sync.
**Recommendation:** Pick one:
- (a) **Move tag** — `git tag -d v1.5.0 && git tag v1.5.0 395acb2 && git push --force-with-lease origin v1.5.0` (destructive but private-only; tag never went public).
- (b) **Bump version** — re-instate `1.5.1` in pyproject + serve/app.py + CHANGELOG, restore separate `[1.5.1]` section, tag `v1.5.1` on `395acb2`. v1.5.0 stays at `3fae1b2`.

### C4. Documentation drift — HIGH UX
**Files:**
- `docs/migration-guide.md:54-58` — shows `create_app(..., allow_unauthenticated_query=True)` without `host=`. Now hard-fails.
- `docs/migration/v1.4-to-v1.5.md` — zero references to the breaking change. Last touched in `d541edb` (April 25, **before** the audit).
- `docs/getting-started.md:146` — references `allow_unauthenticated_query` without host requirement.
- `docs/configuration.md:65` — same.
**Recommendation:** Update all four files with the migration snippet `create_app(agent, allow_unauthenticated_query=True, host="127.0.0.1")` plus rationale (audit P2 #5).

## Serious (architecture / coverage gaps)

### S1. Cross-provider inconsistency in sandbox denylist — LSP/Clean Arch
**Files:** `src/swarmline/tools/sandbox_e2b.py:79-107` vs `tools/sandbox_docker.py:64-76` vs `tools/sandbox_openshell.py:127-141`
**Evidence:** Three providers behind the same `SandboxProvider` Protocol enforce denylist with different policies:
- E2B (post-audit): recursive `sh -c` payload re-parse
- Docker / OpenShell: flat outright-block of `_DENYLIST_WRAPPERS`
A `denied_commands={"rm"}` config rejects `sh -c 'echo hi'` on docker/openshell but accepts it on E2B. Same Protocol, different LSP behaviour.
**Recommendation:** Lift `_DENYLIST_WRAPPERS` to a shared module under `tools/` and apply consistently across all 3 providers, or document the divergence as an explicit Protocol-level decision.

### S2. Lowercase env-style keys not redacted — MEDIUM security gap
**File:** `src/swarmline/observability/redaction.py:51`
**Pattern:** `\b[A-Z][A-Z0-9_]*(?:_KEY|_TOKEN|_SECRET|_PASSWORD)=...` — anchored to uppercase.
**Evidence:** `api_key=secret`, `database_password=...`, `client_secret=...`, `Db_Password=...` all pass through unchanged. Provider exception strings frequently embed lowercase config keys (e.g. `KeyError: 'api_key'` followed by config dump).
**Quoted values also miss**: `OPENAI_API_KEY="actual-secret"` — value class `[^\s'"]+` halts at `"`/`'`, matches empty string, secret survives.
**Recommendation:** Add `re.IGNORECASE`, broaden value class, add explicit lowercase tokens (`api_key`, `apikey`, `client_secret`).

### S3. `sk-ant-` pattern is dead code — MEDIUM completeness
**File:** `src/swarmline/observability/redaction.py:31-38`
**Evidence:** Generic `sk-` regex (line 31) runs first → matches and replaces `sk-ant-...` with `sk-[REDACTED]` → second `sk-ant-` regex (line 36) finds nothing. Anthropic-specific replacement template is never emitted; provenance hint promised in docstring is lost.
**Recommendation:** Either reorder so `sk-ant-` runs first, or drop the redundant pattern. `DEFAULT_SECRET_PATTERNS` order is load-bearing — document.

### S4. `_build_subprocess_env` wrapper adds zero behaviour — KISS/YAGNI
**File:** `src/swarmline/runtime/cli/runtime.py:36-46`
**Evidence:** 4-line forward to `build_subprocess_env(...)` purely for "callers that depend on the CliConfig-typed signature" — no such callers exist in the diff. Docstring even says *"New code should call build_subprocess_env directly."*
**Recommendation:** Inline at the single use site (line 171), delete the wrapper.

### S5. pi_sdk env overrides bypass allowlist — MEDIUM defence-in-depth
**File:** `src/swarmline/runtime/_subprocess_env.py:41`
**Evidence:** `overrides` are merged AFTER the allowlist filter. `PiSdkOptions(env={"BLOCKED_SECRET": "x"})` injects `BLOCKED_SECRET` into child env even though it's not in `env_allowlist`. Verified live.
**Severity context:** "operator-controlled" — but means allowlist is **advisory**, not enforcing. Any code path that builds `PiSdkOptions` from untrusted config (YAML, dynamic per-request, A2A handoff) defeats the audit P1 fix.
**Recommendation:** Validate `overrides` keys against `env_allowlist` (or a separate `env_overrides_allowlist`) before merging. At minimum, log a security warning for outside-allowlist override.

### S6. E2B shell-wrapper bypasses (defence-in-depth, not primary) — MEDIUM
**File:** `src/swarmline/tools/sandbox_e2b.py:91-99`
**Confirmed bypasses:** `sh -c $'rm /etc/passwd'` (ANSI-C quoting), `sh -c '\`rm /tmp/x\`'` (backticks), `env -i sh -c 'rm /tmp/x'` (env wrapper), `busybox sh -c '...'`, `python -c "import os; os.system('rm /tmp/x')"`, `sh --command "..."`.
**Severity context:** Sandbox primary boundary is E2B Firecracker isolation — denylist is defence-in-depth. Audit explicitly listed `sh -c 'rm ...'` and the fix only addresses the literal example.
**Recommendation:** Pivot from "recursive parse" to "tokenized basename match across all words after shlex.split, with descent into known eval flags (`-c`, `-e`, `--command`, `--exec`)".

## Notes

### N1. JSONL sink replacement template divergence — DRY
**Files:** `src/swarmline/observability/jsonl_sink.py:48-50,143-147` vs `redaction.py:21-54`
JSONL strips per-pattern replacement template, substitutes flat `[REDACTED]`. Bearer in JSONL → `[REDACTED]`; same Bearer in error → `Bearer [REDACTED]`. Same input, different output between two surfaces.
**Recommendation:** Share the (pattern, replacement) tuples directly, or document the divergence as intentional log-compaction.

### N2. Missing AWS access keys (AKIA…) and JWT (eyJ…) — coverage
**File:** `src/swarmline/observability/redaction.py`
AWS access key IDs end in `_ID` (e.g. `AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE`) — not matched by env-style regex. JWTs (`eyJ...`) used by Auth0/Cognito/Supabase — no pattern. Audit P2 #6 claim "Bearer tokens" implies these but doesn't deliver.
**Recommendation:** Add patterns for AKIA, ASIA prefixes; add JWT pattern `eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+`.

### N3. Stale docstring in `path_safety.py:13-19` — cosmetic
Over-sells what it does ("`..` rejected via substring guard, but explicit set documents intent" — explicit set is required only for `.`).

### N4. Test quality nits
- `test_observability_redaction.py:25-26` — weak `assert "[REDACTED]" in result or "***" in result`. Pick one (impl emits `[REDACTED]`).
- `test_observability_redaction.py:55-58` — tautological disjunction.
- `test_observability_redaction.py:101-104` — asserts `redact_secrets(None)` returns `str` but not `""`.
- Missing JSONL value-pattern integration test in `test_jsonl_telemetry_sink.py` — DRY refactor at `jsonl_sink.py:48-50` could silently regress.
- `test_path_safety.py` — no whitespace-host edge case (`host=" "`).

### N5. `cli/runtime.py:262-268` — error redaction inconsistency
Subprocess startup-failure branch does NOT include exception message redacted. Subprocess exit-failure branch DOES (line 248). Same flow, different diagnostic verbosity. Add `redact_secrets(str(exc))` symmetrically.

## Tests

- Unit: ✅ 5532 passed, 7 skipped, 5 deselected (re-verified)
- Integration: ✅ included in unit count
- E2E: ✅ smoke `import swarmline; __version__ == "1.5.0"`
- ty: ✅ 0 diagnostics
- ruff: ✅ All checks passed
- format: ✅ 768 files already formatted
- **Coverage gaps:** missing JSONL value-pattern integration test (N4); `inherit_host_env=True` not parametrized in pi_sdk tests; no ReDoS-safety regression test for redaction patterns.

## Plan alignment

Reference: `.memory-bank/plans/2026-04-27_fix_security-audit.md` (7 stages).

- **Implemented (per plan):** Stage 1 (path `.`) ✅, Stage 2 (pi_sdk env) ✅, Stage 3 (E2B shell wrapper) ✅ (with caveats — see S6), Stage 4 (URL scheme) ✅, Stage 5 (host=None hard-fail) ✅, Stage 6 (redaction) ✅ (with caveats — see C1, S2, S3, N2), Stage 7 (release prep) ✅ → reverted to 1.5.0.
- **Not implemented:** No plan item explicitly required cross-provider denylist alignment (S1) — emerged during review. Documentation update for breaking change (C4) was not part of the plan but is essential pre-publish.
- **Outside the plan:** Plan implicitly assumed `1.5.1` minor release; final consolidation under `1.5.0` reverted that, leaving `v1.5.1` references in source/error messages (C2). Plan should have included a "doc sweep" stage.

## Summary (1-3 sentences)

The 6 audit findings are fully or substantially closed at the **engineering** level (tests, types, lint clean), but the **release-readiness** layer has C1 (HIGH ReDoS, exploitable from any error path), C2-C4 (consistency / documentation drift referencing a non-existent `v1.5.1`), plus 6 SERIOUS gaps in coverage and architecture. Recommendation: **ship as v1.5.0 with a follow-up "Stage 8 polish" plan** addressing C1+C2+C4 minimum (security ReDoS + version-string sweep + docs update) before public PyPI sync. S1, S2, S3, S5, S6, N1-N5 can ship as `v1.5.1` patch within ~1-2 weeks. Tag move/bump (C3) is a destructive operator decision — not a code action.

## Suggested follow-up plan (Stage 8 — pre-publish polish)

| # | Severity | Effort | Action |
|---|----------|--------|--------|
| C1 | **HIGH** (security) | 30 min | ReDoS-safe URL-userinfo regex + 100KB regression test |
| C2 | **HIGH** (consistency) | 15 min | Replace `since v1.5.1` strings in `serve/app.py` |
| C3 | **HIGH** (operator decision) | 5 min | Move tag v1.5.0 → 395acb2 (destructive — needs approval) |
| C4 | **HIGH** (UX) | 1 h | Update 4 docs files for breaking change |
| S1 | SERIOUS (LSP) | 2 h | Cross-provider denylist alignment |
| S2 | MEDIUM | 30 min | Lowercase env keys + quoted values + IGNORECASE |
| S3 | MEDIUM | 10 min | Reorder sk-/sk-ant- patterns + test |
| S4 | KISS | 10 min | Drop dead `_build_subprocess_env` wrapper |
| S5 | MEDIUM | 30 min | Validate `overrides` against allowlist |
| S6 | MEDIUM (defence-depth) | 1 h | Broader E2B wrapper detection (busybox/env/python) |
| N1 | DRY | 15 min | Share replacement tuple between redaction.py and jsonl_sink.py |
| N2 | coverage | 30 min | AWS AKIA + JWT patterns |
| N3 | cosmetic | 5 min | path_safety docstring tightening |
| N4 | tests | 30 min | Test assertion fixes + JSONL regression test |
| N5 | redaction | 10 min | Symmetric redact in subprocess startup-failure path |

**Total polish:** ~7 hours. Recommended split: **C1+C2+C4** (1.5h) for v1.5.0 publish; rest as v1.5.1 within 1-2 weeks.
