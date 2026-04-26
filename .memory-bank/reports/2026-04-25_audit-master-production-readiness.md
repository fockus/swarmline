# Master Production-Readiness Audit — swarmline v1.4.1 → v1.5.0

**Date:** 2026-04-25
**Auditors:** 4 parallel specialists (Backend Architect / Code Reviewer / Security Engineer / Reality Checker)
**Scope:** Full source (~336 .py files), tests (5352), docs (`docs/`), examples (32 files), build/CI

---

## TL;DR — Final Verdict

> **NOT READY for v1.5.0 release TODAY.**
> ~11–18 hours of focused work flips this to **READY**. No CVE-class vulnerabilities, no architectural blockers, but several user-visible bugs + missing release packaging artifacts.

| Dimension | Verdict | Score |
|-----------|---------|-------|
| **Architecture** | CONDITIONAL — 3 critical blockers | 7/10 |
| **DX vs FastAPI** | GOOD WITH CAVEATS — 5 release-blocking DX bugs | 6/10 |
| **Security** | NEEDS WORK — no critical, 4 medium | 8/10 |
| **Reality / Packaging** | NEEDS WORK — 5 packaging blockers | 5/10 |
| **Overall production-readiness** | **CONDITIONAL** | **6.5/10** |

The library **code** is genuinely strong. The **release packaging is incomplete**, and **first-impression DX has 5 paper-cuts** that will burn early adopters.

---

## Cross-cutting findings (consensus across ≥2 auditors)

### CRITICAL (release blockers — fix all before v1.5.0)

| # | Issue | Auditors | Severity | File:line | Fix effort |
|---|-------|----------|----------|-----------|------------|
| C-1 | **Test isolation broken** — 141/4641 unit tests fail when run together due to `observability/logger.py:22-27` writing stdout with `force=True` | Architect, Reality Checker | CRITICAL | `observability/logger.py:22-27` | 2h |
| C-2 | **`JsonlTelemetrySink.record` blocks event loop** — sync file I/O inside `async def` | Architect | CRITICAL | `observability/jsonl_sink.py:49-60` | 1h |
| C-3 | **CLI `--format json` corrupted by structlog logs** — same root cause as C-1; downstream `jq`/`json.loads` consumers break | Architect, Reality Checker | CRITICAL | `observability/logger.py` | (covered by C-1) |
| C-4 | **CHANGELOG `[Unreleased]` is empty** despite 55 commits | Reality Checker | BLOCKING | `CHANGELOG.md` | 30min |
| C-5 | **`pyproject.toml` still at `1.4.1`** — no release branch, no version bump | Reality Checker | BLOCKING | `pyproject.toml` | 2min |
| C-6 | **CI lint failure** — 1 ruff error in `tests/unit/test_pi_sdk_runtime.py:5` + 457 unformatted files | Reality Checker | CRITICAL | (CI) | 5min |
| C-7 | **`publish.yml` matrix includes Python 3.10** but `pyproject` requires `>=3.11` | Reality Checker | HIGH | `.github/workflows/publish.yml` | 2min |
| C-8 | **Default runtime mismatch**: `AgentConfig.runtime = "claude_sdk"` but all docs/examples use `"thin"` — first-time user with no claude_agent_sdk installed hits ImportError on hello-world | Code Reviewer | CRITICAL | `agent/config.py:35` | 1h |
| C-9 | **Russian error string** in user-facing path: `"Ошибка LLM API ..."` | Code Reviewer | CRITICAL (i18n) | `runtime/thin/errors.py:45` | 5min |
| C-10 | **Docs lie**: `agent-facade.md:36` says "only `runtime` typically required" but `__post_init__` rejects empty `system_prompt` | Code Reviewer | HIGH (credibility) | `docs/agent-facade.md:36` | 5min |

### HIGH-severity (strongly recommended pre-v1.5.0)

