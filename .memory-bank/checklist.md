# Checklist

## Audit remediation — 2026-04-30

- ✅ 10/10 audit findings implemented: plugin subprocess env hardening, provider/runtime error redaction, public MCP URL validation, `McpBridge` lifecycle, ThinRuntime resumed tool transcript preservation, URL query secret redaction, and web fetch error/log redaction.
- ✅ Verification complete: targeted audit suite **251 passed**; `ruff check src/ tests/` green; `ty check src/swarmline/` green; full `PYTHONPATH=src pytest --tb=short -q` → **5616 passed, 7 skipped, 5 deselected**.

## v1.5.0 public release — 2026-05-02

- ✅ Private `main` pushed and public-safe snapshot synced to `github.com/fockus/swarmline`.
- ✅ Tag `v1.5.0` published publicly and `Publish to PyPI` GitHub Actions run succeeded.
- ✅ PyPI now reports `swarmline 1.5.0` as latest.
- ✅ Release publish blocker fixed: top-level `import swarmline` works without optional `httpx`.
- ✅ Post-release CI hardening verified locally: local + CI-like `ty` green, `pip-audit` pinned-requirements path green, `ruff`/format green, architecture meta-tests green, full offline `pytest` → **5600 passed, 7 skipped, 5 deselected**.
- ⬜ Public GitHub Actions `CI` re-run for post-release hardening must be green after pushing this follow-up commit.

## v1.5.0 — SHIPPED (2026-04-25, tag `v1.5.0` on commit `3fae1b2`)

All 21 stages of [`plans/2026-04-25_fix_v150-release-blockers.md`](plans/2026-04-25_fix_v150-release-blockers.md) executed end-to-end on `main`. Tag pushed to private `origin` only.

- ✅ Functional implementation for phases 11-17 is complete and full offline `pytest -q` is green (post-release: **5452 passed, 7 skipped, 5 deselected, 0 failed** verified 2026-04-27)
- ✅ Release gate green: `ty check src/swarmline/` → All checks passed! (0 diagnostics, baseline locked = 0)
- ✅ Public Python support contract synced to **3.11+**
- ✅ **Public sync to PyPI** — completed 2026-05-02; PyPI latest = `1.5.0`

## ThinRuntime Claude Code Parity v2 — v1.5.0 (Phases 11-17)

### Phase 11: Foundation Filters ✅ DONE (Judge 4.40/5.0, 2026-04-13)
- ✅ 11.1 InputFilter protocol + ProjectInstructionFilter (CLAUDE.md loading) + 19 unit tests
- ✅ 11.2 SystemReminderFilter (dynamic context injection) + 17 unit tests
- ✅ 11.3 ThinRuntime filter wiring + integration tests + 14 tests
- ✅ Quality gates: 4778 tests pass, ruff clean

### Phase 12: Tool Surface Expansion ✅ DONE (Judge 4.43/5.0, 2026-04-13, commit 4d2d018)
- ✅ 12.1 Domain allow/block filter for web_fetch (HttpxWebProvider) — 20 unit tests
- ✅ 12.2 MCP resource reading in McpClient (list_resources + read_resource + caching) — 11 unit tests
- ✅ 12.3 read_mcp_resource tool in ToolExecutor + ThinRuntime active_tools wiring — 15 integration tests
- ✅ 12.4 RuntimeConfig web_allowed_domains/web_blocked_domains fields + ResourceDescriptor frozen dataclass exported
- ✅ Quality gates: 4824 tests pass, ruff clean

### Phase 13: Conversation Compaction ✅ DONE (Judge 4.23/5.0, 2026-04-13, commit 8a63ad6)
- ✅ 13.1 ConversationCompactionFilter (InputFilter protocol) + CompactionConfig frozen dataclass
- ✅ 13.2 3-tier cascade: tool result collapse → LLM summarization → emergency truncation
- ✅ 13.3 Auto-wired in ThinRuntime.run() from RuntimeConfig.compaction + 35 tests (26 unit + 9 integration)
- ✅ Quality gates: 4859 tests pass, ruff clean

### Phase 14: Session Resume ✅ DONE (Judge 4.30/5.0, 2026-04-13, commit d3602c5)
- ✅ 14.1 JsonlMessageStore — JSONL file-based persistence (SHA-256 filenames, corrupted-line resilience) + 18 unit tests
- ✅ 14.2 Conversation.resume(session_id) + auto-persist in say()/stream() + auto-compaction on resume — 10 unit tests
- ✅ 14.3 Integration tests (12) + quality gate: 4899 tests pass, ruff clean

### Phase 15: Thinking Events ✅ DONE (Judge 4.42/5.0, 2026-04-13, commit 8c56581)
- ✅ 15.1 ThinkingConfig frozen dataclass + RuntimeEvent.thinking_delta factory + LlmCallResult — 22 unit tests
- ✅ 15.2 AnthropicAdapter thinking extraction + LLM client wiring + strategy emission + non-Anthropic warning — 23 unit tests
- ✅ 15.3 Compaction non_compactable exclusion (tier 2 + tier 3) + integration tests — 14 tests
- ✅ Quality gates: 4959 tests pass, ruff clean

### Phase 16: Multimodal Input ✅ DONE (Judge 4.26/5.0, 2026-04-13, commit 54fed1c)
- ✅ 16.1 ContentBlock types (TextBlock, ImageBlock) + Message.content_blocks additive field — 28 unit tests
- ✅ 16.2 Provider adapters (Anthropic vision, OpenAI image_url, Google inline_data) in call/stream/call_with_tools — 21 unit tests
- ✅ 16.3 Read tool image detection + BinaryReadProvider ISP split + PDF/Jupyter extractors — 20 unit tests
- ✅ 16.4 Integration tests (14) + quality gate: 5042 tests pass, ruff clean

