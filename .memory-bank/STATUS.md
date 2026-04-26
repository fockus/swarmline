# Status

## Текущий фокус

**Production v2.0 — Sprint 1 (ty-strict gate)** (2026-04-25) — закрытие release gate перед v1.5.0. Sprint 1A (Phase 01a) и Sprint 1B (Phase 01b) **COMPLETE**: ty diagnostics 75 → 0, baseline locked = 0. ADR-003 fulfilled (ty strict-mode = sole release gate, no mypy).

**Release gate status:** **GREEN** — `ty check src/swarmline/` → All checks passed! (0 diagnostics). Готово к v1.5.0 release.

**Предыдущая фаза:** ThinRuntime Claude Code Parity v2 (2026-04-13) — Parity COMPLETE 17/17 фаз. Phase 17 commit 2e2c800.

**Прогресс Production v2.0:** Phase 01a ✅ + Phase 01b ✅ (Sprint 1 ty-strict gate complete). Следующий шаг: v1.5.0 release (release branch + bump pyproject + CHANGELOG + tag + sync to public).

**Предыдущие транши завершены**:
- v1.4.0 Stabilization (2026-04-11) — secure-by-default, validation gate green
- v1.4.1 Rename (2026-04-11) — cognitia → swarmline, PyPI published, deprecated wrapper
- Repo housekeeping (2026-04-12) — remotes, docs, memory bank aligned

## Версии

- swarmline: 1.4.1 (published on PyPI)
- cognitia: 1.5.0 (deprecated wrapper → swarmline)
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

- Offline suite: `5352 passed, 7 skipped, 5 deselected` ← текущий (2026-04-25, Sprint 1B Stage 6 done, ty=0)
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
- Source files: ~336 .py files ← текущий (2026-04-13, Phase 16 done)
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
_No active plans — Sprint 1B (Phase 01b) closed 2026-04-25, baseline=0 locked. Next: v1.5.0 release branch._
- [2026-04-25] [plans/2026-04-25_fix_v150-release-blockers.md](plans/2026-04-25_fix_v150-release-blockers.md) — fix — v1.5.0 release-blockers
<!-- /mb-active-plans -->

## Recently done plans

- [2026-04-25] [plans/2026-04-25_feature_production-v2-phase-01a-ty-strict-foundation.md](plans/2026-04-25_feature_production-v2-phase-01a-ty-strict-foundation.md) — Sprint 1A: ty 75 → 62, foundation + decisions + ADR-003
- [2026-04-25] [plans/2026-04-25_feature_production-v2-phase-01b-ty-bulk-cleanup.md](plans/2026-04-25_feature_production-v2-phase-01b-ty-bulk-cleanup.md) — Sprint 1B: ty 62 → 0, baseline locked = 0

## Release gate (v1.5.0)

| Gate | Status | Evidence |
|------|--------|----------|
| `ty check src/swarmline/` | ✅ GREEN | 0 diagnostics (was 75 pre-Sprint 1) |
| `tests/architecture/ty_baseline.txt` | ✅ LOCKED | 0 |
| Full offline pytest | ✅ GREEN | 5352 passed, 7 skipped, 5 deselected |
| ruff check | ✅ GREEN | only pre-existing F401 in test_pi_sdk_runtime.py (out-of-scope) |
| ADR-003 outcome | ✅ FULFILLED | ty strict-mode = sole type-check release gate, no mypy |