| # | Issue | Auditors | Severity | File:line | Fix effort |
|---|-------|----------|----------|-----------|------------|
| H-1 | **`__all__` is too noisy** (51 names) — many infrastructure leaked publicly | Code Reviewer, Architect (extensibility) | HIGH | `swarmline/__init__.py` | 2h |
| H-2 | **`examples/01_agent_basics.py` is 176 LOC, 80 of mock boilerplate** — first impression catastrophe | Code Reviewer | HIGH | `examples/01_agent_basics.py` | 4h |
| H-3 | **No user-facing docs for v1.5.0 features** (Phases 11-17, agent packs, multimodal, sessions, JSONL sink, pi-sdk runtime) | Reality Checker | HIGH | `docs/` | 2-4h |
| H-4 | **No `SwarmlineError` base class** — users can't `except SwarmlineError:` | Code Reviewer | MEDIUM-HIGH | `agent/`, `runtime/` | 2h |
| H-5 | **Migration guide v1.4 → v1.5 missing** | Reality Checker | HIGH | `docs/migration/` | 1h |
| H-6 | **`ThinRuntime.run()` is a 300-line god method** with 17 distinct concerns | Architect | MEDIUM-HIGH | `runtime/thin/runtime.py` | (defer to v1.6) |
| H-7 | **`session/manager.py:_run_awaitable_sync` spawns thread to call `asyncio.run()` from inside running loop** — dangerous sync-bridge anti-pattern | Architect | MEDIUM-HIGH | `session/manager.py` | (defer to v1.6) |
| H-8 | **`CircuitBreaker` not thread-safe**; `CircuitBreakerRegistry.get` has check-then-set race | Architect | MEDIUM | `resilience/circuit_breaker.py` | (defer to v1.6) |

### MEDIUM-severity (defer to v1.5.x or v1.6.0 unless trivial)

- **Coverage 86% (not 89% as claimed).** Dark zones: `todo/db_provider.py` (0%), `todo/schema.py` (0%), `tools/extractors.py` (33%), `session/backends_postgres.py` (50%) — Reality Checker.
- **`serve.create_app(allow_unauthenticated_query=True)` does NOT enforce loopback host** — inconsistent with A2A/HealthServer (M-1, Security).
- **Provider exception messages leak credentials/PII** verbatim into `RuntimeErrorData.message` — key-only redaction misses values (M-2, Security).
- **`JsonlTelemetrySink` redaction is key-name-only** — missing common keys (`bearer`, `cookie`, `private_key`, `dsn`); no value-level regex for `sk-*`, `Bearer ...`, URL userinfo (M-3, Security).
- **`SystemReminderFilter._format_block`** doesn't sanitize `</system-reminder>` — external docs/RULES.md from untrusted repos can inject closing tags (M-4, Security).
- **`Postgres/SqliteMemoryProvider` are 17-method god-classes** implementing 6 protocols each (SRP at impl-level, not Protocol-level — Architect).
- **`@runtime_checkable`** applied inconsistently (25/39 in `protocols/` package — Architect).
- **`AgentConfig` has 35 fields** — should split into composed configs (Code Reviewer).
- **`Conversation.say` vs `Agent.query`** — verb inconsistency for same operation.
- **`AgentConfig.thinking: dict[str, Any]`** — should be typed `ThinkingConfig` (already exported!).
- **Deprecated `max_thinking_tokens`** still in AgentConfig — remove for major-feeling v1.5.0.
- **`docs/structured-output.md` exists but `query_structured` has docstring lies** — Reality Checker.
- **CLAUDE.md/AGENTS.md still say "Python 3.10+"** — pyproject is `>=3.11`.

### LOW-severity / known issues

- 11 distinct custom exception classes with no shared base (`BudgetExceededError` is even **duplicated** in middleware vs pipeline).
- Branch-name prefix injection theoretical (Security Low).
- Plugin worker_shim missing method allowlist (Security Low).
- EventBus silent error swallowing (Security Low).
- Unredacted `tool_call` previews in observability (Security Low).
- `swarmline run` hardcoded `trusted=True` (Security Low).
- One Protocol with 7 methods (`CodingTaskBoardPort`) violates ISP — acknowledged in its docstring (Architect).
- Tool naming sprawl: `tool` vs `ToolDefinition` vs `ToolFunction` vs `ToolSpec` (4 distinct concepts unclear).

---

## What's genuinely strong (cross-validated)