### Phase 17: Parallel Agent Infrastructure ✅ DONE (Judge 4.15/5.0, 2026-04-13, commit 2e2c800)
- ✅ 17.1 SubagentSpec.isolation field + worktree lifecycle in ThinSubagentOrchestrator (create/cleanup/stale/max 5) — 14 unit tests
- ✅ 17.2 spawn_agent tool isolation parameter + SUBAGENT_TOOL_SPEC update — 8 unit tests
- ✅ 17.3 RuntimeEvent.background_complete + SubagentSpec.run_in_background + background orchestration — 15 unit tests
- ✅ 17.4 monitor_agent tool + ThinRuntime background event wiring — 17 unit tests
- ✅ Quality gates: 5096 tests pass, ruff clean

## ThinRuntime Claude Code Parity v2 — COMPLETE (7/7 phases, 2026-04-13)

## ThinRuntime Claude Code Parity v1 (2026-04-12) — Phases 1-10 COMPLETE

### Phase 1: Hook Dispatch (P0 — security) ✅ DONE
- ✅ 1.1 HookDispatcher Protocol + DefaultHookDispatcher + 27 unit tests (100% coverage)
- ✅ 1.2 Интеграция hooks в ToolExecutor (pre/post) + 7 unit tests
- ✅ 1.3 Интеграция hooks в ThinRuntime.run() (stop/user_prompt) + 7 unit + 3 wiring + 2 integration tests
- ✅ 1.4 Прокидывание hooks Agent → RuntimeFactory → ThinRuntime (via merge_hooks in create_kwargs)

### Phase 2: Tool Policy Enforcement (P0 — security) ✅ DONE
- ✅ 2.1 DefaultToolPolicy в ToolExecutor + 8 unit tests (6 original + 2 edge cases)
- ✅ 2.2 Прокидывание policy Agent → ThinRuntime + 2 wiring tests

### Phase 3: LLM-Initiated Subagents (P1) ✅ DONE
- ✅ 3.1 SubagentTool spec + types + executor + 25 unit tests (100% coverage)
- ✅ 3.2 Wire into ThinRuntime + 4 unit + 4 integration tests

### Phase 4: Command Routing (P2) ✅ DONE
- ✅ 4.1 CommandInterceptor + ThinRuntime integration + 11 unit tests + 2 wiring tests
- ✅ 4.2 Integration tests (Agent → ThinRuntime → CommandRegistry) + 2 integration tests

### Phase 5: Native Tool Calling (P2) ✅ DONE
- ✅ 5.1 NativeToolCallAdapter Protocol + types + 3 adapters + 18 unit tests
- ✅ 5.2 React strategy integration + parallel execution + fallback + 8 strategy tests
- ✅ 5.3 Integration tests (ThinRuntime e2e + backward compat) + 3 integration tests

### Phase 6: Integration Validation (P3) ✅ DONE
- ✅ 6.1 Cross-feature integration tests (hooks+commands, stop hook, backward compat) + 5 tests
- ✅ 6.2 mypy fix (variable shadowing in native tool path)
- ✅ 6.3 Quality gates: 4394 tests pass, ruff clean, mypy clean, coverage 86%

### Phase 7: Coding Profile Foundation ✅ DONE
- ✅ 7.1 CodingProfileConfig contract + canonical tool pack + policy wiring
- ✅ 7.2 Shared builtin tools (read/write/edit/bash/glob/grep) + ThinRuntime integration
- ✅ 7.3 Profile-scoped regressions + backward compat tests (155 tests, Judge 4.40/5.0)

### Phase 8: Coding Task Runtime and Persistence ✅ DONE
- ✅ 8.1 Coding task runtime facade + persistent task/todo/session adapters (83 tests, Judge 4.33/5.0)

### Phase 9: Coding Context and Compatibility ✅ DONE
- ✅ 9.1 Coding context assembler + compatibility/fail-fast wiring (329 tests, Judge 4.34/5.0)

### Phase 10: Coding Subagent Inheritance and Validation ✅ DONE
- ✅ 10.1 Coding-profile subagent inheritance + tranche-level validation closure (341 tests, Judge 4.38/5.0)

## Audit remediation tranche (2026-04-11)

- ✅ Security hardening: namespace segment validation, A2A/daemon auth defaults, CLI env redaction, MCP target validation, plan-store namespace-aware load/update
- ✅ Root README quickstarts synchronized with shipped API and covered by executable docs test
- ✅ Application/runtime boundary hardened via `RuntimeFactoryPort`; `AgentConfig.resolved_model` reduced to deprecation shim
- ✅ Test strategy hardened with negative/success regressions for namespace isolation, auth defaults, CLI env policy, MCP URL policy, README drift
- ✅ Low-risk DRY slice completed for graph task-board SQLite/Postgres serialization helpers
- ✅ Phase-4 low-risk structural follow-up completed for `ThinRuntime` helper extraction and `DefaultGraphOrchestrator` run-state/store extraction
- ✅ Phase-4 low-risk structural follow-up completed for `SessionManager` runtime execution bridge extraction
- ✅ Phase-4 low-risk structural follow-up completed for `SessionManager` snapshot codec/store extraction
- ✅ Final validation green: repo-wide `ruff`, repo-wide `mypy`, full offline `pytest -q`

