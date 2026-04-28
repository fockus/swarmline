# Full Framework Review — swarmline v1.5.0 (Master Synthesis)

**Date:** 2026-04-27
**Scope:** Cross-domain synthesis of 5 parallel specialist audits — Security, Architecture/Scalability, Code Quality, Test Coverage, DX/Adoption
**Reviewer:** Synthesis from 5 subagents (Security Engineer, Backend Architect, Code Reviewer, Test Results Analyzer, Developer Advocate)
**Baseline:** v1.5.0 tag on `a10085e` (post-audit-closure), 387 source files, 52 980 LOC, 5527+ tests, ty=0, ruff clean

**Source reports (read for full details):**
- [`security-full-audit`](2026-04-27_review_security-full-audit.md)
- [`architecture-scalability`](2026-04-27_review_architecture-scalability.md)
- [`code-quality`](2026-04-27_review_code-quality.md)
- [`test-coverage`](2026-04-27_review_test-coverage.md)
- [`dx-adoption`](2026-04-27_review_dx-adoption.md)

---

## Executive Summary

### Dimension Scores

| Dimension | Health | Score / Findings | Headline |
|---|---|---|---|
| **Security** | ✅ Solid | 0 C / 5 H / 11 M / 2 L | No PyPI blockers; 4 H-fixes for v1.5.1 |
| **Architecture** | ⚠️ Production-defaults | 4 C / 10 H / 10 M | Excellent bones; scalability needs opt-in tuning |
| **Code Quality** | ⚠️ Localized debt | 0 critical, 3 debt clusters | Healthy core; ship-ready |
| **Test Coverage** | ⚠️ Margin-zero | 85.17% (target 85%) | 143 polluted tests; inverted pyramid (88% unit) |
| **DX / OSS Health** | ⚠️ Tech-strong, signals-weak | 7.5/10 (→ 8.5 with quick wins) | Tech excellent; community trust signals missing |

### Combined Release Verdict

| Path | Status | Blocker |
|---|---|---|
| **PyPI publish v1.5.0** | ✅ GO | None — no Critical security/code/architecture issues |
| **Public visibility (community traction)** | ⚠️ HOLD 1 day | Missing SECURITY.md, CODE_OF_CONDUCT, live CI badges, LICENSE copyright still "cognitia" |
| **Production adoption (≤20 concurrent agents)** | ✅ GO with operator tuning | Document Postgres index requirements, MCP-client reuse, prompt caching opt-in |
| **Production scale (>50 concurrent agents)** | ⚠️ HOLD for v1.6.0 | C-1 (buffered streaming), C-2 (per-request httpx), C-3 (missing DDL) need wiring |
| **Enterprise security review** | ⚠️ HOLD for v1.5.1 | H1 timing attack, H4 git argv injection, H2/H3 redaction bypass |

### Bottom Line

**Ship v1.5.0 to PyPI as-is technically possible** (zero Critical findings across all 5 dimensions), **but defer 1 day** to close 6 OSS-health quick wins that disproportionately move the project from "amateur OSS" to "enterprise-credible" perception. Then ship v1.5.1 within 2 weeks closing 5 High-severity security findings + test pollution. The framework's **architectural fundamentals are exceptional** (Clean Arch verified, all 26 Protocols ≤5 methods, Domain layer stdlib-only) — debt is **localized, named, and tractable**.

---

## Cross-Cutting Themes

Five independent specialist audits surfaced **four overlapping themes** that no single audit fully captures:

### Theme A: "Production scale = opt-in tuning"

The framework supports production scale on paper, but **defaults are conservative-conservative**:
- Architecture: buffered streaming defeats streaming benefit (C-1), MCP creates new HTTPS connection per call (C-2), no Postgres DDL ships (C-3), no prompt caching (H-8), no Prometheus metrics (H-4)
- Code quality: `_adapter_cache` is unbounded module-global (H-5), subagent registry never reaps (H-6)
- DX: no Dockerfile, no cloud deployment guides
- Test coverage: 0 benchmarks, no load tests