- ✅ **Domain layer is truly pure stdlib** — verified `protocols/`, `types.py`, `memory/types.py` import nothing from Infrastructure (Architect).
- ✅ **DIP boundary at `agent ↔ runtime` via `RuntimeFactoryPort` is real and correct** (Architect).
- ✅ **Lazy optional dependencies via `__getattr__` and `_OPTIONAL_EXPORTS`** is exemplary (Architect).
- ✅ **`ty check` passes** with zero diagnostics (Reality Checker verified live).
- ✅ **5352 tests pass when isolated**, real and behavioral (Reality Checker spot-checked).
- ✅ **Zero `eval/exec/shell=True/os.system`** — clean security baseline (Architect, Security).
- ✅ **No `pickle`, no archive extraction, no unsafe deserialization** (Security).
- ✅ **TODO/FIXME debt = 0** — verified (Architect).
- ✅ **No top-level circular imports** (Architect).
- ✅ **`@tool` decorator is FastAPI-grade** — auto-extracts description from docstring, parses Google-style `Args:`, infers Pydantic + Enum + `list[T]` + `Optional[T]` (Code Reviewer).
- ✅ **SSRF defense is best-in-class** — cloud-metadata blocking + private/loopback/link-local/reserved IP rejection + DNS-rebinding defense + IP pinning with Host/SNI preservation (Security).
- ✅ **SQL injection comprehensively closed** — all `.execute()` paths use parameterized binding (Security).
- ✅ **Default-deny tool policy** with case-parity (`Bash`/`bash` both denied), tested in `tests/security/` (Security).
- ✅ **Constant-time `hmac.compare_digest`** on all three bearer-auth surfaces (Security).
- ✅ **Sandbox path traversal** correctly uses `Path.resolve().is_relative_to()` (Security).
- ✅ **All YAML uses `safe_load`** (Security).
- ✅ **Frozen dataclass discipline** — `Result`, `AgentConfig`, `ToolDefinition`, `Message` all immutable (Code Reviewer).
- ✅ **Async-first end-to-end** — no sync/async fork (Code Reviewer).
- ✅ **`async with agent` and `async with conv`** — cleanup-by-construction. Better than FastAPI lifespan in some ways (Code Reviewer).
- ✅ **Runtime swappability is real** — same `Agent.query()` works for `thin`, `claude_sdk`, `deepagents`, `cli` — genuine FastAPI-class abstraction (Code Reviewer).
- ✅ **`swarmline init` CLI** is on par with `fastapi-cli` / `cookiecutter` (Code Reviewer).

**Architect's verdict**: "Architecture is meaningfully better than LangChain in three concrete ways: Domain purity, Protocol-first ports, DIP at runtime boundary."

**Security verdict**: "No critical or high-severity bypasses. Codebase is production-grade and security-conscious. Every dangerous pattern you'd expect to find is explicitly absent or correctly handled."

---

## Pre-v1.5.0 Action Plan (priority-ordered)

**Goal: flip the verdict to READY in ~11–18 hours of focused work.**

### Tier 1 — release blockers (~6 hours)

| # | Action | Effort | Owner | Done? |
|---|--------|--------|-------|-------|
| T1.1 | `ruff check --fix && ruff format src/ tests/` (covers C-6) | 5min | core | ⬜ |
| T1.2 | Fix `AgentConfig.runtime` default `"claude_sdk"` → `"thin"` (C-8) | 1h | core | ⬜ |
| T1.3 | Fix Russian error string in `runtime/thin/errors.py:45` (C-9) | 5min | core | ⬜ |
| T1.4 | Fix `docs/agent-facade.md:36` lie about optional `system_prompt` (C-10) | 5min | core | ⬜ |
| T1.5 | Fix test isolation: stop `force=True` in `observability/logger.py:22-27` (C-1, C-3) | 2h | core | ⬜ |
| T1.6 | `JsonlTelemetrySink.record` → `asyncio.to_thread()` for file I/O (C-2) | 1h | core | ⬜ |
| T1.7 | Drop Python `'3.10'` from `publish.yml` matrix (C-7) | 2min | core | ⬜ |
| T1.8 | Update `CLAUDE.md` / `AGENTS.md` to say Python 3.11+ (consistency) | 5min | core | ⬜ |
| T1.9 | `git checkout -b release/v1.5.0`, bump `pyproject.toml` to `1.5.0` (C-5) | 2min | core | ⬜ |

### Tier 2 — release packaging (~3 hours)

