# Status

## Текущий фокус

**v1.5.0 RELEASED publicly** (2026-05-02). Public `Publish to PyPI` workflow succeeded for tag `v1.5.0`; PyPI shows `swarmline 1.5.0` as latest. Follow-up public CI hardening is in progress on `main` after the release artifact was published.

**Pending (next step):** push post-release CI hardening to private/public `main` and confirm GitHub Actions `CI` green. Do **not** move/re-push tag `v1.5.0` after PyPI publish, because PyPI artifacts are immutable.

**Release/CI gate status (verified 2026-05-02):**
- `ty check src/swarmline/` → All checks passed! (0 diagnostics, baseline locked = 0)
- CI-like `.[dev,all]` venv: `ty check src/swarmline/` → All checks passed!
- CI-like `pip freeze --exclude-editable` + `pip-audit --strict --desc --requirement ...` → No known vulnerabilities found
- `pytest --tb=no -q` → **5600 passed, 7 skipped, 5 deselected, 0 failed** (~52s)
- `pytest tests/architecture/ -v -m slow` → **3 passed**
- `ruff check src/ tests/` → All checks passed!
- `ruff format --check src/ tests/` → 771 files already formatted

**Предыдущие фазы**:
- ThinRuntime Claude Code Parity v2 (2026-04-13) — Parity COMPLETE 17/17 фаз. Phase 17 commit `2e2c800`.
- Production v2.0 Sprint 1 (2026-04-25) — ty diagnostics 75 → 0, baseline locked = 0. ADR-003 fulfilled (ty strict-mode = sole release gate, no mypy).
- v1.4.0 Stabilization (2026-04-11) — secure-by-default, validation gate green
- v1.4.1 Rename (2026-04-11) — cognitia → swarmline, PyPI published, deprecated wrapper
- Repo housekeeping (2026-04-12) — remotes, docs, memory bank aligned

## Версии

- swarmline: **1.5.0** (released on PyPI 2026-05-02; public publish workflow succeeded)
- swarmline: 1.4.1 (currently published on PyPI; will be superseded by 1.5.0)
- cognitia: 1.5.0 (deprecated wrapper → swarmline; legacy)
- deepagents: 0.4.11 (0.5.0 ещё не на PyPI)

## Roadmap

**Завершено (v1.4.0 stabilization tranche)**:
- ✅ Secure-by-default release posture documented (`enable_host_exec=False`, `allow_host_execution=False`, `allow_unauthenticated_query=False`)
- ✅ Migration guide / changelog / README / capabilities / getting-started / configuration synchronized
- ✅ Structured `security_decision` logging for host-exec deny, HTTP query deny, network-target deny
- ✅ Validation matrix completed: offline + integration + Postgres + live
- ✅ Memory Bank aligned with current repository truth

**Завершено (v0.1.0 → v0.5.0)**:
1. ✅ Phase 0C: Shared ProviderResolver
2. ✅ Phase 0B: ThinRuntime multi-provider (3 адаптера + stream + caching)
3. ✅ Phase 1: Upstream params (memory/subagents/skills/middleware)
4. ✅ Phase 2: Compaction (noop native, token-aware portable, arg truncation)
5. ✅ Phase 0A: Portable memory + token-aware compaction
6. ✅ Phase 3: Cross-session memory + auto-backend
7. ✅ Phase 4: Capabilities (HITL native-only)
8. ⏸️ Phase 5: deepagents 0.5.0 (ожидаем PyPI release)

**Завершено (v0.5.0 → v1.0.0-core)** — Master Plan v3.2:

- ✅ Phase 6: DX Foundation (structured output, @tool, registry, cancel, context manager, typed events, protocols split)
- ✅ Phase 7: Production Safety (cost budget, guardrails, input filters, retry/fallback)
- ✅ Phase 8: Persistence & UI (session backends, event bus, tracing, UI projection, RAG)

*Enterprise extras:*
- ✅ Phase 9 MVP: Agent-as-tool + simple task queue + simple agent registry
- ✅ Graph Agents: AgentExecutionContext, governance, skills/MCP inheritance, dual-dispatch runner
- ✅ Knowledge Bank: 5 ISP protocols, multi-backend (FS/SQLite/Postgres), tools, consolidation
- ✅ Task Enhancements: BLOCKED status, progress auto-calc, extensible workflow stages
- ⬜ Phase 9 Full: Enterprise scheduler, advanced task policies

*Platform:*
- ✅ Phase 10A: CLI Agent Runtime (CliAgentRuntime, NdjsonParser, registry integration)
- ⬜ Phase 10 rest: MCP, credential proxy, OAuth, RTK, `swarmline init`, LiteLLM

*Ecosystem:*
- ⬜ Phase 11: OpenAI Agents SDK (4-й runtime + bridges, gated on SDK ≥ v1.0)