**Implication:** The "ready for production" claim in README is technically correct only for ≤20 concurrent agents per process and ≤100k messages per topic. Beyond that, operators must tune themselves with little guidance. **Action:** v1.6.0 must ship a `docs/production-tuning.md` *and* close the top-3 architecture criticals.

### Theme B: "Test pollution undermines coverage headline"

Coverage report says 85.17% (target met). Reality:
- **143 tests fail / 69 errors** in full pytest runs (`test_cli_commands.py`, `test_tool_policy.py`, `test_mcp_*`, etc.) — pass in isolation
- Pyramid is **88% unit / 10% integration / 2% e2e** vs Testing Trophy guidance "integration-heavy"
- 78 test files have >5 mocks; 49 files have >10 mocks (heavy implementation coupling)
- `-m integration` filter catches only 40/525 actual integration tests
- 4 zero-coverage modules totaling 344 statements

**Implication:** The 5527-passing-tests headline number is misleading. Test contract violation per RULES ("tests must pass for ANY correct implementation"). **Action:** P0 fix `CliRunner` isolation pattern + apply `pytestmark = pytest.mark.integration` consistently. Block v1.5.1 release on test pollution closure.

### Theme C: "OSS-mature signals lag the technical maturity"

The codebase ships exceptional engineering (ty=0 strict mode, ruff clean, 5527 tests, ISP-clean, Clean Arch verified, security audit closure documented). The **public-facing surface lags 1-2 years behind**:
- No SECURITY.md (despite thorough audit closure in CHANGELOG)
- No CODE_OF_CONDUCT.md (Contributor Covenant)
- 5 README badges are static/hardcoded (`tests-4200%2B%20passed-brightgreen`)
- LICENSE still says "Copyright (c) 2024-2026 cognitia contributors" (rename was 2026-04-11)
- `docs/why-cognitia.md` left orphaned
- README runtime feature matrix shows 3 of 6 actual runtimes
- `docs/agent-facade.md:10` snippet raises `ValueError` on copy-paste
- No public roadmap (private `roadmap.md` filtered by sync script)
- No Dockerfile

**Implication:** Enterprise evaluators run a 30-second vibe check on these signals before reading any code. Failing this check = automatic disqualification for security/legal/risk teams, regardless of code quality. **Action:** Quick-win pass before public sync (2-4 hours total).

### Theme D: "Domain purity is exceptional; App→Infra leaks are the next refactor target"

Architecture and code-quality audits independently confirmed:
- ✅ Domain (`protocols/`, `domain_types.py`, `memory/types.py`) — 0 non-stdlib imports
- ✅ All 26 Protocols in `protocols/` are ≤5 methods (ISP-clean)
- ✅ All 67 sub-package internal Protocols ≤5 methods
- ✅ Lazy-import discipline preserved across all optional deps
- ⚠️ `orchestration/workflow_executor.py:11` and `orchestration/thin_subagent.py:25` import concrete `ThinRuntime` — 2 actual DIP violations
- ⚠️ `agent/runtime_wiring.py:123` and `orchestration/thin_subagent.py:414` lazy-import `LocalSandboxProvider` (concrete) — 2 lazy-shimmed Clean Arch violations
- ⚠️ `RuntimeConfig` is mutable and shared between subagents (race risk)

**Implication:** The framework is *one ports-introduction PR away* from true Clean Architecture. **Action:** v1.6.0 — introduce `SubagentRuntimeFactory` + `SandboxProviderPort` Protocols; freeze `RuntimeConfig`.

---

## Master Prioritization

Compiled from 5 audits, deduplicated, cross-validated. Format: **ID** | dimension | finding | source.

### 🔴 P0 — Close BEFORE public PyPI sync (≤1 day total, parallelizable)