## v1.4.0 stabilization tranche

- ✅ README/docs/configuration/docs/getting-started/docs/migration-guide/CHANGELOG synchronized with secure-by-default defaults
- ✅ Structured security decision logging added for deny-paths (host exec, `/v1/query`, network target)
- ✅ Validation matrix completed: offline `pytest -q`, repo-wide `ruff`, repo-wide `mypy`, explicit `integration`, disposable Postgres harness, `live`
- ✅ Memory Bank updated to reflect current repo truth and release posture
- ✅ Targeted stale-wording checks completed on user-facing docs and release notes

## Интеграция upstream middleware deepagents + multi-provider

- ✅ Phase 0C: Shared ProviderResolver (provider_resolver.py) — 24 теста
- ✅ Phase 0B: ThinRuntime multi-provider (llm_providers.py — 3 адаптера + factory + stream + caching + default_llm_call) — 30 тестов
- ✅ Phase 1: Пробросить memory/subagents/skills/middleware в create_deep_agent() — 6 тестов
- ✅ Phase 5: deepagents 0.5.0 не вышел на PyPI, остаёмся на 0.4.11
- ✅ Phase 2: Compaction — noop для native, token-aware для portable, arg truncation — 19 тестов
- ✅ Phase 0A: Portable memory (AGENTS.md read) + token-aware compaction — 8+7 тестов
- ✅ Phase 3: Cross-session memory — native propagation + auto-backend + portable injection — 8 тестов
- ✅ Phase 4: Capabilities (HITL native-only; builtin_memory/builtin_compaction не advertised runtime-level) — обновлены + тесты

## Ревью gap'ы — исправлены

- ✅ 2026-03-18: session backend snapshot sync + lazy restore + backend cleanup verified
- ✅ 2026-03-18: registry-aware capability negotiation wired for RuntimeConfig / AgentConfig / RuntimeFactory / Agent
- ✅ 2026-03-18: ThinRuntime now enforces estimated cost budget, cooperative cancellation, and shared structured-output validation in conversational/react/planner
- ✅ 2026-03-18: `close_all()` keeps persisted session snapshots; ThinRuntime buffers streamed text until guardrails/output validation/retry can no longer rewrite or block it
- ✅ 2026-03-18: P1 follow-up fixes — `runtime="cli"` ignores facade-only kwargs, CLI stdin includes `system_prompt`, `execute_agent_tool()` fails on `RuntimeEvent.error`/missing final, `TaskQueue.get()` atomically claims TODO tasks as `IN_PROGRESS`
- ✅ 2026-03-18: review-fix batch 2 — SQLite `complete()`/`cancel()` use atomic CAS transition, CLI runtime emits `bad_model_output` when subprocess exits without final event, Claude autodetect uses basename, `execute_agent_tool()` catches arbitrary `Exception`
- ✅ K1: stream() method в LlmAdapter + все 3 адаптера
- ✅ K2: GoogleAdapter multi-turn format (user+assistant)
- ✅ C2: Auto-backend (FilesystemBackend) при memory + no backend
- ✅ C5: DRY is_native_mode property в RuntimeConfig
- ✅ C7: Argument truncation (только tool messages, >2000 chars)
- ✅ З1: Кеширование адаптера (get_cached_adapter)
- ✅ З6: Интеграционные тесты ThinRuntime multi-provider — 10 тестов
- ✅ #8: default_llm_call stream=True → adapter.stream()
- ✅ #9: DRY — _filter_chat_messages + _prepare в адаптерах
- ✅ #14: truncate_long_args — только tool/function roles
- ✅ #15: тест builtin_compaction capability
- ✅ RF1: `swarmline[thin]` bundle'ит openai + google-genai, docs синхронизированы
- ✅ RF2: `AnthropicAdapter.call()` снова конкатенирует все text blocks
- ✅ RF3: `deepagents` больше не рекламирует `hitl` через runtime-level capabilities
- ✅ RF4: Native/hybrid memory больше не дублируется в `<agent_memory>` prompt injection
- ✅ RF5: `deepagents` больше не рекламирует `builtin_memory` / `builtin_compaction` через runtime-level capabilities
- ✅ RF6: ThinRuntime больше не отдаёт pseudo-JSON envelope в stream error-path; ошибки идут через `RuntimeEvent.error`
- ✅ RF7: `google:*` path реально поддерживает `base_url` через `google-genai` client `http_options`

## Phase 6: DX Foundation (v0.6.0)

- ✅ 6A: Structured Output via Pydantic (IDEA-011) — output_type, retry, validation — 19 unit + 6 integration
- ✅ 6B: Tool Schema Auto-generation (IDEA-016) — @tool decorator — 18 unit + 7 integration
- ✅ 6C: Extensible Adapter Registry (IDEA-002) — register/get, entry points — 21 unit + 3 integration
- ✅ 6D: Legacy Cleanup + Core DX (IDEA-024, 025) — protocols split, cancellation, typed events, context manager, error messages English — 16+18 unit
- ✅ 6-DOC: Getting Started guide + examples/ + CHANGELOG v0.6.0

## Phase 7: Production Safety (v0.7.0)

- ✅ 7A: Cost Budget Tracking (IDEA-004) — 23 unit + 5 integration
- ✅ 7B: Guardrails + CallerPolicy (IDEA-008, 022) — 28 тестов (19 unit + 9 integration)
- ✅ 7C: Pre-LLM Input Filter (IDEA-013) — 17 unit + 3 integration
- ✅ 7D: Retry / Fallback Policy (IDEA-026) — 15 unit + 3 integration
- ✅ 7-DOC: Guides + examples + CHANGELOG v0.7.0

