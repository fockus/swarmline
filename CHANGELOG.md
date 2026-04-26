# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

(none yet)

## [1.5.0] - 2026-04-25

This is a substantial release that brings ThinRuntime to feature parity with Claude Code's
agent loop and adds two new runtime adapters, multimodal input, parallel agents, session
resume, conversation compaction, and a typed thinking-events surface.

> **Pre-public-release security audit (added 2026-04-27).** Before the public sync to PyPI, a security review surfaced 6 findings (2× P1, 4× P2) which have been folded into v1.5.0. The full pytest gate is now **5532 passed** (was 5452 at initial tag), `ty check` 0 diagnostics, `ruff check` clean. See **Security audit closure** below for details.

### Security audit closure (added 2026-04-27, pre-public-release)

- **P1 — `path_safety` rejects `"."` and `".."` namespace segments.** Previously `SandboxConfig(user_id=".", topic_id="alice")` and `("alice", ".")` resolved to the same workspace path, breaking tenant isolation. Now both raise `ValueError`. Affects `tools/types.SandboxConfig`, `todo/fs_provider`, `memory_bank/fs_provider`.
- **P1 — `pi_sdk` runtime applies an env allowlist (parity with CLI runtime).** The Node bridge previously inherited the full host environment (`OPENAI_API_KEY`, `AWS_*`, CI tokens). It now uses `DEFAULT_PI_SDK_ENV_ALLOWLIST` (`PATH`/`HOME`/Node + provider keys). Legacy behavior available via `PiSdkOptions(inherit_host_env=True)`. New `PiSdkOptions` fields: `inherit_host_env`, `env_allowlist`, `env`. Shared `runtime/_subprocess_env.build_subprocess_env()` helper used by both CLI and pi_sdk runtimes (DRY).
- **P2 — `web_fetch` rejects non-HTTP schemes.** `file://`, `ftp://`, `data:`, `javascript:`, `gopher://`, `ssh://`, `smb://`, `ws[s]://` URLs previously passed `HttpxWebProvider._validate_url` and could reach delegated browser-capable fetch providers (Crawl4AI, Jina). Now blocked at validator entry; only `http`/`https` (case-insensitive) proceed.
- **P2 — E2B sandbox resolves shell-wrapper denylist bypass.** `sh -c 'rm -rf /workspace'` previously bypassed `denied_commands={"rm"}` because the `rm` token sat inside a quoted argument. The provider now detects shell wrappers (`sh`/`bash`/`zsh`/`dash`/`ksh`/`fish`) and recursively re-parses the `-c` payload through the same denylist. Brings E2B to parity with Local/Docker/OpenShell. No behavioral change without an explicit denylist.
- **P2 — Secret redaction for runtime/CLI/serve error messages.** Provider exceptions, CLI subprocess stderr, and HTTP 500 responses could include `Bearer` tokens, `sk-*` API keys (OpenAI, Anthropic), GitHub tokens (`ghp_`/`gho_`/`ghu_`/`ghs_`/`ghr_`), URL userinfo, and `KEY=value` env strings. New `observability/redaction.py` exposes `redact_secrets(text)` and `DEFAULT_SECRET_PATTERNS`; applied at `provider_runtime_crash`, CLI runtime stderr decode, and `/v1/query` 500 path. `JsonlTelemetrySink` now sources the same pattern set (DRY — single source of truth instead of two near-duplicate regex tuples).
- **P2 — `serve.create_app(allow_unauthenticated_query=True)` now requires an explicit `host=` argument.** The earlier v1.5.0 path (logged a deprecation warning when `host=None` and silently accepted the call) could combine with `uvicorn --host 0.0.0.0` to expose unauthenticated `/v1/query` publicly. The host argument is now mandatory; passing `host=None` or `host=""` raises `ValueError`. **Migration:** `create_app(agent, allow_unauthenticated_query=True, host="127.0.0.1")` for local-only mode, or pass `auth_token=` for production.
- **Test additions:** 80 new tests across 6 atomic stages (path_safety 14, pi_sdk env 8, web schemes 19, E2B wrappers 11, redaction 27, serve loopback +2/-1 net). Plan: [`.memory-bank/plans/2026-04-27_fix_security-audit.md`](.memory-bank/plans/2026-04-27_fix_security-audit.md).

### Added

#### ThinRuntime Claude Code parity (Phases 1–10)

- **Hook dispatch** — full `PreToolUse` / `PostToolUse` / `Stop` / `UserPromptSubmit` lifecycle in ThinRuntime via `HookRegistry`.
- **Tool policy enforcement** — `DefaultToolPolicy` is now wired through `ToolExecutor`; default-deny applies to ThinRuntime (parity with `claude_sdk` adapter).
- **LLM-initiated subagents** — `spawn_agent` builtin tool lets the model delegate work to a child Agent. Configurable via `AgentConfig.subagent_config: SubagentToolConfig`.
- **Command routing** — slash-command registry recognized inside ThinRuntime conversations. Configurable via `AgentConfig.command_registry`.
- **Native tool calling** — parallel tool execution path using provider-native function-call APIs (Anthropic `tool_use`, OpenAI `tools`, Google `functionDeclarations`).
- **Coding profile** — opt-in `CodingProfileConfig` enables a curated coding-agent tool surface (sandbox, web, thinking) with hardened policy. Set `AgentConfig.coding_profile`.