| # | Action | Effort | Owner | Done? |
|---|--------|--------|-------|-------|
| T2.1 | Write `CHANGELOG.md [1.5.0]` entry covering 7 phases + Sprint 1A/1B + new public surface (C-4) | 30min–1h | core | ⬜ |
| T2.2 | Add `docs/migration/v1.4-to-v1.5.md` with breaking/non-breaking changes (H-5) | 1h | core | ⬜ |
| T2.3 | Add minimum-viable docs for new v1.5.0 features (Phase 11-17, agent packs, multimodal, sessions, JSONL sink, pi-sdk) (H-3) | 2-4h | core | ⬜ |

### Tier 3 — DX paper-cuts (~7 hours, strongly recommended)

| # | Action | Effort | Owner | Done? |
|---|--------|--------|-------|-------|
| T3.1 | Add `examples/00_hello_world.py` — 10-line truly-minimal example | 30min | core | ⬜ |
| T3.2 | Trim `swarmline/__init__.py __all__` from 51 to ~12 names (H-1) | 2h | core | ⬜ |
| T3.3 | Add `SwarmlineError` base exception class; subclass all custom errors (H-4) | 2h | core | ⬜ |
| T3.4 | Move 80-line `_MockBasicsRuntime` from `examples/01_agent_basics.py` to `swarmline.testing.MockRuntime` (H-2) | 2-4h | core | ⬜ |
| T3.5 | Promote `AgentConfig.thinking: dict` → `ThinkingConfig` (typed) | 1h | core | ⬜ |
| T3.6 | Remove deprecated `max_thinking_tokens` from `AgentConfig` | 30min | core | ⬜ |

### Tier 4 — security hardening (parallel, ~5h, can ship in v1.5.1)

| # | Action | Effort | Owner | Pre-v1.5.0? |
|---|--------|--------|-------|-------------|
| T4.1 | M-1: enforce loopback host when `serve.create_app(allow_unauthenticated_query=True)` | 1h | core | YES (small) |
| T4.2 | M-3: extend `JsonlTelemetrySink` redaction with value-level regex for `sk-*`, `Bearer ...`, URL userinfo | 2h | core | YES (small) |
| T4.3 | M-2: redact provider exception messages before they hit `RuntimeErrorData.message` | 2h | core | v1.5.1 |
| T4.4 | M-4: sanitize `</system-reminder>` markup in external docs filters | 1h | core | v1.5.1 |
| T4.5 | Add `pip-audit` to CI | 30min | core | YES |

### Tier 5 — defer to v1.6.0 / v2.0 (no blockers)

- Refactor `ThinRuntime.run()` 300-line god method (H-6).
- Replace `session/manager.py:_run_awaitable_sync` thread+`asyncio.run()` anti-pattern (H-7).
- Make `CircuitBreaker` thread-safe (H-8).
- Split `AgentConfig` into composed configs (`AgentConfig` + `RuntimeOptions` + `StructuredConfig` + `SandboxConfig`) — breaking, v2.0.
- Unify `Agent.query` + `Agent.query_structured(prompt, response_model=Type)` — next minor.
- Add `@agent.hook("pre_tool")` decorator API — next minor.
- Rename `Conversation.say` → `Conversation.query` — breaking, v2.0 (or alias).
- `swarmline.testing.MockRuntime` + `TestAgent` formalization — v1.6.0.
- Self-describing tool manifest endpoint (analog to `/openapi.json`) in `swarmline.serve` — v1.6.0+.
- `Depends()`-style DI for memory store / sandbox / web provider — v2.0.

---

## Quantitative summary