## Phase 8: Persistence & UI (v1.0.0-core)

- ✅ 8A: Session Backends + Memory Scopes (IDEA-010, 005, 021) — SessionBackend Protocol, InMemory + Sqlite backends, MemoryScope enum — 16 unit + 4 integration
- ✅ 8B: Event Bus + Tracing (IDEA-015, 027) — EventBus Protocol, InMemoryEventBus, Tracer Protocol, NoopTracer, ConsoleTracer, TracingSubscriber, ThinRuntime wiring — 18 unit + 5 integration
- ✅ 8C: UI Event Projection (IDEA-023) — EventProjection Protocol, UIState/UIMessage/UIBlock, ChatProjection, project_stream — 19 unit + 6 integration
- ✅ 8D: RAG / Retriever Protocol (IDEA-028) — Retriever Protocol, Document, RagInputFilter, SimpleRetriever, auto-wrap in ThinRuntime — 14 unit + 4 integration
- ✅ 8-DOC: Full docs site (mkdocs-material) + CHANGELOG v1.0.0-core

## DOC-debt + Phase 9 MVP + Phase 10A

- ✅ Stage 1: examples/ runnable scripts (9 files + README.md)
- ✅ Stage 2: CHANGELOG v0.6.0, v0.7.0, v1.0.0-core
- ✅ Stage 3: Getting Started guide update
- ✅ Stage 4: mkdocs.yml nav update
- ✅ Stage 5: 9A Protocol + types (AgentTool, AgentToolResult)
- ✅ Stage 6: 9A Contract tests — 10 tests
- ✅ Stage 7: 9A Implementation (agent_tool.py — create_agent_tool_spec, execute_agent_tool)
- ✅ Stage 8: 9A Integration tests — 10 tests
- ✅ Stage 9: 9B-MVP Protocol + types (TaskQueue, TaskItem, TaskStatus)
- ✅ Stage 10: 9B-MVP Contract tests — 24 tests (parametrized inmemory+sqlite)
- ✅ Stage 11: 9B-MVP Implementation (InMemory + Sqlite)
- ✅ Stage 12: 9B-MVP Integration tests — 6 tests
- ✅ Stage 13: 9C-MVP Protocol + types (AgentRegistry, AgentRecord, AgentStatus)
- ✅ Stage 14: 9C-MVP Contract tests — 11 tests
- ✅ Stage 15: 9C-MVP Implementation (InMemoryAgentRegistry)
- ✅ Stage 16: 9C-MVP Integration tests — 3 tests
- ✅ Stage 17: 10A Protocol + types (CliConfig, NdjsonParser, ClaudeNdjsonParser)
- ✅ Stage 18: 10A Contract tests — 18 tests (parser + types + runtime)
- ✅ Stage 19: 10A Implementation (CliAgentRuntime + registry + capabilities)
- ✅ Stage 20: 10A Integration tests — 6 tests (added timeout + registry)
- ✅ Stage 21: 10A + 9 MVP docs (cli-runtime.md, multi-agent.md, CHANGELOG)
- ✅ Stage 22: Full test suite (2301 passed) + lint + mypy clean
- ✅ Code review round 1: narrowed exceptions, isinstance test, None score fix
- ✅ Code review round 2: assert→guard, process leak fix, unused imports, 2 new tests
- ✅ Post-review P1 fixes: +20 tests, full offline pytest green, docs synchronized; repo-wide ruff/mypy still report unrelated existing issues
- ✅ Post-review P1 fixes batch 2: +10 regression tests, `ruff check` green, full offline `pytest -q` green (`2331 passed`); `mypy` still blocked by pre-existing import-graph errors outside diff
- ✅ 2026-03-18: audit remediation Wave 1 — portable `mcp_servers`, canonical `final.new_messages`, terminal contract hardening, port/session final metadata, thin-team `send_message`, single-layer retry; targeted `pytest`/`ruff`/`mypy` and full offline `pytest -q` verified
- ✅ 2026-03-18: audit remediation Wave 2 low-risk slices — shared portable runtime wiring helper for `Agent`/`Conversation` and lazy fail-fast optional exports for `runtime`/`hooks`/`memory`/`skills`; targeted `pytest`/`ruff`/`mypy` and full offline `pytest -q` verified
- ✅ 2026-03-18: re-audit remediation complete — `SessionManager` keeps canonical `final.new_messages`, `BaseRuntimePort`/session runtime paths fail on silent EOF and preserve final metadata, `ClaudeCodeRuntime` stops after terminal error, DeepAgents portable path round-trips tool history, builtin `cli` works through registry and legacy fallback, workflow executor advertises tools, docs/runtime narrative synced, repo-wide `ruff`/`mypy` green, full offline `pytest -q` green (`2366 passed`)
- ✅ 2026-03-18: follow-up hardening pass — `Conversation` больше не пишет partial assistant history после terminal `error`, portable runtime exceptions нормализуются в typed error path для `Conversation`/`SessionManager`, `CliAgentRuntime.cancel()` возвращает `cancelled`, `InMemoryMemoryProvider` теперь snapshot-store для session state, storage priority покрыт regression tests, repo-wide `ruff`/`mypy` green, full offline `pytest -q` green (`2397 passed`)

## v1.0.0-core Release Pipeline