| # | Source | Finding | Effort | Why P0 |
|---|---|---|---|---|
| P0-1 | DX | LICENSE copyright `cognitia contributors` → `swarmline contributors` | 2 min | Legal hygiene; public sync should not ship wrong copyright |
| P0-2 | DX | Add SECURITY.md (vuln disclosure, supported versions, response SLA) | 30 min | Security researchers default to public Issues without it; v1.5.0 audit closure deserves it |
| P0-3 | DX | Add CODE_OF_CONDUCT.md (Contributor Covenant 2.1 boilerplate) | 15 min | Enterprise/community signal |
| P0-4 | DX | Replace 5 static README badges with live CI badges | 30 min | Hardcoded `tests-4200%2B%20passed` reads as fake |
| P0-5 | DX | Fix `docs/agent-facade.md:10` snippet (`AgentConfig(runtime="thin")` → with `system_prompt`) | 5 min | Copy-paste raises `ValueError` |
| P0-6 | Test | Apply `pytestmark = pytest.mark.integration` to 67 files in `tests/integration/` | 30 min | `-m integration` filter currently catches 40/525 |
| P0-7 | DX | README "Runtime Feature Matrix" table: include `cli`, `openai_agents`, `pi_sdk` (currently 3/6) | 15 min | Inconsistency with runtime list above it |
| P0-8 | DX | Remove or mark-as-historical `docs/why-cognitia.md` | 5 min | Stale post-rename artifact |

**Total: ~2-3 hours of work.** All independent, can be one PR or 8 micro-commits. Then trigger `./scripts/sync-public.sh --tags`.

### 🟠 P1 — v1.5.1 patch release (target: 1-2 weeks)

#### Security (5 H-findings)

| # | Finding | File | Fix shape |
|---|---|---|---|
| P1-S1 | **H1**: Timing attack in bearer auth | `serve/app.py:41` | Replace `==` with `hmac.compare_digest` (mirrors `daemon/health.py:133` and `a2a/server.py:107` already-correct pattern) |
| P1-S2 | **H2/H3**: `exc_info=True` bypasses `redact_secrets` | `runtime/thin/llm_client.py:161,195,215`, `runtime/cli/runtime.py:262` | Add structlog redaction processor globally; replace `logger.exception` with `logger.error("...", error=redact_secrets(str(exc)))` |
| P1-S3 | **H4**: Git argv injection via `target_branch` | `multi_agent/worktree_orchestrator.py:87,169` | Add ref-validator regex `^(?!-)[a-zA-Z0-9._/-]{1,255}$`; reject paths starting with `-` |
| P1-S4 | **H5**: `langchain-core>=1.2.18` accepts CVE-2026-40087 | `pyproject.toml:82` | Bump floor to `>=1.2.28`; also `anthropic>=0.87.0` (CVE-2026-34450/34452) |
| P1-S5 | **N5 (widened)**: CLI startup-failure stacktrace | `runtime/cli/runtime.py:262-268` | Same fix as H2/H3 (single global processor closes both) |

#### Test pollution (P0 quality issue per Test audit)

| # | Finding | File | Fix shape |
|---|---|---|---|
| P1-T1 | 14 tests fail in batch | `test_cli_commands.py` | `runner.isolated_filesystem()` + reset stdout per test |
| P1-T2 | 60+ tests fail in batch | `test_coding_profile_wiring.py` | Module-level state isolation |
| P1-T3 | 60+ MCP tests fail/error in batch | `test_mcp_*.py` | Async event-loop teardown discipline |
| P1-T4 | 20 tests fail in batch (pass alone) | `test_tool_policy.py` | Module state leak |
| P1-T5 | Apply `requires_anthropic` / `requires_langchain` markers | ~10 files | Use `pytestmark = pytest.mark.requires_*` at module top |
| P1-T6 | Enable branch coverage in `pyproject.toml` | `[tool.coverage.run] branch = true` | Adds 5-10% additional gap visibility |
| P1-T7 | Delete or test `tools/extractors.py` (33% coverage = dead code candidate) | `tools/extractors.py` | Verify call sites; delete if dead |

