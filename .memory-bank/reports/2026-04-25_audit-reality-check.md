# Reality Check — swarmline v1.5.0 production readiness

**Verdict:** **NEEDS WORK** — CI lint job will fail; CHANGELOG has empty `[Unreleased]` despite 55 commits and 7 phases of features; pyproject still says 1.4.1.

**Date:** 2026-04-25
**Auditor:** Reality Checker (skeptic-by-default)
**Repo:** `/Users/fockus/Apps/swarmline` (HEAD = 1c896cb, branch = main, clean)

---

## TL;DR

Tests genuinely pass and ty baseline is genuinely 0 — the headline numbers are real. **But the release is not actually packaged**: pyproject.toml is still `1.4.1`, the CHANGELOG `[Unreleased]` section is empty, and 458 lint/format issues will block the CI green tick. None of the new v1.5.0 surface (Phases 11-17, structured workflows, agent packs, JSONL telemetry sink, pi-sdk runtime) is in user-facing docs or the changelog. Releasing **today** = shipping unannounced features and breaking the public CI workflow. This is a 2-4 hour fix, but it is a fix, not a "ready-to-go".

---

## Verified facts (with evidence)

- **ty strict-mode = 0** — `ty check src/swarmline/` → `All checks passed!`. Baseline file `tests/architecture/ty_baseline.txt` = `0`. Architecture meta-test (`test_ty_diagnostics_at_or_below_baseline`) PASSES. ADR-003 release gate fulfilled.
- **5352 tests pass offline** — `pytest -q` (system Python 3.12.7) → `5352 passed, 7 skipped, 5 deselected in 53.06s`. Higher run count: `5354 passed, 7 skipped, 3 deselected` (with --cov). Claim accurate within ±2 tests due to live/slow markers.
- **Test collection consistent** — `5359/5364 collected (5 deselected)` matches stated counts.
- **Coverage = 86%** (NOT 89% as claimed — small overstatement). 21,771 statements, 2,954 missing.
- **conftest.py sys.path[0] shim works correctly** — verified `import swarmline` in test context resolves to `/Users/fockus/Apps/swarmline/src/swarmline/__init__.py` (1.4.1) despite presence of 3 colliding sibling editable installs (cognitia, taskloom, aura).
- **CI workflow exists** with proper jobs: lint (ruff), typecheck (ty), tests (3.11/3.12/3.13 matrix), architecture (slow). Publish workflow has OIDC + multi-Python smoke. `.github/workflows/{ci,docs,publish}.yml` all present.
- **41 example smoke tests pass** — `tests/integration/test_examples_smoke.py` 41 passed in 13.30s with system pytest.
- **Test quality is real** — spot-checked `test_agent_pack_resolver.py`, `test_jsonl_telemetry_sink.py`: AAA pattern, behavioral asserts (not constructor smoke), edge cases covered (empty, redaction, attach/detach).
- **No TODO/FIXME pollution** — 34 hits, all are `TaskStatus.TODO` enum values (legitimate state machine), zero literal `# TODO:` comments in source.
- **Memory Bank is alive and current** — `.memory-bank/STATUS.md` accurately states "Release gate status: GREEN — `ty check` All checks passed! Готово к v1.5.0 release".

---

## Falsified / suspicious claims

### ❌ FALSIFIED: "Python 3.10+"

**Source of claim:** `CLAUDE.md`, `AGENTS.md`, project doc.
**Evidence (pyproject.toml line 9):** `requires-python = ">=3.11"`.
**Evidence (publish.yml line 32):** Tests install on Python 3.10 in matrix — **install will fail** because `pip install` honors `requires-python`.
**Severity:** HIGH for releases — test-install on 3.10 will fail in CI on tag push.

### ❌ FALSIFIED: "89%+ coverage"

**Source of claim:** Audit prompt, multiple memory-bank notes.
**Evidence:** `pytest --cov=swarmline` (real run, 75.95s) → `TOTAL 21771 2954 86%`.
**Reality:** 86%, not 89%. Small overstatement. Per-target: core/business modules mostly 90-100%, infrastructure modules in the 50-85% band.

### ❌ FALSIFIED: "Domain in `protocols.py` and `types.py`"