- ✅ Этап 1: Ruff cleanup — src/ (11 errors → 0)
- ✅ Этап 2: Ruff cleanup — tests/ (49 errors → 0)
- ✅ Этап 3: Mypy cleanup (27 errors в 17 файлах → 0)
- ✅ Этап 4: Wave 2 remaining — Session/runtime migration cleanup (Phase 5)
- ✅ Этап 5: Wave 2 remaining — Factory/registry hardening (Phase 6)
- ✅ Этап 6: CHANGELOG.md финализация
- ✅ Этап 7: Getting Started guide обновление
- ✅ Этап 8: mkdocs site audit и актуализация
- ⬜ Этап 9: Version bump 0.5.0 → 1.0.0 + PyPI release
- ✅ Этап 10: Финальная проверка (all gates green)

## Phase 16: Code Agent Integration

- ✅ Wave 1: HeadlessRuntime + MCP Types + StatefulSession — 24 tests
- ✅ Wave 2: Headless Tools (memory 6 + plans 5 + team 5 + code 1) — 57 tests
- ✅ Wave 3: Agent Tools 3 + MCP Server Assembly + pyproject.toml — 11 tests
- ✅ Wave 4: CLI Client (Click app + 6 command groups) — 32 tests
- ✅ Wave 5: SKILL.md + 10 references + integration configs (claude-code/codex/opencode) + docs (4 files)
- ✅ Wave 6: 7 E2E Use Case Tests (31 tests) + docs/use-cases.md update

## Graph Agents + Knowledge Bank (2026-03-29)

### Code Review Fixes
- ✅ S1: delegate_task governance enforcement (check_delegate_allowed подключён)
- ✅ S2: root task execution tracking (AgentExecution в start())
- ⬜ S3: Race condition DefaultKnowledgeStore index (→ BACKLOG)
- ⬜ S4-W7: Minor findings (→ BACKLOG)

### Task Progress + BLOCKED + Workflow Stages
- ✅ Phase 1: TaskStatus.BLOCKED + progress/stage/blocked_reason fields + WorkflowConfig
- ✅ Phase 2: Serialization (SQLite/Postgres) + block_task/unblock_task в 3 backend'ах
- ✅ Phase 3: Progress auto-calc с рекурсивной propagation (_propagate_parent)
- ✅ Phase 4: Stage в delegate_task tool + exports WorkflowConfig/WorkflowStage

## Paperclip-inspired Components (2026-03-29)

- ✅ 1.1: TaskSessionStore — protocol + InMemory + SQLite — 26 tests
- ✅ 1.2: ActivityLog + ActivityLogSubscriber — protocol + InMemory + SQLite — 39 tests
- ✅ 1.3: PersistentBudgetStore — protocol + InMemory + SQLite — 26 tests
- ✅ 2.1: RoutineBridge — Scheduler → TaskBoard bridge — 17 tests (14 unit + 3 integration)
- ✅ 2.2: ExecutionWorkspace — temp_dir/git_worktree/copy isolation — 10 tests
- ✅ 3.1: PluginRunner + worker shim — subprocess JSON-RPC — 21 tests
- ✅ Review: S1 lock fix (workspace) + S2 publish→emit fix (task_session_store)

## Production v2.0 — Phase 01a: ty-strict-foundation (2026-04-25)

> Plan: [plans/2026-04-25_feature_production-v2-phase-01a-ty-strict-foundation.md](plans/2026-04-25_feature_production-v2-phase-01a-ty-strict-foundation.md)
> Sprint Gate: 75 → ≤62 ty diagnostics; 11 critical errors → 0; CI gate активен; 3 patterns documented
> **Note:** baseline зафиксирован = **75** (фактическое значение `ty check src/swarmline/` на 2026-04-25). Цифра 70 в строке 6 этого файла — устаревший release-gate snapshot, будет обновлена в Stage 6.

### Stage 1: ty strict-mode meta-test + CI gate ✅ DONE (2026-04-25)
- ✅ `tests/architecture/test_ty_strict_mode.py` создан (3 теста: baseline-file/diagnostics/ci-step), все green локально
- ✅ `tests/architecture/ty_baseline.txt` = 75
- ✅ `.github/workflows/ci.yml` создан (lint + typecheck + tests + architecture jobs); содержит step `ty check src/swarmline/`, fail-on-error
- ✅ `pytest tests/architecture/ -v -m slow` зелёный, 3/3 passed
- ✅ `ruff check tests/architecture/` clean; `ruff format --check` clean
- ✅ `slow` marker зарегистрирован в `pyproject.toml [tool.pytest.ini_options]`
- ✅ Регрессий нет (полный pytest collect 5171/5179 tests, без коллизий)

### Stage 2: Fix GraphTaskBoard missing methods (coding_task_runtime crashes) ✅ DONE (2026-04-25)
- ✅ `ty check src/swarmline/orchestration/coding_task_runtime.py` — 0 attr-defined errors (на 165/182/186 post-format)
- ✅ 15 новых тестов passed (6 unit с parametrize + 4 integration + lifecycle preserved)
- ✅ `tests/architecture/ty_baseline.txt` → 72 (75 → 72, ✓ -3)
- ✅ ISP: 3 базовых Protocol сохраняют ≤5 методов; `CodingTaskBoardPort` — composition (7 методов на orchestration layer)
- ✅ Backwards compat: 4550 existing tests passed без изменений; duck typing на InMemory/SQLite/Postgres сохраняется
- ✅ ruff/format clean; meta-test `tests/architecture/test_ty_strict_mode.py` green с baseline=72