**Завершено (v1.1.0 → v1.2.0):**
- ✅ Phase 12.3: API Docs + community infra
- ✅ Phase 13.1-13.2: Evaluation Framework (eval + compare/history)
- ✅ Phase 14.1-14.3: Memory (Episodic + Procedural + Consolidation Pipeline)
- ✅ Phase 15.1-15.4: HTTP API, HITL, Plugin Registry, Benchmarks
- ✅ Graph Agents Phases 1-6: full hierarchical multi-agent system
- ✅ Graph Agent Config A1-A5: ExecutionContext, skills/MCP, governance
- ✅ Knowledge Bank B1-B4: protocols, multi-backend, tools, consolidation
- ✅ Pipeline Engine + Daemon
- ✅ Paperclip-inspired Components (6 modules)
- ✅ 30+ security fixes, 19 mypy fixes, Clean Architecture extraction

**Детали**: `plans/2026-03-18_masterplan_v3.md` (v3.2)

## Phase 0: Swarmline Lifecycle + HostAdapter + Multi-Runtime (2026-04-10)
- LifecycleMode: EPHEMERAL, SUPERVISED, PERSISTENT
- AgentCapabilities: max_depth, can_delegate_authority
- HostAdapter Protocol: 4 methods (ISP)
- AgentSDKAdapter (Claude Agent SDK)
- CodexAdapter (OpenAI SDK)
- PersistentGraphOrchestrator + GoalQueue
- ModelRegistry: codex-mini entry
- Governance: authority delegation + capability validation

## Тесты

- Offline suite: **5616 passed, 7 skipped, 5 deselected, 0 failed** ← текущий (2026-04-30, audit remediation for plugin env/runtime redaction/MCP safety/tool transcript)
- Offline suite: **5452 passed, 7 skipped, 5 deselected, 0 failed** (2026-04-27, post-v1.5.0 release tag, full suite ~52s via `rtk proxy pytest --tb=no -q`)
- Offline suite: `5352 passed, 7 skipped, 5 deselected` (2026-04-25, Sprint 1B Stage 6 done, ty=0)
- Offline suite: `5096 passed, 5 skipped, 5 deselected` (2026-04-13, Phase 17 done)
- Offline suite: `5042 passed, 5 skipped, 5 deselected` (после Phase 16)
- Offline suite: `4959 passed, 3 skipped, 5 deselected` (после Phase 15)
- Offline suite: `4899 passed, 3 skipped, 5 deselected` (после Phase 14)
- Offline suite: `4859 passed, 3 skipped, 5 deselected` (после Phase 13)
- Offline suite: `4824 passed, 3 skipped, 5 deselected` (после Phase 12)
- Offline suite: `4778 passed, 3 skipped, 5 deselected` (после Phase 11)
- Offline suite: `4249 passed, 3 skipped, 5 deselected` (после audit-remediation)
- Offline suite: `4223 passed, 3 skipped, 5 deselected` (после stabilization)
- Explicit integration: `31 passed, 5 skipped`
- Live suite: `5 passed`
- Postgres integration harness: `3 passed`
- Source files: **385 .py files** under `src/swarmline/` (817 total files) ← текущий (2026-04-27, post-v1.5.0)
- Source files: ~336 .py files (2026-04-13, Phase 16 done)
- Coverage: 89%+ overall
- Graph Agents (A1-A5): ~102 new tests
- Knowledge Bank (B1-B4): ~140 new tests
- Task Progress + BLOCKED + Stages: ~50 new tests
- Previous phases: ~480 tests (6-8, 9MVP, 10A)

## Verification Notes

- Full offline `pytest -q` green after audit-remediation tranche (`4249 passed, 3 skipped, 5 deselected`)
- Repo-wide `ruff check src/ tests/` green after audit-remediation tranche
- Repo-wide `mypy src/swarmline/` green after audit-remediation tranche (`351 source files`)
- Full offline `pytest -q` green after stabilization + release hardening (`4223 passed, 3 skipped, 5 deselected`)
- Explicit integration gate green (`31 passed, 5 skipped`)
- Disposable Postgres integration harness green (`3 passed`)
- Live gate green after installing optional `ddgs` test dependency (`5 passed`)
- Full offline `pytest -q` green after OpenRouter live examples/runtime follow-up (`2524 passed, 11 skipped, 5 deselected`)
- Full offline `pytest -q` green after unified release-risk remediation + follow-up hardening (`2397 passed, 16 skipped, 5 deselected`)
- Representative targeted regressions green: Batch 1/2 (`205 passed`), merge-point portable/session pack (`110 passed`), orchestration/workflow/storage pack (`66 passed`)
- Full offline `pytest -q` green after full re-audit remediation (`2366 passed, 16 skipped, 5 deselected`)
- Targeted Wave 1 regression `pytest` green (`256 passed`)
- Targeted Wave 2 portable-helper regression `pytest` green (`76 passed, 1 skipped`)
- Targeted import-isolation/runtime-registry regressions green (`54 passed`, затем `32 passed` compatibility subset и `30 passed` memory/skills subset)
- Targeted `ruff check` on changed files green
- Targeted `mypy --follow-imports=silent` on changed source modules green
- Repo-wide `ruff check src/ tests/` green
- Repo-wide `mypy src/swarmline/` green
- Smoke verification green: `python examples/20_workflow_graph.py`, real `CliAgentRuntime` success path via temporary `claude` wrapper, and generic NDJSON fail-fast path (`bad_model_output`)