#### ThinRuntime Parity v2 (Phases 11–17)

- **Phase 11 — Foundation filters**: `ProjectInstructionFilter` walks up from cwd loading `CLAUDE.md` / `AGENTS.md` / `RULES.md` / `GEMINI.md` into the system prompt; `SystemReminderFilter` injects dynamic context blocks.
- **Phase 12 — Tool surface expansion**: `web_fetch` honours `web_allowed_domains` / `web_blocked_domains` filters; new MCP resource tools (`list_resources`, `read_resource`, builtin `read_mcp_resource`) with TTL caching; `ResourceDescriptor` exported.
- **Phase 13 — Conversation compaction**: 3-tier cascade (tool-result collapse → LLM summarization → emergency truncation) via `ConversationCompactionFilter` + `CompactionConfig`.
- **Phase 14 — Session resume**: `JsonlMessageStore` (SHA-256 filenames, corrupted-line resilience) + `Conversation.resume(session_id)` with auto-persist and auto-compaction.
- **Phase 15 — Thinking events**: typed `ThinkingConfig` union (`ThinkingConfigEnabled` / `ThinkingConfigAdaptive` / `ThinkingConfigDisabled`); `RuntimeEvent.thinking_delta` factory; `LlmCallResult` envelope; AnthropicAdapter extracts thinking blocks.
- **Phase 16 — Multimodal input**: `ContentBlock` / `TextBlock` / `ImageBlock` types; `Message.content_blocks` additive field; multimodal converters for Anthropic / OpenAI / Google adapters; `BinaryReadProvider`; PDF and Jupyter notebook extractors.
- **Phase 17 — Parallel agents**: `SubagentSpec.isolation` (`shared` / `worktree`); per-agent git worktree lifecycle for `spawn_agent`; `RuntimeEvent.background_complete`; new `monitor_agent` builtin tool.

#### New runtime adapters

- **`runtime="pi_sdk"`** — Pi SDK adapter via Node.js bridge. Fourth runtime in the matrix.
- **`runtime="openai_agents"`** — OpenAI Agents SDK adapter (Codex + OpenAI models). Fifth runtime in the matrix.

#### Other additions

- **Agent packs** — `AgentPackResolver`, `AgentPackResource`, `ResolvedAgentPack` for declarative agent-bundle loading. See `docs/agent-pack.md`.
- **Typed pipeline primitives** — structured workflow building blocks (`pipeline/typed.py`, `pipeline/bridge.py`, chain extensions).
- **JSONL telemetry sink** — `JsonlTelemetrySink` subscribes to `EventBus`, writes append-only JSONL events to disk with non-blocking I/O and serialized concurrent writes. Built-in key-name redaction for secrets.
- **Subagent worktree isolation** — `SubagentToolConfig` exposes worktree-isolation knobs to LLM-initiated subagents.

### Changed

- **Default runtime** — `AgentConfig.runtime` default flipped from `"claude_sdk"` → `"thin"`. Existing code that passes `runtime="claude_sdk"` explicitly is unaffected; only callers that relied on the implicit default see new behaviour. Recommendation: pin `runtime=...` explicitly. (See `docs/migration/v1.4-to-v1.5.md`.)
- **Python 3.10 dropped** — minimum supported interpreter is now `>=3.11`. CI matrix updated in `.github/workflows/publish.yml`.
- **`ty` strict-mode baseline = 0** — Sprints 1A/1B drove diagnostics from 75 → 0 (locked in `tests/architecture/ty_baseline.txt`).
- LLM error messages standardised on English in `runtime/thin/errors.py` and `runtime/thin/llm_client.py` (was Russian).
- `docs/agent-facade.md` corrected — `system_prompt` (not `runtime`) is the only required `AgentConfig` parameter.

### Deprecated

- **`AgentConfig.max_thinking_tokens`** — use `AgentConfig.thinking={"type":"enabled","budget_tokens":N}` (or one of the typed `ThinkingConfigEnabled` / `ThinkingConfigAdaptive` / `ThinkingConfigDisabled` dataclasses) instead. Backwards-compatible mapping is preserved in `runtime/options_builder.py`; the field will be removed in a future release.

### Fixed

- **C-1 / C-3** — test isolation: `observability/logger.py` no longer calls `logging.basicConfig(force=True)` on every reconfigure and now routes stdlib logging to `stderr`. This eliminates cross-test contamination and preserves the CLI JSON contract on `stdout`.
- **C-2** — `JsonlTelemetrySink.record()` no longer blocks the event loop: file I/O wrapped in `asyncio.to_thread()` and concurrent writes serialized via a lazy `asyncio.Lock`.
- **C-9** — Russian error string in `runtime/thin/errors.py` translated to English ("LLM API error" replaces "Ошибка LLM API").
- **C-10** — `docs/agent-facade.md` accuracy: `system_prompt` is the only required field; `runtime` defaults to `"thin"`.
- E402 `noqa` placement on multi-line imports in `tests/unit/test_otel_exporter.py`.