### Stage 3: Fix isolated type bugs (project_instruction_filter + agent_registry_postgres) ✅ DONE (2026-04-25)
- ✅ `ty check project_instruction_filter.py` — 0 errors (annotation `list[tuple[int, list[str]]]`)
- ✅ `ty check multi_agent/agent_registry_postgres.py` — 0 errors (`cast(CursorResult, result).rowcount`)
- ✅ 4 теста green (3 unit project_instruction_filter + 1 source-check agent_registry_postgres); 2 PG-runtime tests properly skipped без PG_DSN
- ✅ `tests/architecture/ty_baseline.txt` → 70 (72 → 70, ✓ -2)
- ✅ Удалён `# type: ignore[attr-defined]` — заменён на typed `cast(CursorResult, result)`
- ✅ ruff/format clean

### Stage 4: ToolFunction Protocol для __tool_definition__ ✅ DONE (2026-04-25)
- ✅ `src/swarmline/agent/tool_protocol.py` создан с `@runtime_checkable Protocol`, экспортирован из `swarmline.agent`
- ✅ `ty check agent/tool.py` — 0 errors (декоратор `tool()` теперь возвращает `ToolFunction`)
- ✅ `ty check multi_agent/graph_tools.py` — 0 errors (cast не нужен — return type уже типизирован)
- ✅ `grep -n "type: ignore" multi_agent/graph_tools.py` → 0 occurrences (был 3)
- ✅ 8 unit-тестов green (Protocol declaration + isinstance + source invariants + parametrize)
- ✅ `tests/architecture/ty_baseline.txt` → 66 (70 → 66, ✓ -4)
- ✅ 761 regression tests passed (no breakage in tool ecosystem)

### Stage 5: hooks/dispatcher __name__ helper ✅ DONE (2026-04-25)
- ✅ `_hook_name` helper создан в `src/swarmline/hooks/_helpers.py`, fully documented
- ✅ `ty check hooks/dispatcher.py` — 0 errors на 106,158,194,207
- ✅ 11 новых тестов passed (named/async/partial/lambda/class-callable/non-callable/source-invariant + 5 parametrize)
- ✅ DRY: 4 inline `entry.callback.__name__` заменены на `_hook_name(entry.callback)`
- ✅ `tests/architecture/ty_baseline.txt` → 62 (66 → 62, ✓ -4)
- ✅ 106 hook regression tests passed; ruff/format clean

### Stage 6: Decisions doc + Sprint 1B handoff + ADR ✅ DONE (2026-04-25)
- ✅ `.memory-bank/notes/2026-04-25_ty-strict-decisions.md` создан — 3 паттерна (OptDep/DecoratedTool/CallableUnion) с примерами кода
- ✅ ADR-003 — Use ty in strict mode as sole type checker (no mypy) — добавлен в BACKLOG.md (Context/Options A-B-C/Decision/Rationale/Consequences заполнены)
- ✅ `plans/2026-04-25_feature_production-v2-phase-01b-ty-bulk-cleanup.md` scaffold + Context (ссылки на Sprint 1A + decisions note + baseline 62 + 5-stage preliminary breakdown)
- ✅ Архитектурный meta-test green после baseline=62
- ✅ `progress.md` append для Sprint 1A completion (6 stages, 21 tests, 7 condition Gate)
- ✅ Sprint Gate verified — все 7 conditions green (ty ≤62, baseline=62, decisions note, Sprint 1B plan, ADR-003, CI gate, no regressions)

## Production v2.0 — Phase 01b: ty-bulk-cleanup (2026-04-25)

> Plan: [plans/2026-04-25_feature_production-v2-phase-01b-ty-bulk-cleanup.md](plans/2026-04-25_feature_production-v2-phase-01b-ty-bulk-cleanup.md)
> Sprint Gate: 62 → 0 ty diagnostics; baseline locked = 0; canonical `# ty: ignore[<rule>]  # <reason>` pattern across all suppressions; 6 stages, ~60+ tests added; ADR-003 outcome confirmed.

### Stage 1: OptDep batch — 22 unresolved-import → 0 ✅ DONE (2026-04-25)
- ✅ 22 `unresolved-import` ошибок закрыты ty-native ignore + reason на 16 файлах
- ✅ 22 `# type: ignore[import-not-found]` (inert mypy-style) удалены
- ✅ `tests/unit/test_optdep_typing_fixes.py` — 23 cases (22 line-anchored + 1 no-naked scan)
- ✅ `tests/architecture/ty_baseline.txt` → 40 (62 → 40, ✓ -22)
- ✅ Full offline pytest green; ruff/format clean

### Stage 2: Unresolved-attribute batch — 4 fixes ✅ DONE (2026-04-25)
- ✅ 4 `unresolved-attribute` закрыты — 3 ty-native ignore + 1 structural fix (cast `CursorResult` для SQLAlchemy 2.x)
- ✅ `tests/unit/test_attribute_resolution_fixes.py` — 4 cases line-anchored + structural invariant
- ✅ `tests/architecture/ty_baseline.txt` → 36 (40 → 36, ✓ -4)
- ✅ Full offline pytest green; ruff/format clean

### Stage 3: Callable narrow — 9 call-non-callable → 0 ✅ DONE (2026-04-25)
- ✅ 9 `call-non-callable` ошибок закрыты ty-native ignore + reason на 6 файлах
- ✅ Декораторы (`@functools.wraps`, `@track_metrics`) и SDK callable-union strict cases
- ✅ `tests/unit/test_callable_narrow_fixes.py` — 9 line-anchored + 1 no-naked scan
- ✅ `tests/architecture/ty_baseline.txt` → 27 (36 → 27, ✓ -9)
- ✅ Full offline pytest green; ruff/format clean