| Metric | Claimed | Verified | Delta |
|--------|---------|----------|-------|
| Tests passing | 5352 | 5352 (isolated); 4500/4641 (combined run) | ⚠️ test isolation broken |
| Coverage | 89% | 86% | ❌ overstated by 3pp |
| ty diagnostics | 0 | 0 | ✅ |
| ruff (`check`) | green | 1 error in `tests/unit/test_pi_sdk_runtime.py:5` | ❌ |
| ruff (`format --check`) | (unspecified) | 457 files unformatted | ❌ |
| Source files | 336 | 336+ | ✅ |
| Protocol count | 14 | 31 in `protocols/`, 101 across src tree | ⚠️ understated 7× |
| Public exports `__all__` | (unspecified) | 51 | ⚠️ noisy |
| `AgentConfig` fields | (unspecified) | 35 | ⚠️ god-class |
| Custom exception classes | (unspecified) | 11 (no shared base) | ⚠️ |
| TODO/FIXME debt | (unspecified) | 0 in `src/` | ✅ exemplary |
| `eval` / `exec` / `shell=True` | (unspecified) | 0 | ✅ clean |
| Examples | 32 | 32 | ✅ |
| Docs files | (unspecified) | 47 | ✅ |
| `examples/01_agent_basics.py` LOC | (unspecified) | 176 (80 mock boilerplate) | ❌ first-impression cost |
| Default runtime in code | (unspecified) | `"claude_sdk"` | ❌ disagrees with docs |
| Default runtime in docs | (unspecified) | `"thin"` | ❌ disagrees with code |

---

## Sign-off

### Per-auditor verdicts

- **Backend Architect**: CONDITIONAL — fix C-1, C-2, C-3 (~3 days) → release with confidence. Architecture itself is meaningfully better than LangChain.
- **Code Reviewer (DX)**: GOOD WITH CAVEATS — with items 1-8 from the DX recommendations (~11 hours), reaches "FastAPI-class DX for the agent space".
- **Security Engineer**: NEEDS WORK — no CVE-class vulnerabilities. Ship v1.5.0; address M-1 + M-3 in release window (~5h); defer M-2/M-4 to v1.5.1.
- **Reality Checker**: NEEDS WORK — the product is good, the packaging is not. ~3-5 hours away from YES.

### Master verdict

> **🟡 CONDITIONAL — DO NOT TAG `v1.5.0` TODAY.**
>
> **Action**: complete Tier 1 (6h) + Tier 2 (3h) + Tier 1 of Tier 4 (T4.1, T4.2, T4.5 = 3.5h) = **~12 hours of work** to flip to **🟢 READY**.
>
> Tier 3 (DX paper-cuts, ~7h) is **strongly recommended** but technically not blocking — these can ship in v1.5.1 if pressed for time. However, releasing v1.5.0 with the default-runtime mismatch (C-8) and Russian error string (C-9) is **not acceptable** for a "production-ready" announcement.
>
> Tier 5 items are real but appropriate for v1.6.0+ — they are not regressions, just unfinished evolution.

### Comparison to ecosystem

| Framework | Production-readiness score (2026-04-25 swarmline assessment) |
|-----------|--------------------------------------------------------------|
| **swarmline v1.5.0 (post-Tier 1+2)** | 8/10 — strong contender |
| LangChain | 7/10 (more mature ecosystem, more legacy debt) |
| FastAPI (DX baseline) | 10/10 (different domain, but the mental model swarmline aspires to) |
| LlamaIndex | 7/10 |
| AutoGen | 6/10 |
| Anthropic Agent SDK (alone) | 6/10 (less generic) |

swarmline's **architectural moat** (Domain purity + Protocol-first DIP + runtime swappability) is real and durable. Once the packaging gap closes, this is a **best-in-class agent framework** for production AI systems, especially in regulated/multi-provider/Clean-Architecture-disciplined contexts.

---

## Auditor reports (links)

- `.memory-bank/reports/2026-04-25_audit-architecture.md` — Backend Architect (full)
- `.memory-bank/reports/2026-04-25_audit-dx-fastapi-comparison.md` — Code Reviewer (full)
- `.memory-bank/reports/2026-04-25_audit-security.md` — Security Engineer (full)
- `.memory-bank/reports/2026-04-25_audit-reality-check.md` — Reality Checker (full)
- `.memory-bank/reports/2026-04-25_audit-master-production-readiness.md` — **this file** (synthesis)

---

## Recommended next session

```
1. /mb plan fix v1.5.0-release-blockers      # plan the Tier 1+2 work as TDD stages
2. Execute Tier 1 (6h) → tests green, lint green
3. Execute Tier 2 (3h) → CHANGELOG, migration guide, feature docs
4. (Optional) Execute Tier 3 (7h) → DX polish for the public-facing v1.5.0 launch
5. /mb verify → confirm everything ships
6. /mb done → close session
7. release/v1.5.0 branch → tag v1.5.0 → sync-public.sh → PyPI auto-publish via OIDC
```