**Source of claim:** `CLAUDE.md` "Layers" section.
**Evidence:** `src/swarmline/protocols.py` does not exist; only `src/swarmline/protocols/` package (12 files) and `src/swarmline/types.py` (22 lines, only `TurnContext`/`ContextPack`/`SkillSet` re-exports). Real domain types live in `domain_types.py`, `memory/types.py`, `runtime/types.py`. `CLAUDE.md` architecture section is **stale**.
**Severity:** LOW for code, HIGH for onboarding — every new contributor reads CLAUDE.md and gets disoriented.

### ⚠️ SUSPICIOUS: "Clean Architecture: Domain → Infrastructure"

**Evidence of inversion:**
- `src/swarmline/runtime/types.py` (presumably "infra") imports from `swarmline.compaction`, `swarmline.runtime.cancellation`, `swarmline.runtime.capabilities`, `swarmline.runtime.cost`. **Forward direction OK.**
- BUT `src/swarmline/protocols/runtime.py` imports `from swarmline.domain_types import ...` and via TYPE_CHECKING `from swarmline.runtime.types import RuntimeConfig` — **protocols package depends on its own consumers' types** through TYPE_CHECKING.
- `src/swarmline/protocols/memory.py` imports `from swarmline.memory.types import ...` — protocols importing from a concrete-storage subtree. Likely OK if `memory/types.py` is itself pure domain (it is — only stdlib + dataclasses). Architecturally awkward but not strictly broken.
- `src/swarmline/agent/*` (Application) imports from `swarmline.runtime.types` — that's Application → Infrastructure types, but acceptable if those types are protocol-shaped contracts (they are: `Message`, `RuntimeConfig`, `RuntimeEvent`, `ToolSpec` are dataclasses, not implementations).
**Verdict:** No obvious circular or downward leak. The architecture is "good enough" but the verbal claim of strict three-layer separation is sloppy. Real layout is more like "shared core types + application + infrastructure".

### ⚠️ SUSPICIOUS: "All 4263 tests pass on each phase" (memory-bank claim)

**Reality:** 5352 tests now (suite has grown). Old number is stale. Claim that suite passed on each phase commit is plausible (every Phase commit message ends "tests pass, ruff clean") but only verifiable by checking out each commit, which I did not do — I trust the trail.

---

## Critical missing artifacts (BLOCKING for v1.5.0)

| Artifact | Status | Impact |
|---|---|---|
| **CHANGELOG.md `[Unreleased]` filled in** | **EMPTY** — only `## [Unreleased]` heading, no content under it | **BLOCKING** — every published release needs this |
| **pyproject.toml version bumped to 1.5.0** | Still `1.4.1` | **BLOCKING** — release/v1.5.0 branch hasn't been created yet |
| **v1.4 → v1.5 migration guide** | MISSING — `docs/migration-guide.md` ends at v1.4.0 stabilization | HIGH — major minor release without migration notes |
| **SECURITY.md** | MISSING | MEDIUM — public repo SHOULD have responsible-disclosure policy |
| **Pre-commit hooks** | MISSING — `.pre-commit-config.yaml` not present | MEDIUM — would catch the 458 lint/format issues |
| **Public docs of new features** | MISSING — Phase 11-17 not in `docs/index.md`, getting-started, capabilities, advanced | HIGH — users won't discover thinking events, multimodal, session resume, parallel agents, agent packs, JSONL telemetry |

Found:
- `CONTRIBUTING.md` ✅
- `LICENSE` ✅ (MIT)
- `mkdocs.yml` ✅
- `py.typed` marker ✅ (in `src/swarmline/py.typed`, included in wheel via `force-include`)
- `docs/releasing.md` ✅ (has SemVer policy)

---

## Test reality

```
5352 passed, 7 skipped, 5 deselected in 53.06s   # offline run
5354 passed, 7 skipped, 3 deselected in 75.95s   # with --cov
```

- 369 test files / 382 source files. Reasonable density.
- 283 unit / 66 integration / 13 e2e / 2 security / architecture-meta. Trophy-shaped, integration-leaning.
- Spot-checked tests are real (AAA, behavioral, edge cases, no constructor stubs).
- 5 tests deselected by `addopts = ["-m", "not live"]` — confirmed live tests exist but are correctly excluded by default.
- 41/41 example smoke tests pass — non-trivial because each example runs as a subprocess.