### Stage 4: Argument-type batch — 22 mixed → 5 ✅ DONE (2026-04-25)
- ✅ 22 ошибок закрыты: 17 invalid-argument-type + 3 unknown-argument + 2 no-matching-overload
- ✅ 18 ty-native ignore (SDK strictness) + STRUCTURAL fix в `pi_sdk/event_mapper.py` (4 errors → 0)
- ✅ Real bug closure: `TurnMetrics(input_tokens=...)` → canonical `tokens_in`/`tokens_out`/`tool_calls_count`/`model` (TypeError at runtime if uncaught)
- ✅ `tests/unit/test_argument_type_fixes.py` — 18 line-anchored + 2 event_mapper structural + 9 no-naked-scans = 29 tests
- ✅ `tests/architecture/ty_baseline.txt` → 5 (27 → 5, ✓ -22)
- ✅ Full offline pytest 5341 green; ruff/format clean

### Stage 5: Точечные остатки — 5 misc → 0 ✅ DONE (2026-04-25)
- ✅ 5 ошибок закрыты ty-native ignore + reason: 2× invalid-return-type + 2× invalid-assignment + 1× not-iterable
- ✅ 4 inert `# type: ignore[...]` (mypy-style) заменены на ty-native syntax
- ✅ Multi-rule extension: `[unresolved-attribute, not-iterable]` на Gemini parts loop
- ✅ `tests/unit/test_misc_typing_fixes.py` — 4 line-anchored + 1 multi-rule + 4 no-naked + 1 inert-mypy guard = 10 tests
- ✅ `tests/architecture/test_ty_strict_mode.py` parser extended (recognizes `All checks passed!` zero-diagnostic shape)
- ✅ `tests/architecture/ty_baseline.txt` → 0 (5 → 0, ✓ -5)
- ✅ Full offline pytest 5352 green; ruff/format clean

### Stage 6: Final verification + lock baseline=0 ✅ DONE (2026-04-25)
- ✅ `ty check src/swarmline/` → **All checks passed!** (0 diagnostics)
- ✅ `tests/architecture/ty_baseline.txt` = **0** (locked)
- ✅ STATUS.md updated — release gate green; ty strict-mode = sole release gate (ADR-003 outcome confirmed)
- ✅ checklist.md Sprint 1B section closed (6 stages all DONE)
- ✅ progress.md append for Sprint 1B completion (6 stages, ~70 new tests)
- ✅ Sprint Gate verified — все conditions green (ty=0, baseline=0, full pytest 5352 passed, ruff clean, ADR-003 fulfilled)

## P1/P2 Audit Gaps (2026-03-30)
⬜ Этап 1: P1 false-green completion + task board state consistency
⬜ Этап 2: P1 ThinRuntime per-call config for LLM path
⬜ Этап 3: P2 Concurrency (WorkflowGraph, SessionManager, Scheduler)
⬜ Этап 4: P2 SQLite thread safety + task queue performance
⬜ Этап 5: P2 Security hardening (SSRF, workspace, A2A, Docker, MCP, daemon)
⬜ Этап 6: P3 Observability bounds + final verification
⬜ Этап 7: Integration tests (KB, memory, pipeline, HITL, plugins, daemon, task progress) — 22 tests
⬜ Этап 8: E2E tests (knowledge agent, graph orchestration, pipeline, daemon) — 9 tests

## Code Audit Fixes (2026-03-29)
⬜ C1: hmac.compare_digest в health.py
⬜ C2: FTS5 sanitization в procedural_sqlite.py
⬜ C4: --token в CLI pause/resume
⬜ C7: cost extractor в budget wrap_runner
⬜ C9: max_retries `if is not None` в orchestrator
⬜ C10: metadata column в graph_communication_postgres
⬜ S2/S3/S4: Any → Protocol types (системно)
⬜ S5: CLI/YAML priority fix
⬜ S6: task tracking при shutdown
⬜ S12: dataclasses.replace() вместо manual construction
⬜ S15: [nats]/[redis] extras в pyproject.toml

<!-- mb-plan:2026-04-25_fix_v150-release-blockers.md -->
## v1.5.0 release-blockers plan — ALL STAGES DONE (2026-04-25, tag `v1.5.0` → `3fae1b2`)

<!-- mb-plan:2026-04-25_fix_v150-release-blockers.md -->
## Stage 1: CI lint cleanup — `ruff check --fix && ruff format`
- ✅ CI lint cleanup — `ruff check --fix && ruff format` (commit `0badf89` Tier 1, format pass `1511f65`)

<!-- mb-plan:2026-04-25_fix_v150-release-blockers.md -->
## Stage 2: Default runtime fix — `claude_sdk` → `thin`
- ✅ Default runtime fix — `claude_sdk` → `thin` (commit `3bdd7ab`, C-8)

<!-- mb-plan:2026-04-25_fix_v150-release-blockers.md -->
## Stage 3: Russian error string fix
- ✅ Russian error string fix (commit `0badf89` Tier 1)

<!-- mb-plan:2026-04-25_fix_v150-release-blockers.md -->
## Stage 4: Docs lie fix — `agent-facade.md:36`
- ✅ Docs lie fix — `agent-facade.md:36` (commit `0badf89` Tier 1)