### Documentation

- New: `docs/migration/v1.4-to-v1.5.md` — migration guide for the 1.4 → 1.5 transition.
- New / extended: `docs/agent-pack.md`, `docs/observability.md`, `docs/structured-output.md`, `docs/pipeline.md` — parity v2 surface and JSONL telemetry coverage.
- `CLAUDE.md` and `AGENTS.md` aligned to Python 3.11+.

### Internal

- Sprint 1A — `ty` strict-mode foundation (75 → 62 diagnostics).
- Sprint 1B — six staged batches (62 → 0): OptDep, unresolved-attribute, callable narrow, argument-type, miscellaneous, baseline lock.

## [1.4.1] - 2026-04-11

### Changed

- **Branding**: package renamed `cognitia` → `swarmline`. PyPI distribution is `swarmline==1.4.1`. All 4263 tests pass post-rename.
- CI: GitHub Actions workflows updated to Node.js 24-compatible action versions.

### Fixed

- `docs` extra: missing `mkdocstrings` dependency added so `mkdocs build` works in a clean install.

### Tests

- Added contract tests for `Agent.query()` `messages` parameter behaviour.

## [1.4.0] - 2026-04-11

### Changed

- Documented the secure-by-default release posture for the `v1.4.0` stabilization tranche:
  - `enable_host_exec=False` for MCP host execution
  - `allow_host_execution=False` for `LocalSandboxProvider`
  - `allow_unauthenticated_query=False` for `/v1/query`
- Added explicit migration recipes for enabling MCP host exec, enabling sandbox host execution, and intentionally opening `/v1/query`
- Aligned README, capabilities, getting-started, configuration, and memory-bank notes with the current release truth

### Release readiness

- `v1.4.0` is release-doc ready: the remaining work is packaging/version publication, not further product design

## [1.3.0] - 2026-03-30

### Changed

- **Branding**: Swarmline renamed to Swarmline across README and documentation

### Fixed

- **P1 — False-green completion**: Pipeline now detects failed/timed-out root agent (wait_for_task None → phase FAILED)
- **P1 — Task state consistency**: Orchestrator calls checkout_task() on start/delegate, cancel_task() on failure/cancel
- **P1 — ThinRuntime per-call config**: Per-call RuntimeConfig now applies to actual LLM path via partial binding (not just guardrails/cost)
- **P2 — Concurrency**: WorkflowGraph.resume() per-execution interrupt isolation; SessionManager async backend methods; Scheduler honors max_concurrent_tasks via Semaphore
- **P2 — SQLite thread safety**: EpisodicMemory uses threading.Lock + check_same_thread=False; TaskQueue.get() uses SQL-level filtering instead of O(N) Python scan
- **P2 — Security hardening**: SSRF DNS resolution + localhost block + no-redirect; workspace slug validation; A2A server auth_token + request size limit; Docker cap_drop=ALL + network=none + mem_limit; MCP exec_code trusted=True required; daemon auth wired through config
- **P3 — Observability bounds**: ActivityLog max_entries eviction; ConsoleTracer ended span pruning
- **Critical**: FTS5 BEFORE DELETE/UPDATE triggers (prevents stale search duplicates)
- **Critical**: Exponential retry backoff in orchestrator (prevents retry storm / livelock)
- **Critical**: Task board read methods under async lock (prevents dict iteration crash)
- **Critical**: run_turn/stream_reply use async aget() (prevents event loop blocking)
- Workspace lock safety + plugin/session publish→emit method rename
- 30+ additional security, correctness, and concurrency fixes across all modules

## [1.2.0] - 2026-03-30

### Added

- **Agent Graph System** — hierarchical multi-agent with org charts, governance, delegation
  - AgentNode with capabilities, skills, MCP servers, runtime config
  - AgentExecutionContext — structured runner context replacing 4 positional strings
  - GraphBuilder DSL with YAML/dict support
  - Governance: AgentCapabilities (can_hire, can_delegate, max_children) + GraphGovernanceConfig
  - Graph tools: hire_agent, delegate_task, escalate
  - InMemory + SQLite + PostgreSQL backends
  - GraphCommunication: inter-agent messaging (InMemory/SQLite/Postgres/Redis/NATS)
  - GraphTaskBoard: hierarchical tasks with DAG dependencies, atomic checkout
  - Task progress auto-calculation from subtasks
  - TaskStatus.BLOCKED with mandatory reason
  - Extensible workflow stages (WorkflowConfig, WorkflowStage)