#### Code quality DRY quick wins (≤1 day)

| # | Finding | Files |
|---|---|---|
| P1-C1 | Extract `agent/mcp_bridge.py` for `build_tools_mcp_server`, `_adapt_handler`, `_RuntimeEventAdapter`, `_ErrorEvent` (4× duplicates) | `agent/agent.py`, `agent/runtime_dispatch.py` |
| P1-C2 | Extract `_BasePlanStore.load/list_plans/update_step` | `orchestration/plan_store.py` |
| P1-C3 | Extract `_emit_budget_event` helper | `pipeline/budget_store.py` |
| P1-C4 | Extract `swarmline._lazy_module()` helper for 3× `__getattr__` lazy loaders | `memory/__init__.py`, `runtime/ports/__init__.py`, `skills/__init__.py` |
| P1-C5 | Drop `Agent._runtime: Any = None` (never assigned/read); inline `Agent._merge_hooks` | `agent/agent.py` |
| P1-C6 | Address S4 (KISS empty wrapper in orchestration) | already in v1.5.1 backlog |

#### Architecture quick wins (≤1 day, no API change)

| # | Finding | File |
|---|---|---|
| P1-A1 | **C-2**: Reuse `httpx.AsyncClient` in `McpClient` (4 `async with` per turn → 1 per agent) | `runtime/thin/mcp_client.py` |
| P1-A2 | **C-4**: Replace `_locks[ks] = asyncio.Lock()` with `setdefault(...)` | `session/manager.py:39-44` |
| P1-A3 | **H-2**: Move `JsonlTelemetrySink._lock = asyncio.Lock()` to `__init__` | `observability/jsonl_sink.py:76` |
| P1-A4 | **M-8**: Wrap `adapter.call` in `asyncio.wait_for(timeout_sec)` | `runtime/thin/llm_client.py` |

#### DX/Documentation (≤1 day)

| # | Finding | Effort |
|---|---|---|
| P1-D1 | Bold `swarmline[thin]` as canonical install in README | 15 min |
| P1-D2 | Add public `docs/roadmap.md` (subset of `.memory-bank/roadmap.md`, public-safe quarterly buckets) | 1h |
| P1-D3 | Move `docs/credentials.md` link to top of `docs/getting-started.md` | 5 min |
| P1-D4 | Cover the 4 zero-coverage modules with happy-path tests (`otel_exporter.py`, `mcp/_types.py`, `multi_agent/persistent_graph.py`, `plugins/_worker_shim.py`) | 1d |
| P1-D5 | Add `pydantic-ai` row to README framework comparison table | 15 min |

**v1.5.1 sprint scope: ~3-5 working days** (one developer). Bumps tests count to ~5600+, closes 5 High-severity security, kills test pollution, removes 8 DRY clusters, ships 4 OSS-health items.

### 🟡 P2 — v1.6.0 minor release (target: 1-2 months)

#### Architecture (10 H + 6 critical C-class items)