<!-- mb-plan:2026-04-25_fix_v150-release-blockers.md -->
## Stage 5: Test isolation fix — drop `force=True`, route stdlib logging to stderr
- ✅ Test isolation fix — drop `force=True`, route stdlib logging to stderr (commit `5cbc326`, C-1, C-3)

<!-- mb-plan:2026-04-25_fix_v150-release-blockers.md -->
## Stage 6: JsonlTelemetrySink async fix — wrap I/O in `asyncio.to_thread()` + add lock
- ✅ JsonlTelemetrySink async fix — wrap I/O in `asyncio.to_thread()` + add lock (commit `32fe1af`, C-2)

<!-- mb-plan:2026-04-25_fix_v150-release-blockers.md -->
## Stage 7: Drop Python 3.10 from `publish.yml` matrix
- ✅ Drop Python 3.10 from `publish.yml` matrix (commit `0badf89` Tier 1)

<!-- mb-plan:2026-04-25_fix_v150-release-blockers.md -->
## Stage 8: Update CLAUDE.md / AGENTS.md to Python 3.11+
- ✅ Update CLAUDE.md / AGENTS.md to Python 3.11+ (commit `0badf89` Tier 1)

<!-- mb-plan:2026-04-25_fix_v150-release-blockers.md -->
## Stage 9: Bump version to 1.5.0
- ✅ Bump version to 1.5.0 (final release commit `3fae1b2`; `pyproject.toml` + `serve/app.py` `_VERSION` both at 1.5.0)

<!-- mb-plan:2026-04-25_fix_v150-release-blockers.md -->
## Stage 10: CHANGELOG.md `[1.5.0]` entry
- ✅ CHANGELOG.md `[1.5.0]` entry (commit `d541edb` Tier 2)

<!-- mb-plan:2026-04-25_fix_v150-release-blockers.md -->
## Stage 11: Migration guide v1.4 → v1.5
- ✅ Migration guide v1.4 → v1.5 (commit `d541edb` Tier 2)

<!-- mb-plan:2026-04-25_fix_v150-release-blockers.md -->
## Stage 12: Feature docs for new v1.5.0 features
- ✅ Feature docs for new v1.5.0 features — 5 docs added (commit `d541edb` Tier 2)

<!-- mb-plan:2026-04-25_fix_v150-release-blockers.md -->
## Stage 13: Add `examples/00_hello_world.py` — 10-line minimal example
- ✅ Add `examples/00_hello_world.py` — 10-line minimal example (commit `d7f2a55` Tier 3, file present at `examples/00_hello_world.py`)

<!-- mb-plan:2026-04-25_fix_v150-release-blockers.md -->
## Stage 14: Trim `swarmline/__init__.py __all__`
- ✅ Trim `swarmline/__init__.py __all__` (commit `d7f2a55` Tier 3)

<!-- mb-plan:2026-04-25_fix_v150-release-blockers.md -->
## Stage 15: Add `SwarmlineError` base exception class
- ✅ Add `SwarmlineError` base exception class (commit `d7f2a55` Tier 3 — errors hierarchy)

<!-- mb-plan:2026-04-25_fix_v150-release-blockers.md -->
## Stage 16: Move `_MockBasicsRuntime` to `swarmline.testing.MockRuntime`
- ✅ Move `_MockBasicsRuntime` to `swarmline.testing.MockRuntime` (commit `d7f2a55` Tier 3)

<!-- mb-plan:2026-04-25_fix_v150-release-blockers.md -->
## Stage 17: Promote `AgentConfig.thinking: dict` → `ThinkingConfig` typed
- ✅ Promote `AgentConfig.thinking: dict` → `ThinkingConfig` typed (commit `d7f2a55` Tier 3 — thinking typing)

<!-- mb-plan:2026-04-25_fix_v150-release-blockers.md -->
## Stage 18: Remove deprecated `max_thinking_tokens`
- ✅ Remove deprecated `max_thinking_tokens` (commit `d7f2a55` Tier 3)

<!-- mb-plan:2026-04-25_fix_v150-release-blockers.md -->
## Stage 19: M-1 fix — enforce loopback host in `serve.create_app(allow_unauthenticated_query=True)`
- ✅ M-1 fix — enforce loopback host in `serve.create_app(allow_unauthenticated_query=True)` (commit `913cb5c` Tier 4)

<!-- mb-plan:2026-04-25_fix_v150-release-blockers.md -->
## Stage 20: M-3 fix — extend `JsonlTelemetrySink` redaction (key + value-level regex)
- ✅ M-3 fix — extend `JsonlTelemetrySink` redaction (key + value-level regex) (commit `913cb5c` Tier 4)

<!-- mb-plan:2026-04-25_fix_v150-release-blockers.md -->
## Stage 21: Add `pip-audit` to CI
- ✅ Add `pip-audit` to CI (commit `913cb5c` Tier 4)

<!-- v1.5.0 follow-up -->
## v1.5.0 follow-up — full-suite isolation fixes
- ✅ Fix two full-suite-only failures from Tier 2/4 (commit `b2fd673`)
- ✅ Apply ruff format pass + sync `test_optdep_imports` line numbers (commit `1511f65`)
- ✅ Record v1.5.0 release plan + 5 audit reports in Memory Bank (commit `82f00cf`)

## v1.5.0 release — pending
- ⬜ Public sync — `./scripts/sync-public.sh --tags` → `github.com/fockus/swarmline` → PyPI auto-publish via OIDC (awaiting user approval)