**Caveat:** Coverage column shows 0% for `todo/db_provider.py` (29 stmts) and `todo/schema.py` (3 stmts). Either dead code or unexercised infrastructure — investigate before release. Web `crawl4ai.py` (55%), `tools/extractors.py` (33%), `session/backends_postgres.py` (50%) are the other dark zones; all are integration-heavy modules where mocking would be heavy and live tests gated. Acceptable per "infrastructure 70%+" rule **except** the 0% modules.

---

## Type reality

```
$ ty check src/swarmline/
All checks passed!
```

```
tests/architecture/test_ty_strict_mode.py
  test_ty_baseline_file_exists                       PASSED
  test_ty_diagnostics_at_or_below_baseline           PASSED
  test_ci_workflow_has_ty_step                       PASSED
```

ty baseline file = `0`, architecture meta-test enforces it. **Verified clean.** ADR-003 fulfilled.

---

## Lint reality

```
$ ruff check src/ tests/
tests/unit/test_pi_sdk_runtime.py:5:8: F401 [*] `asyncio` imported but unused
Found 1 error.
[*] 1 fixable with the `--fix` option.
```

```
$ ruff format --check src/ tests/
457 files would be reformatted, 294 files already formatted
```

**This is the single most important finding.** CI workflow `.github/workflows/ci.yml` lint job runs both `ruff check` and `ruff format --check`. Both will fail. **Tag push → red CI → publish blocked.**

Fix is trivial — `ruff check --fix src/ tests/ && ruff format src/ tests/` — but it must be done before any release commit.

---

## Backward compat reality

55 commits since `v1.4.0`. Nothing in `[Unreleased]` of CHANGELOG. New surface introduced (from commits + memory-bank trail):

- ProjectInstructionFilter, SystemReminderFilter (Phase 11)
- Domain allow/block filter, MCP resource reading, `read_mcp_resource` tool, ResourceDescriptor (Phase 12)
- ConversationCompactionFilter, CompactionConfig, 3-tier compaction cascade (Phase 13)
- JsonlMessageStore, Conversation.resume, auto-persist, auto-compaction-on-resume (Phase 14)
- ThinkingConfig, RuntimeEvent.thinking_delta factory, LlmCallResult, AnthropicAdapter thinking (Phase 15)
- ContentBlock/TextBlock/ImageBlock, multimodal in Anthropic/OpenAI/Google adapters, BinaryReadProvider, PDF/Jupyter extractors (Phase 16)
- SubagentSpec.isolation, worktree lifecycle, spawn_agent isolation, RuntimeEvent.background_complete, monitor_agent (Phase 17)
- pi-sdk runtime (4th adapter, Node.js bridge)
- Sprint 1A/1B: ty diagnostics 75 → 0
- AgentPackResolver, AgentPackResource, ResolvedAgentPack
- JsonlTelemetrySink (observability)
- TypedPipeline, structured workflow primitives

Public `__all__` in `src/swarmline/__init__.py` — adds `AgentPackResolver`, `AgentPackResource`, `ResolvedAgentPack`, `CompactionConfig`, `ConversationCompactionFilter`, `ProjectInstructionFilter`, `JsonlMessageStore`, `ThinkingConfig`, `ContentBlock`, `ImageBlock`, `TextBlock` (verified). All additive — no obvious deletions detected.

Manual deletion check: `git diff v1.4.0 -- src/swarmline/__init__.py | grep "^-from"` would clarify; not run here, but unchanged sections look additive.

**No silent breaking changes detected** in surface (would need a deeper public-API diff). But **also no documentation of all the additions** — users discovering "I can do thinking events" only via reading commit messages.

---

## Examples reality

- `examples/` has 32 numbered examples (01–33, with 31 missing) + `skills/` + README.md.
- All 32 examples pass offline subprocess tests (the smoke matrix). Source files all parse with `ast.parse`.
- Example 28 (`opentelemetry_tracing.py`) had failed when running the broken sibling-venv pytest, but with system Python 3.12.7 (which has all extras installed) it passes. **However** — this means without `swarmline[otel]`, example 28 errors out gracefully. Acceptable.