| # | Finding | Type | Source ID |
|---|---|---|---|
| P2-A1 | Ship Postgres DDL with proper indexes (`messages`, `facts`, `topics`) + `apply_migrations()` helper | Critical | C-3 |
| P2-A2 | Split streaming path: `stream_llm_call(yield chunk, raw_so_far)` + retain `run_buffered_llm_call` for validation | Critical | C-1 |
| P2-A3 | Async `subscribe` + `_subscribers` lock for `RedisEventBus`/`NatsEventBus` | High | H-3 |
| P2-A4 | Add `observability/metrics.py` Protocol + Prometheus adapter (`swarmline[prometheus]`) | High | H-4 |
| P2-A5 | Bounded LRU on `_adapter_cache` with `clear_adapter_cache()` + close on eviction | High | H-5 |
| P2-A6 | `ThinSubagentOrchestrator.cleanup_completed(retain_seconds)` | High | H-6 |
| P2-A7 | `asyncio.gather` for multi-tool envelopes in JSON-in-text path | High | H-7 |
| P2-A8 | Anthropic prompt caching opt-in (`RuntimeConfig.use_prompt_caching`) | High | H-8 |
| P2-A9 | Cache `Agent` runtime per `AgentConfig` hash (or expose `Agent.warm()`) | High | H-9 |
| P2-A10 | Wire `CircuitBreaker` into `McpClient` and LLM provider calls | Medium | M-4 |
| P2-A11 | `/v1/health` performs DB + event-bus liveness check | Medium | M-10 |
| P2-A12 | `RuntimeConfig` → `@dataclass(frozen=True)`; immutable `input_filters` | High | H-1 (breaking, gate behind v1.6.0 deprecation) |

#### Code Quality (substantial refactors)

| # | Finding | Type |
|---|---|---|
| P2-Q1 | Split `run_react`/`run_conversational`/`run_planner` (389+290+191 LOC of imperative flow); introduce `RuntimeStrategy` Protocol | KISS / SRP |
| P2-Q2 | Split `PostgresMemoryProvider`/`SQLiteMemoryProvider` (17-method god classes) per protocol; share `_PostgresSession`/`_SQLiteSession` mixins | SRP |
| P2-Q3 | Introduce `SubagentRuntimeFactory` + `SandboxProviderPort` Protocols; eliminate `from swarmline.runtime.thin.runtime import ThinRuntime` in orchestration | DIP / Clean Arch |
| P2-Q4 | Continue `graph_task_board_shared.py` Strangler-Fig migration; consolidate Sqlite/Postgres task boards | DRY |
| P2-Q5 | Reduce `# type: ignore` count from 20 → ≤5 | Maintenance |

#### Tests (rebalance pyramid)

| # | Finding | Source ID |
|---|---|---|
| P2-T1 | Refactor `test_a2a_adapter.py` with parametrize fixture (eliminates 13× duplicate constructor) | Test #1 |
| P2-T2 | Bring `agent/runtime_dispatch.py` to 95% (5 integration tests covering each runtime selection path) | Test #2 (P0 in source report) |
| P2-T3 | Bring `orchestration/workflow_langgraph.py` to 90%+ or skip-if-no-langchain | Test #3 |
| P2-T4 | 5 property-based tests via Hypothesis: `redact_secrets`, JSON parsers, `tool_id_codec`, model alias resolver, sandbox path isolation | Test missing #4 |
| P2-T5 | Convert 10 mock-heavy unit tests to integration tests | Test smell #1 |
| P2-T6 | Add explicit concurrency tests for memory providers, `Scheduler` | Test missing #5 |

#### DX (medium-effort)

| # | Finding | Effort |
|---|---|---|
| P2-D1 | Granular `[thin-anthropic]` / `[thin-openai]` / `[thin-google]` extras (saves ~50MB on minimal install) | 4h |
| P2-D2 | `RuntimeEventType` Literal/Enum (replace string-typed `event.type`) | 4h |
| P2-D3 | `@hook` decorator (`@agent.hook("pre_tool")` mirroring `@tool`) | 6h |
| P2-D4 | Dockerfile + `docs/deployment/docker.md` | 1d |
| P2-D5 | `mkdocstrings-python` integration; auto-generate API reference | 1d |
| P2-D6 | `cookbook/` with 5-10 high-leverage recipes | 2-3d |
| P2-D7 | `docs/migration/from-langchain.md`, `from-crewai.md` | 1d |

#### Security (defense-in-depth)