- **Knowledge Bank** — universal domain-agnostic structured knowledge storage
  - 5 ISP protocols: KnowledgeStore, KnowledgeSearcher, ProgressLog, ChecklistManager, VerificationStrategy
  - DocumentMeta YAML frontmatter with kind, tags, importance
  - Multi-backend: filesystem, SQLite, PostgreSQL, custom providers
  - Knowledge tools: search, save_note, get_context
  - Episode-to-Knowledge consolidation
- **Pipeline Engine** — multi-phase execution with budget gates
- **Daemon** — universal long-running process manager
- **Evaluation Framework** — agent eval with compare/history (Phases 13.1-13.2)
- **Memory Enhancements**
  - Episodic Memory with InMemory + SQLite (Phase 14.1)
  - Procedural Memory — learned tool sequences (Phase 14.2)
  - Consolidation Pipeline — episodes to knowledge (Phase 14.3)
- **HTTP API** (`swarmline serve`) — Phase 15.1
- **Human-in-the-Loop** approval patterns — Phase 15.2
- **Plugin Registry** + Benchmarks — Phases 15.3-15.4
- **Paperclip-inspired Components**
  - TaskSessionStore: session-per-task persistence
  - ActivityLog + ActivityLogSubscriber: structured audit trail
  - PersistentBudgetStore: durable cost tracking
  - RoutineBridge: scheduler to task board integration
  - ExecutionWorkspace: temp_dir/git_worktree/copy isolation
  - PluginRunner: subprocess JSON-RPC plugin host
- **API Docs** — auto-generated + community infra (Phase 12.3)

### Changed

- GraphTaskBoard: `_propagate_completion()` renamed to `_propagate_parent()` (always recurses for progress)
- Redis/NATS EventBus: URL now required parameter (no localhost default)
- A2A adapter: URL now required parameter
- Provider resolver: ollama/local marked as dev-only defaults
- Clean Architecture: domain types extracted to `domain_types.py`

### Fixed

- 30+ security fixes across all modules (exec_code blocklist, SSRF protection, path traversal, FTS5 sanitization, timing-safe auth)
- 19 mypy type errors resolved (orchestrator, tools, postgres backends, SDK adapters)
- delegate_task governance enforcement (check_delegate_allowed)
- Root task execution tracking in orchestrator
- localhost defaults removed from production constructors

## [1.1.0] - 2026-03-29

### Added

- **Code Agent Integration** (`swarmline.mcp`, `swarmline.cli`) — Phase 16
  - MCP Server (`swarmline-mcp`): 20 typed tools via FastMCP STDIO — memory (6), plans (5), team (5), agent (3), code (1)
  - Headless Runtime: 0 LLM mode for external code agents (Claude Code, Codex CLI, OpenCode)
  - Stateful Session: auto-detect mode from env vars, holds all InMemory providers
  - CLI Client (`swarmline`): Click-based CLI with 6 command groups — memory, plan, team, agent, run, mcp-serve
  - Claude Code Skill: `SKILL.md` + 10 reference patterns for seamless integration
  - Integration configs: claude-code, codex, opencode ready-made configurations
  - 7 E2E use case tests: research swarm, persistent memory, review pipeline, resumable plans, meta-agent, cross-tool, learning agent
- **OpenTelemetry Exporter** (`swarmline.observability.otel`) — Phase 11.1
  - `OTelExporter`: bridges Swarmline EventBus to OpenTelemetry spans
  - Auto-creates spans for LLM calls, tool executions, agent queries
  - Configurable via `OTelConfig(service_name, endpoint, headers, insecure)`
  - Lazy import — only requires `opentelemetry-api` + `opentelemetry-sdk` when used
  - New optional: `swarmline[otel]`
- **Structured Output at Agent Level** (`swarmline.agent`) — Phase 11.2
  - `Agent.query_structured(prompt, output_type: type[T]) -> T` — type-safe Pydantic output
  - Auto-generates JSON Schema from Pydantic model, runs through runtime retry loop
  - `StructuredOutputError` raised when parsing fails after all retries
  - Zero changes to ThinRuntime (already supported `output_type`)
- **A2A Protocol Support** (`swarmline.a2a`) — Phase 11.3
  - Full Agent-to-Agent protocol: JSON-RPC 2.0 over HTTP + SSE streaming
  - `SwarmlineA2AAdapter`: pure adapter pattern, wraps any Agent as A2A service (0 core changes)
  - `A2AServer`: Starlette ASGI server with `/.well-known/agent.json` discovery
  - `A2AClient`: httpx-based client with `discover()`, `send_task()`, `stream_task()`
  - Domain types: `Task`, `AgentCard`, `AgentSkill`, `TaskStatus`, `Message`, `Artifact`
  - New optional: `swarmline[a2a]` (starlette + httpx)
- **`swarmline init` CLI Scaffolding** — Phase 12.1
  - `swarmline init my-agent` scaffolds a production-ready agent project in seconds
  - Flags: `--runtime` (thin/claude/deepagents), `--memory` (inmemory/sqlite), `--full`, `--output`, `--force`
  - Generates: `agent.py`, `config.yaml`, `tests/`, `.env.example`, `pyproject.toml`, `README.md`
  - Full mode adds: `Dockerfile`, `docker-compose.yml`, `skills/`
  - Pure stdlib templates (string.Template), no Jinja2 dependency