Examples cover: facade, tool decorator, structured output, middleware, hooks, filters, guardrails, RAG, memory, sessions, budget, retry, cancel, thinking, event bus, UI projection, runtime switching, custom runtime, CLI runtime, workflow graph, agent-as-tool, task queue, agent registry, deep research (498 lines!), shopping agent, code project team, nano claw, otel, structured-pydantic, A2A, eval. **Strong coverage for users.**

Memory Bank trail confirms each phase added a regression test for examples.

---

## Real-world readiness signals

| Signal | Status |
|---|---|
| Container example | NONE in `examples/` |
| Deployment doc | NONE (`docs/deployment.md` doesn't exist) |
| Observability setup recipe | `docs/observability.md` exists (37 lines spot-checked, complete with event bus + JSONL sink + OTEL bridge) |
| Production logging guidance | `docs/observability.md` covers structlog, otel |
| Benchmark suite | `benchmarks/` exists with 2 benches (`bench_context.py`, `bench_memory.py`) — modest but present |
| Performance evidence in CHANGELOG | NONE — no benchmark numbers documented |
| `examples/30_a2a_agent.py`, `28_opentelemetry_tracing.py` | Both present, smoke-tested |
| `swarmline serve`, `swarmline-mcp`, `swarmline-daemon` | All registered as `[project.scripts]` entry points |
| **Real-world deployment proof (production users)** | UNKNOWN — no testimonials, case studies, or external usage in repo. "Beta" classifier in pyproject (`Development Status :: 4 - Beta`) is honest. |

---

## Local dev hygiene (NOT a release blocker, but a smell)

Your local pyenv 3.12.7 has 3 colliding `swarmline` editable installs:
- `/Users/fockus/Apps/aura/...`
- `/Users/fockus/Apps/cognitia/src/swarmline/`
- `/Users/fockus/Apps/taskloom/packages/swarmline/src`

Plus `/Users/fockus/Apps/swarmline/.venv/bin/pytest` is a stale shim with a shebang pointing to `/Users/fockus/Apps/cognitia/.venv/bin/python3` (which IS broken — earlier when I tried `.venv/bin/pytest` it ran a totally different code path and produced 142 failed / 69 errors).

**For the release itself this is fine** — CI uses a fresh GitHub Actions runner. **For your day-to-day** — you should `pip uninstall -y swarmline` from each of those venvs, or your imports are non-deterministic.

---

## 5 concrete problems (ranked by impact)

| # | Problem | Severity | Evidence | Fix |
|---|---|---|---|---|
| 1 | **CI lint job will fail on tag push** — 1 ruff error + 457 unformatted files | **CRITICAL** | `ruff check src/ tests/` → 1 error in `tests/unit/test_pi_sdk_runtime.py:5`. `ruff format --check` → "457 files would be reformatted". | `ruff check --fix src/ tests/ && ruff format src/ tests/` (5 min) → commit on release/v1.5.0 branch |
| 2 | **CHANGELOG.md `[Unreleased]` is empty** despite 7 phases of features | **BLOCKING** | `sed -n '/^## \[Unreleased\]/,/^## \[1\.4\.0\]/p' CHANGELOG.md` returns just two heading lines | Write the v1.5.0 changelog: identity filters, MCP resources, compaction, sessions, thinking, multimodal, parallel, agent packs, JSONL sink, structured workflows, ty=0, pi-sdk runtime. ~30 min. |
| 3 | **pyproject.toml version still `1.4.1`** — release branch not created | **BLOCKING** | `grep version pyproject.toml` → `version = "1.4.1"` | `git checkout -b release/v1.5.0`, bump to `1.5.0`, commit. 2 min. |
| 4 | **publish.yml test-install matrix includes Python 3.10** — pyproject `requires-python = ">=3.11"` | **HIGH** | publish.yml:32 `python-version: ['3.10', '3.11', '3.12', '3.13']` vs pyproject `requires-python = ">=3.11"` | Drop `'3.10'` from publish.yml matrix OR loosen `requires-python` to `>=3.10`. Pick one (CI matrix is 3.11+). 2 min. |
| 5 | **No user-facing docs for v1.5.0 features** — multimodal, session resume, thinking events, parallel agents, agent packs, JSONL sink, pi-sdk runtime | **HIGH** | `grep -E "ContentBlock\|JsonlMessageStore\|multimodal\|session resume" docs/*.md` → almost nothing | Add to `docs/capabilities.md`, `docs/api-reference.md`, new `docs/multimodal.md` and `docs/sessions.md`. Update `docs/migration-guide.md` with v1.4 → v1.5 section. ~2-4 hours. |

Plus secondary issues:
- `CLAUDE.md` and `AGENTS.md` say "Python 3.10+" but pyproject says 3.11+. Stale claim. (Public docs say 3.11+, fortunately.)
- `AGENTS.md` and `CLAUDE.md` claim domain protocols live in `protocols.py`/`types.py` — they don't (now `protocols/` package, `domain_types.py`, `runtime/types.py`).
- No SECURITY.md.
- No pre-commit config (issue #1 wouldn't have happened with one).
- 0% coverage on `todo/db_provider.py` — investigate; either delete or test.
- `coverage` claim of 89% should be corrected to ~86%.

---

## Final verdict

**Безопасно ли релизить v1.5.0 СЕГОДНЯ? NOT YET.**

The library itself is **good code** — tests are real, types are clean, architecture is sane, examples are runnable. The product-quality bar is met. **But the release packaging is not done.** Tagging `v1.5.0` right now ships:

1. A red CI job (lint + format).
2. A `[Unreleased]` changelog with no content.
3. A pyproject version that doesn't match the tag.
4. A test-install on Python 3.10 that will fail.
5. Several major features users have no documented way to discover.

**To flip to YES — required actions, ordered, ~3-5 hours total:**

1. (5 min) `ruff check --fix src/ tests/ && ruff format src/ tests/` — eliminate the 458 lint/format issues. Commit.
2. (2 min) Drop `'3.10'` from `publish.yml` test-install matrix (or loosen `requires-python`).
3. (2 min) `git checkout -b release/v1.5.0`, bump `pyproject.toml` to `1.5.0`.
4. (30 min) Write `CHANGELOG.md [1.5.0]` entry, covering all 7 phases + Sprint 1A/1B + new optional deps + agent packs + JSONL sink + pi-sdk + structured workflows. Update Unreleased link.
5. (2-4 h) Add v1.4 → v1.5 migration section in `docs/migration-guide.md` + minimum-viable user docs for each new feature surface in `docs/capabilities.md`.
6. (5 min) Fix stale "Python 3.10+" in CLAUDE.md / AGENTS.md.
7. (10 min) Run `pytest -q -m "not live"` once more on a clean venv to verify nothing regressed during the formatting pass.
8. Tag, push, sync-public, watch CI green, then PyPI auto-publishes.

**Optional but recommended (post-1.5):**
- Add SECURITY.md.
- Add `.pre-commit-config.yaml` with ruff + ty.
- Investigate 0% coverage modules (delete or test).
- Resolve the local pyenv editable-install collision so devs aren't booby-trapped.
- Correct memory-bank coverage claim from "89%+" to "86%".

---

**Auditor:** Reality Checker
**Method:** real binary execution + filesystem evidence + memory-bank cross-reference
**Files of interest:**
- `/Users/fockus/Apps/swarmline/CHANGELOG.md` (empty `[Unreleased]`)
- `/Users/fockus/Apps/swarmline/pyproject.toml` (still 1.4.1)
- `/Users/fockus/Apps/swarmline/.github/workflows/ci.yml` + `publish.yml`
- `/Users/fockus/Apps/swarmline/tests/architecture/ty_baseline.txt` (= 0, locked)
- `/Users/fockus/Apps/swarmline/.memory-bank/STATUS.md` (correctly says ready, but doesn't catch the lint/format & changelog gaps)
- `/Users/fockus/Apps/swarmline/tests/unit/test_pi_sdk_runtime.py:5` (1 lint error)
- `/Users/fockus/Apps/swarmline/docs/migration-guide.md` (ends at v1.4.0)
- `/Users/fockus/Apps/swarmline/CLAUDE.md` and `/Users/fockus/Apps/swarmline/AGENTS.md` (stale "Python 3.10+" + stale layer-layout claim)