## Ключевые решения

- Portable path ОСТАЁТСЯ (fallback без backend, multi-provider)
- ThinRuntime → multi-provider (Anthropic + OpenAI-compat + Google)
- `swarmline[thin]` = canonical multi-provider install
- SqliteSessionBackend uses asyncio.to_thread() for non-blocking IO
- EventBus wired into ThinRuntime via llm_call wrapper + tool_call event forwarding
- TracingSubscriber uses correlation_id for concurrent tool call span tracking
- GuardrailContext gets session_id from config.extra
- LLM-facing instructions in English (structured output, prompts)
- ConsoleTracer lazy-imports structlog to keep Protocol layer dependency-free
- ThinRuntime buffers assistant text whenever guardrails, output validation, or retry can still reject/replace the response

## Active plans

<!-- mb-active-plans -->
_No active product plans — v1.5.0 released publicly 2026-05-02. Current operational deliverable: make public GitHub Actions `CI` green after post-release hardening._
<!-- /mb-active-plans -->

## Recently done plans

- [2026-04-25] [plans/2026-04-25_fix_v150-release-blockers.md](plans/2026-04-25_fix_v150-release-blockers.md) — fix — v1.5.0 release-blockers — **SHIPPED 2026-04-25** (21/21 stages ✅, tag `v1.5.0` on commit `3fae1b2`)
- [2026-04-25] [plans/2026-04-25_feature_production-v2-phase-01a-ty-strict-foundation.md](plans/2026-04-25_feature_production-v2-phase-01a-ty-strict-foundation.md) — Sprint 1A: ty 75 → 62, foundation + decisions + ADR-003
- [2026-04-25] [plans/2026-04-25_feature_production-v2-phase-01b-ty-bulk-cleanup.md](plans/2026-04-25_feature_production-v2-phase-01b-ty-bulk-cleanup.md) — Sprint 1B: ty 62 → 0, baseline locked = 0

## Last release

| Field | Value |
|-------|-------|
| Tag | `v1.5.0` |
| Commit | `a2ad514` (`fix: keep top-level import working without httpx`) |
| Date (local) | 2026-05-02 |
| Pushed to | private `origin` + public `fockus/swarmline` |
| Public sync | ✅ completed via `./scripts/sync-public.sh`; public tag published |
| PyPI | ✅ `swarmline 1.5.0` published via OIDC; latest on PyPI |
| `pyproject.toml` version | 1.5.0 |
| `src/swarmline/serve/app.py` `_VERSION` | 1.5.0 |

## Release gate (v1.5.0) — verified at tag time

| Gate | Status | Evidence |
|------|--------|----------|
| `ty check src/swarmline/` | ✅ GREEN | 0 diagnostics (was 75 pre-Sprint 1, baseline locked at 0) |
| `tests/architecture/ty_baseline.txt` | ✅ LOCKED | 0 |
| Full offline pytest | ✅ GREEN | 5452 passed, 7 skipped, 5 deselected, 0 failed (verified 2026-04-27) |
| `ruff check src/ tests/` | ✅ GREEN | All checks passed! (auto-fixed F401 in `test_pi_sdk_runtime.py` during Stage 1) |
| `ruff format --check` | ✅ GREEN | applied via Stage 1 (commit `0badf89` + format pass `1511f65`) |
| ADR-003 outcome | ✅ FULFILLED | ty strict-mode = sole type-check release gate, no mypy |
| CHANGELOG `[1.5.0]` entry | ✅ DONE | commit `d541edb` (Tier 2) |
| Migration guide v1.4 → v1.5 | ✅ DONE | commit `d541edb` (Tier 2) |
| Tier 4 security gates (M-1, M-3, pip-audit) | ✅ DONE | commit `913cb5c` |

## Recently done

<!-- mb-recent-done -->
- 2026-04-27 — [plans/done/2026-04-27_fix_post-review-polish.md](plans/done/2026-04-27_fix_post-review-polish.md) — fix — post-review-polish (Stage 8)
<!-- /mb-recent-done -->