### Changed

- `docs/getting-started.md` updated with `swarmline init` quick start as primary onboarding path
- `docs/examples.md` expanded with examples 29 (structured output) and 30 (A2A agent)
- `pyproject.toml` extras: added `otel`, `a2a`, `mcp`, `cli`, `code-agent` bundles

## [1.0.0-core] - 2026-03-18

### Added

- **Structured Output** (`swarmline.runtime`) — Phase 6A
  - `output_type` in `RuntimeConfig` — auto-extracts JSON Schema from Pydantic models
  - `validate_structured_output`, `try_resolve_structured_output`, `extract_structured_output` helpers
  - Retry on validation failure with configurable `max_model_retries`
- **Tool Decorator Enhancements** (`swarmline.agent.tool`) — Phase 6B
  - `@tool` decorator: auto JSON Schema inference from type hints
  - Docstring parsing for parameter descriptions
  - `ToolDefinition.to_tool_spec()` bridge for runtime compatibility
- **Runtime Registry** (`swarmline.runtime.registry`) — Phase 6C
  - `RuntimeRegistry`: thread-safe extensible registry with plugin discovery via entry points
- **Cancellation** (`swarmline.runtime`) — Phase 6D
  - `CancellationToken`: cooperative cancellation with callbacks
- **Runtime Events** (`swarmline.runtime.types`) — Phase 6D
  - Typed `RuntimeEvent` accessors: `.text`, `.tool_name`, `.structured_output`, `.is_final`, `.is_error`
  - Static factory methods: `RuntimeEvent.assistant_delta()`, `.final()`, `.error()`, etc.
- **Runtime Context Manager** — `AgentRuntime` context manager (`async with runtime as r:`) — Phase 6D
- **Protocols ISP Split** — `protocols.py` split into `protocols/memory.py`, `session.py`, `routing.py`, `tools.py`, `runtime.py` — Phase 6D
- **Cost Budget Tracking** (`swarmline.runtime.cost`) — Phase 7A
  - `CostBudget` and `CostTracker` for per-session budget enforcement
  - Bundled `pricing.json` with pricing data for major models
  - Budget enforcement in ThinRuntime with `action_on_exceed` ("error"/"warn")
- **Guardrails** (`swarmline.guardrails`) — Phase 7B
  - `Guardrail` Protocol, `InputGuardrail`/`OutputGuardrail` marker protocols
  - Built-in guardrails: `ContentLengthGuardrail`, `RegexGuardrail`, `CallerAllowlistGuardrail`
  - Parallel guardrail execution via `asyncio.gather`
- **Input Filters** (`swarmline.filters`) — Phase 7C
  - `InputFilter` Protocol for pre-processing user input
  - `MaxTokensFilter` for token budget enforcement
  - `SystemPromptInjector` for dynamic system prompt augmentation
- **Retry and Fallback** (`swarmline.resilience`) — Phase 7D
  - `RetryPolicy` Protocol, `ExponentialBackoff` with jitter
  - `ModelFallbackChain` and `ProviderFallback` data objects for multi-model resilience
- **Session Backends** (`swarmline.session.backends`) — Phase 8A
  - `SessionBackend` Protocol for pluggable session persistence
  - `InMemorySessionBackend` for development and testing
  - `SqliteSessionBackend` with `asyncio.to_thread()` for non-blocking I/O
- **Memory Scopes** (`swarmline.memory.scopes`) — Phase 8A
  - `MemoryScope` enum (`GLOBAL`/`AGENT`/`SHARED`) with `scoped_key()` namespace isolation
- **Event Bus** (`swarmline.observability.event_bus`) — Phase 8B
  - `EventBus` Protocol with fire-and-forget pub-sub
  - `InMemoryEventBus` implementation with topic-based subscription
- **Tracing** (`swarmline.observability.tracing`) — Phase 8B
  - `Tracer` Protocol, `NoopTracer`, `ConsoleTracer` (structlog-based)
  - `TracingSubscriber` bridge connecting EventBus to Tracer
  - ThinRuntime emits `llm_call_start/end`, `tool_call_start/end` events via EventBus
- **UI Projection** (`swarmline.ui.projection`) — Phase 8C
  - `EventProjection` Protocol, `ChatProjection` implementation
  - `project_stream` async generator for real-time UI updates
  - UI blocks: `TextBlock`, `ToolCallBlock`, `ToolResultBlock`, `ErrorBlock`
  - `UIState.to_dict()`/`from_dict()` serialization for frontend transport
- **RAG** (`swarmline.rag`) — Phase 8D
  - `Retriever` Protocol, `Document` frozen dataclass
  - `SimpleRetriever` (word-overlap scoring for development and testing)
  - `RagInputFilter` implementing `InputFilter` — auto-wraps via `RuntimeConfig.retriever`