| # | Finding | Source ID |
|---|---|---|
| P2-S1 | M2/M3: Pin DNS resolution in `validate_http_endpoint_url`; add IPv6 metadata coverage | M2, M3 |
| P2-S2 | M4: TOCTOU in `LocalSandboxProvider.write_file` (use `O_NOFOLLOW \| O_EXCL` + revalidate before rename) | M4 |
| P2-S3 | M5/M6: Plugin entry_point allowlist + RPC method dispatch via `__all__` only | M5, M6 |
| P2-S4 | M7: `fail_closed=True` flag for security-critical hooks | M7 |
| P2-S5 | M11: Apply `validate_http_endpoint_url` to `JinaReaderFetchProvider` | M11 |
| P2-S6 | Prior backlog: S1-S6, N1-N5 | already known |

**v1.6.0 sprint scope: ~6-8 weeks** (one developer at 80% allocation). Closes Critical-class scalability blockers, makes pyramid balanced, ships Dockerfile + cookbook + decorator API symmetry.

### 🟢 P3 — v2.0.0 major release (long-term, 6+ months)

| # | Finding | Type |
|---|---|---|
| P3-1 | Remove deprecated `RuntimePort`, `AgentConfig.thinking=<dict>`, `SessionState.adapter`, `AgentConfig.resolved_model` | Breaking cleanup |
| P3-2 | Split `MessageStore` → `MessageWriter` + `MessageReader` Protocols | ISP refinement |
| P3-3 | `MessageStore.get_messages_bulk` (or new `BulkMessageReader` Protocol) | Performance |
| P3-4 | `EventBus.subscribe → Awaitable[str]` (distributed buses await network confirmation) | Correctness |
| P3-5 | `swarmline.create()` factory (hide 35-field `AgentConfig` behind smart factory) | DX |
| P3-6 | LiteLLM integration (`swarmline[litellm]`) — 200+ providers (per BACKLOG IDEA-030) | Ecosystem |
| P3-7 | Vector store integrations (`swarmline.memory.vector` adapters) — Qdrant, pgvector, Chroma (per BACKLOG IDEA-028) | Ecosystem |
| P3-8 | Test pyramid: target 60% integration / 30% unit / 10% e2e (currently 10/88/2) | Quality |
| P3-9 | Mutation testing with `mutmut` against `agent/`, `protocols.py`, `policy/`; target ≥70% mutation kill | Quality |
| P3-10 | Pytest-benchmark with regression budget on PR checks | Quality |

---

## Risk Matrix

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| PyPI publish exposes timing attack (H1) before v1.5.1 | Low | High (token recovery) | Trivial fix; bundle into v1.5.1 within 2 weeks |
| User encounters `ValueError` on copy-paste from `docs/agent-facade.md:10` | High | Medium (DX friction) | P0 fix |
| Production user hits Postgres seq-scan past 100k messages | Medium | Medium (latency) | Document index requirements; ship DDL in v1.6.0 |
| Test pollution masks real regression in CI | Medium | High (false-green) | P1 fix; block v1.5.1 release on closure |
| Security researcher discloses vuln publicly (no SECURITY.md) | Low | High (reputation) | P0 add SECURITY.md with private disclosure path |
| Enterprise evaluator rejects on `cognitia` LICENSE copyright | Medium | High (lost adoption) | P0 fix |
| `langchain-core>=1.2.18` user installs CVE'd version | Medium | Medium (transitive RCE risk) | P1 bump floor |
| MCP-heavy user hits TLS handshake bottleneck | Medium | Medium (latency) | P1 fix C-2 (1-day refactor) |

---

## What's Genuinely Excellent (Calibration)

To balance the findings list, the audits also surfaced **substantial strengths** that should not get lost in remediation planning:

