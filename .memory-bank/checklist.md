# Checklist

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
- ✅ RF1: `cognitia[thin]` bundle'ит openai + google-genai, docs синхронизированы
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