- **Multi-Agent Coordination** (`swarmline.multi_agent`) — Phase 9 MVP
  - `AgentTool` Protocol — expose any runtime as a callable tool for other agents
  - `create_agent_tool_spec()` / `execute_agent_tool()` — agent-as-tool utility functions
  - `AgentToolResult` frozen dataclass with success/output/error/metrics
  - `TaskQueue` Protocol (5 methods, ISP-compliant) with `InMemoryTaskQueue` and `SqliteTaskQueue`
  - `TaskItem`, `TaskStatus`, `TaskPriority`, `TaskFilter` domain types
  - `AgentRegistry` Protocol (5 methods, ISP-compliant) with `InMemoryAgentRegistry`
  - `AgentRecord`, `AgentStatus`, `AgentFilter` domain types
- **CLI Agent Runtime** (`swarmline.runtime.cli`) — Phase 10A
  - `CliAgentRuntime` — subprocess-based runtime for external CLI agents (Claude Code, custom)
  - `NdjsonParser` Protocol with `ClaudeNdjsonParser` and `GenericNdjsonParser`
  - `CliConfig` frozen dataclass (command, timeout, max_output_bytes, env)
  - Registered in `RuntimeRegistry` as `"cli"` with light tier capabilities
- **27 Runnable Examples** (`examples/`)
  - End-to-end examples covering all major features: agent basics, tool decorator, structured output, middleware, hooks, input filters, guardrails, RAG, memory providers, sessions, cost budget, retry/fallback, cancellation, thinking tool, event bus/tracing, UI projection, runtime switching, custom runtime, CLI runtime, workflow graph, agent-as-tool, task queue, agent registry, deep research, shopping agent, code project team, nano-claw

### Changed

- Audit remediation Wave 1: portable `mcp_servers`, canonical `final.new_messages`, terminal contract hardening, port/session final metadata, thin-team `send_message`, single-layer retry
- Audit remediation Wave 2: shared portable runtime wiring helper for `Agent`/`Conversation`, lazy fail-fast optional exports for `runtime`/`hooks`/`memory`/`skills`
- Re-audit remediation: `SessionManager` keeps canonical `final.new_messages`, `BaseRuntimePort`/session runtime paths fail on silent EOF and preserve final metadata, `ClaudeCodeRuntime` stops after terminal error, DeepAgents portable path round-trips tool history, builtin `cli` works through registry and legacy fallback, workflow executor advertises tools, docs/runtime narrative synced
- Review-fix batch 1: narrowed exceptions, `isinstance` test, `None` score fix
- Review-fix batch 2: `assert` replaced with guard clauses, process leak fix, unused imports removed
- P1 follow-up fixes: `runtime="cli"` ignores facade-only kwargs, CLI stdin includes `system_prompt`, `execute_agent_tool()` fails on `RuntimeEvent.error`/missing final, `TaskQueue.get()` atomically claims TODO tasks as `IN_PROGRESS`
- P1 follow-up batch 2: SQLite `complete()`/`cancel()` use atomic CAS transition, CLI runtime emits `bad_model_output` when subprocess exits without final event, Claude autodetect uses basename, `execute_agent_tool()` catches arbitrary `Exception`

### Fixed

- Repo-wide `ruff check` clean (60 errors in src/ and tests/ resolved)
- Repo-wide `mypy` clean (27 errors in 17 files resolved)
- Session/runtime migration cleanup (Wave 2 Phase 5)
- Factory/registry hardening (Wave 2 Phase 6)

### Deprecated
- `RuntimePort` protocol — use `AgentRuntime` from `swarmline.runtime.base`

## [0.5.0] - 2026-03-16

### Added
- **ThinRuntime Built-in Tools** (`swarmline.runtime.thin.builtin_tools`)
  - 9 tools: `read_file`, `write_file`, `edit_file`, `ls`, `glob`, `grep`, `execute`, `write_todos`, `task`
  - `feature_mode` filtering (portable/hybrid/native_first)
  - DeepAgents-compatible aliases (Read→read_file, Bash→execute, etc.)
  - `merge_tools_with_builtins()` — user tools override built-ins by name
- **Token-Level Streaming** (`swarmline.runtime.thin.stream_parser`)
  - `IncrementalEnvelopeParser` — stateful incremental JSON brace-tracking parser
  - `StreamParser` — high-level streaming parser with ActionEnvelope extraction
  - React + Conversational + Planner modes all stream per-token via `_try_stream_llm_call()`
  - Fallback to non-streaming on parse error
- **ThinTeamOrchestrator** (`swarmline.orchestration.thin_team`)
  - Full `TeamOrchestrator` + `ResumableTeamOrchestrator` protocol implementation
  - Lead delegation: `_compose_worker_task()` personalizes task per worker
  - MessageBus per-team with auto-registered `send_message` tool
  - pause/resume via cancel + re-spawn
- **ThinSubagent Full Implementation** (`swarmline.orchestration.thin_subagent`)
  - `_create_runtime()` creates per-worker `_ThinWorkerRuntime` with ThinRuntime
  - `register_tool()` public method for tool injection (replaces private access)
  - Supports `llm_call`, `local_tools`, `mcp_servers`, `runtime_config` via constructor