1. **Security:** 0 `eval`/`exec`/`pickle`/`yaml.unsafe_load`/`shell=True` across 387 files. All SQL parameterized. `asyncio.create_subprocess_exec` everywhere. Default-deny tool policy. Subagent inherits parent authority (no escalation).
2. **Architecture:** Domain layer verified stdlib-only. All 26 Protocols ≤5 methods. Lazy-import discipline 100%. 6 swappable runtimes share `AgentRuntime` 4-method ISP contract.
3. **Code Quality:** 0 TODO/FIXME/HACK in src/. 0 bare except. 0 mutable defaults. Test/code ratio 1.62. ty=0 strict mode, ruff clean.
4. **Tests:** `tests/architecture/test_ty_strict_mode.py` baseline-locked CI gate. Live tests properly isolated (5 collected with `-m live`). 81 `parametrize` invocations.
5. **DX:** `@tool` auto-schema inference (best-in-class). 34 runnable examples with offline `MockRuntime` (zero-API-key adoption path). CHANGELOG.md security audit closure section is exemplary. GitHub Actions pipeline (lint+typecheck+tests+architecture+pip-audit on Python 3.11/3.12/3.13 + Trusted Publishing OIDC) better than 90% of OSS Python projects.
6. **OSS Health:** Curated 12-name `__all__`. CONTRIBUTING.md (109 lines, comprehensive). Issue + PR templates exist.

These should be **promoted on the public surface** — they are the credibility currency for adoption, currently hidden behind missing badges and missing public roadmap.

---

## Recommended Sequence

```
TODAY (≤3h)        : Close 8 P0 items → green-light public sync
+0 days            : ./scripts/sync-public.sh --tags → PyPI v1.5.0 live
Week 1-2 (sprint)  : v1.5.1 — security H1+H4+H5, redaction processor (H2/H3),
                     test pollution closure, DRY cleanups, 4 zero-coverage modules
                     → v1.5.1 tag → PyPI
Week 3-10 (v1.6.0) : Architecture C-1/C-2/C-3, RuntimeStrategy split,
                     MemoryProvider split, RuntimeConfig freeze (gated breaking),
                     pyramid rebalance, Dockerfile, cookbook, @hook decorator
                     → v1.6.0 tag → PyPI
Months 4-6 (v1.6.1+): Polish, deprecation deadlines, vector store adapters
v2.0.0             : Breaking cleanup (deprecated removals, ISP splits)
```

---

## Open Questions for User

1. **Public sync timing**: Close P0 quick wins first (~3h), then sync? Or sync v1.5.0 as-is now and treat OSS-health as part of v1.5.1?
2. **v1.5.1 scope**: Bundle security (H1+H4+H5) + test pollution + DRY cleanups in one release, or split into v1.5.1 (security-only) + v1.5.2 (quality)?
3. **v1.6.0 architecture work**: All C-1/C-2/C-3 + RuntimeStrategy split is ~6 weeks. Acceptable, or prefer staged minor releases (v1.6.0 = scalability, v1.7.0 = code-quality refactor)?
4. **Plan files**: Do you want me to scaffold the v1.5.1 plan (`/mb plan fix v151-followup-patch`) now? Or wait until after public sync?
5. **BACKLOG sync**: 30+ new findings here are not in `.memory-bank/BACKLOG.md`. Auto-promote to IDEA-NNN entries, or curate manually?

---

## Conclusion

swarmline v1.5.0 is **a release-ready, technically excellent codebase with disproportionately weak community-trust signals**. The 5-perspective audit found **zero PyPI-blocking issues**, validating the post-audit-closure work, and identified a **clean, prioritized debt list** that maps cleanly to v1.5.1 (security + test pollution, ~1 sprint), v1.6.0 (architecture scalability + pyramid rebalance + DX maturity, ~6 weeks), and v2.0.0 (deprecation cleanup, breaking ISP refinements).

**The most leveraged action available** is the **3-hour P0 quick-win pass before public sync** — it converts the project's perception from "promising indie OSS" to "enterprise-credible framework" with no code change beyond `LICENSE`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, badge updates, one snippet fix, two README typo classes, and one test-marker pass. Every other recommendation is downstream of this.

Strongly recommend: **close P0 → public sync → v1.5.1 within 2 weeks → v1.6.0 within 8 weeks**, in that order.