- **MessageBus Tools** (`swarmline.orchestration.message_tools`)
  - `SEND_MESSAGE_TOOL_SPEC` — ToolSpec with JSON Schema (to_agent, content)
  - `create_send_message_tool()` — factory for send/broadcast executor
  - `send_message_tool_spec()` — accessor function
- **McpBridge** (`swarmline.runtime.mcp_bridge`)
  - Library-level MCP facade (runtime-agnostic, works with thin + deepagents)
  - `discover_tools()` / `discover_all_tools()` — tool names prefixed as `mcp__{server}__{tool}`
  - `create_tool_executor()` — async callable factory for LangChain integration
  - Caching delegated to McpClient TTL (300s)
- **DeepAgents MCP Integration** (`swarmline.runtime.deepagents`)
  - `mcp_servers` parameter in `__init__()` — creates `McpBridge` automatically
  - MCP tools injected into `selected_tools` with executor wiring
  - Graceful degradation with `logging.warning` on discovery failure
- **WorkflowGraph** (`swarmline.orchestration.workflow_graph`)
  - Declarative graph execution: linear, conditional branching, loop with max, parallel, subgraph, interrupt/resume
  - `InMemoryCheckpoint` for state persistence
  - `to_mermaid()` — graph visualization export
- **Workflow Executors** (`swarmline.orchestration.workflow_executor`)
  - `ThinWorkflowExecutor` — LLM per-node via ThinRuntime
  - `MixedRuntimeExecutor` — route nodes to different runtimes via `node_interceptor`
  - `compile_to_langgraph()` — LangGraph StateGraph compiler for deepagents
- **GenericWorkflowEngine** (`swarmline.orchestration.generic_workflow_engine`)
  - Pluggable `ExecutorPort` + `VerifierPort` protocols
  - Retry/verify loop with configurable `max_retries`
- **CommandRegistry v2** (`swarmline.commands`)
  - `CommandDef` with typed `parameters` (JSON Schema), `description`, `category`
  - `to_tool_definitions()` — commands available as LLM tools
  - `execute_validated()` — JSON Schema parameter validation before execute
  - YAML auto-discovery via `loader.py` (`load_commands_from_yaml`, `auto_discover_commands`)
  - Backward compatible with string-based API
- **JSON Utilities** (`swarmline.runtime.thin.json_utils`)
  - `find_json_object_boundaries()` — shared brace-tracking parser (DRY extraction)

### Changed
- `CodeWorkflowEngine` now delegates to `GenericWorkflowEngine` (thin wrapper with `_PlannerExecutor` + `_DoDVerifierAdapter`)
- `MixedRuntimeExecutor` uses `node_interceptor` parameter instead of monkey-patching `_execute_node`
- Runtime Feature Matrix added to README.md

### Tests
- 298 new tests (1085 → 1383 passed): builtin_tools (20), streaming (20), thin_subagent (9), thin_team (12), message_tools (7), mcp_bridge (4), deepagents_mcp (5), workflow_graph (8), workflow_executor (10), generic_workflow (6), commands_v2 (12), json_utils (18), code_workflow_delegation (3), and more

## [0.4.0] - 2026-03-15

### Added
- **Code Verification Pipeline** (`swarmline.orchestration`)
  - `CodeVerifier` Protocol — ISP-compliant (5 methods: verify_contracts, verify_tests_substantive, verify_tests_before_code, verify_linters, verify_coverage)
  - `TddCodeVerifier` — implementation respecting `CodingStandardsConfig` (disabled checks auto-SKIP)
  - `CommandRunner` Protocol + `CommandResult` — sandbox-agnostic command execution
  - `DoDStateMachine` — criteria-driven verification state machine (PENDING → VERIFYING → PASSED/FAILED) with max loop counter
  - `CodeWorkflowEngine` — structured code pipeline: plan → execute → verify_dod → loop
  - `WorkflowPipeline` Protocol — generic research → plan → execute → review → verify
  - `WorkflowResult` — structured pipeline result
- **Verification Types** (`swarmline.orchestration.verification_types`)
  - `VerificationStatus` (PASS/FAIL/SKIP), `CheckDetail`, `VerificationResult` with `.passed` property
- **Coding Standards Configs** (`swarmline.orchestration.coding_standards`)
  - `CodingStandardsConfig` — TDD, SOLID, DRY, KISS, Clean Arch flags with factory methods: `strict()`, `minimal()`, `off()`
  - `WorkflowAutomationConfig` — `full()`, `light()`, `off()` factories
  - `AutonomousLoopConfig` — `strict()`, `light()` factories
  - `CodePipelineConfig` — aggregate with `production()`, `development()` presets
  - `TeamAgentsConfig` — team role configuration
- **ToolOutputCompressor Middleware** (`swarmline.agent.middleware`)
  - Content-type aware compression: JSON (truncate arrays), HTML (strip tags), Text (head+tail)
  - Integrates with `HookRegistry` via `on_post_tool_use` callback
  - Configurable `max_result_chars` (default 10000)
- **Middleware helpers**
  - `build_middleware_stack()` — factory for common middleware combinations (cost_tracker, tool_compressor, security_guard)
- **HookRegistry.merge()** — public API to combine hook registries from multiple middlewares
- **PlanStep DoD fields** — `dod_criteria`, `dod_verified`, `verification_log` for plan verification tracking

### Changed
- `PlanStep` transition methods use `dataclasses.replace()` (new DoD fields auto-propagate)

### Tests
- 51 new unit tests: tool_output_compressor (12), verification_types (9), coding_standards (12), code_verifier (10), dod_state_machine (8)

## [0.3.0b1] - 2026-03-13

### Added
- **Agent Facade API** (`swarmline.agent`) — high-level 3-line API for AI agents
  - `Agent` class with `query()`, `stream()`, `conversation()` methods
  - `@tool` decorator for defining tools with auto-inferred JSON Schema
  - `Middleware` protocol with built-in `CostTracker` and `SecurityGuard`
  - `Conversation` for explicit multi-turn dialog management
- **Import isolation** — `import swarmline` works without any optional dependencies
- **Test markers** — `requires_claude_sdk`, `requires_anthropic`, `requires_langchain`, `live`
- LICENSE (MIT), CHANGELOG, CONTRIBUTING, comprehensive documentation

### Fixed
- `@tool` handler contract mismatch with Claude Agent SDK MCP format
- `hooks/__init__.py` crash when `claude_agent_sdk` not installed
- Optional dependency boundaries fully verified with smoke tests

## [0.2.0] - 2026-02-11

### Added
- **Multi-runtime support** — 3 pluggable runtimes:
  - `claude_sdk` — Claude Agent SDK (subprocess, built-in MCP)
  - `thin` — lightweight built-in loop (react/planner/conversational modes)
  - `deepagents` — LangChain Deep Agents integration
- **RuntimeFactory** — create runtime by config/env/override
- **Runtime Ports** — `BaseRuntimePort`, `ThinRuntimePort`, `DeepAgentsRuntimePort`
- **Model Registry** — multi-provider (Anthropic, OpenAI, Google, DeepSeek) with aliases
- **SwarmlineStack** — bootstrap facade factory for quick setup
- **Memory providers** — InMemory, PostgreSQL, SQLite
- **Web tools** — pluggable search (DuckDuckGo, Tavily, SearXNG, Brave) and fetch providers
- **Orchestration** — plan manager, subagent spawning, team coordination
- **SDK 0.1.48 integration** — `one_shot_query`, `sdk_tools`, hooks bridge
- **LLM Summarizer** — automatic conversation summarization with history cap
- **Circuit Breaker** — resilience pattern for external calls
- 14 ISP-compliant protocols (each <=5 methods)

### Changed
- Domain-agnostic: removed all finance-specific defaults from library code
- `RoleSkillsLoader` moved to `swarmline.config.role_skills`
- `RoleRouterConfig` is now a typed dataclass (was dict)

## [0.1.0] - 2026-02-10

### Added
- **Core protocols** — `FactStore`, `GoalStore`, `MessageStore`, `SummaryStore`, `UserStore`, `SessionStateStore`, `PhaseStore`, `ToolEventStore`
- **Behavior protocols** — `RoleRouter`, `ModelSelector`, `ToolIdCodec`, `ContextBuilder`, `SessionRehydrator`, `RuntimePort`
- **Session management** — `InMemorySessionManager`, `DefaultSessionRehydrator`
- **Context builder** — `DefaultContextBuilder` with token budget and priority-based overflow
- **Tool policy** — `DefaultToolPolicy` with default-deny and always-denied tools list
- **Skills** — `YamlSkillLoader`, `SkillRegistry` for declarative MCP skill management
- **Routing** — `KeywordRoleRouter` for keyword-based role resolution
- **Observability** — `AgentLogger` with structured JSON logging
- **Memory** — `InMemoryMemoryProvider`, `PostgresMemoryProvider`
- **Commands** — `CommandRegistry` with aliases

[Unreleased]: https://github.com/fockus/swarmline/compare/v1.5.0...HEAD
[1.5.0]: https://github.com/fockus/swarmline/compare/v1.4.1...v1.5.0
[1.4.1]: https://github.com/fockus/swarmline/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/fockus/swarmline/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/fockus/swarmline/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/fockus/swarmline/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/fockus/swarmline/compare/v1.0.0...v1.1.0
[1.0.0-core]: https://github.com/fockus/swarmline/compare/v0.5.0...v1.0.0-core
[0.5.0]: https://github.com/fockus/swarmline/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/fockus/swarmline/compare/v0.3.0b1...v0.4.0
[0.3.0b1]: https://github.com/fockus/swarmline/compare/v0.2.0...v0.3.0b1
[0.2.0]: https://github.com/fockus/swarmline/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/fockus/swarmline/releases/tag/v0.1.0
