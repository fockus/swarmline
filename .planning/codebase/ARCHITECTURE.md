# Architecture

**Analysis Date:** 2026-04-12

## Pattern Overview

**Overall:** Clean Architecture with explicit port/adapter layering (Hexagonal Architecture variant)

**Key Characteristics:**
- Strict dependency direction: Infrastructure → Application → Domain (never reversed)
- 18 ISP-compliant `@runtime_checkable` Protocol classes (≤5 methods each) in `src/swarmline/protocols/`
- All domain objects are frozen dataclasses — no mutation
- Async-first: all runtime, storage, and I/O APIs are async generators or coroutines
- Runtime-swappable execution loops via `AgentRuntime` Protocol — `claude_sdk`, `thin`, `deepagents`, `openai_agents`, `cli`, `headless`

---

## Layers

**Domain (Zero external dependencies):**
- Purpose: Core contracts, types, and frozen data objects. Nothing here imports from runtime/, memory/, or any external library.
- Location: `src/swarmline/domain_types.py`, `src/swarmline/types.py`, `src/swarmline/protocols/`
- Contains: `Message`, `ToolSpec`, `RuntimeEvent`, `RuntimeErrorData`, `TurnMetrics` (all frozen dataclasses); `AgentRuntime`, `MessageStore`, `FactStore`, `SessionFactory`, etc. (all `Protocol` classes)
- Depends on: stdlib only (`dataclasses`, `typing`, `uuid`, `collections.abc`)
- Used by: All layers

**Application (Business logic and orchestration):**
- Purpose: Agent facade, orchestration, session management, context assembly, multi-turn conversations.
- Location: `src/swarmline/agent/`, `src/swarmline/orchestration/`, `src/swarmline/session/`, `src/swarmline/context/`, `src/swarmline/bootstrap/`, `src/swarmline/multi_agent/`
- Contains: `Agent` (query/stream/conversation facade), `AgentConfig`, `Conversation`, `Middleware`, `SwarmlineStack` factory, `DefaultContextBuilder`, team/subagent orchestration
- Depends on: Domain protocols only; lazy imports for Infrastructure (inside functions, not module-level)
- Used by: Infrastructure adapters (via DIP), CLI, serve, MCP server

**Infrastructure (Concrete implementations, IO):**
- Purpose: Runtime adapters, memory backends, tool executors, LLM providers, persistence.
- Location: `src/swarmline/runtime/`, `src/swarmline/memory/`, `src/swarmline/tools/`, `src/swarmline/session/backends*.py`, `src/swarmline/memory_bank/`
- Contains: `ThinRuntime`, `ClaudeCodeRuntime`, `DeepAgentsRuntime`, `InMemoryMemoryProvider`, `SQLiteMemoryProvider`, `PostgresMemoryProvider`, `AnthropicAdapter`, tool sandbox implementations
- Depends on: Domain types and protocols (via DIP), external SDKs (`anthropic`, `langchain`, etc.)
- Used by: Application layer via Protocol interfaces

**Delivery (Entry points and I/O adapters):**
- Purpose: External-facing surfaces that wire application components to callers.
- Location: `src/swarmline/cli/`, `src/swarmline/serve/`, `src/swarmline/mcp/`, `src/swarmline/a2a/`
- Contains: CLI commands (`typer`/`rich`), Starlette HTTP serve app, FastMCP server, A2A protocol adapter
- Depends on: Application layer (Agent, SwarmlineStack)

---

## Data Flow

**One-shot Query Flow (Agent.query):**
1. Caller constructs `AgentConfig(system_prompt=..., runtime="thin", tools=(...))` — immutable frozen dataclass
2. `Agent.query(prompt)` applies `Middleware.before_query` chain to transform the prompt
3. `Agent._execute_stream()` calls `dispatch_runtime()` to route by `config.runtime`:
   - `"claude_sdk"` → `stream_claude_one_shot()` → `ClaudeCodeRuntime` subprocess
   - `"thin"` / `"deepagents"` → `run_portable_runtime()` → `RuntimeFactory.create()` → `AgentRuntime.run()`
4. `AgentRuntime.run()` yields `RuntimeEvent` objects (async generator): `assistant_delta`, `tool_call_started`, `tool_call_finished`, `final`, `error`
5. `collect_stream_result()` drains the generator into a `Result` frozen dataclass
6. `Middleware.after_result` chain post-processes the `Result`
7. `Result` returned to caller

**ThinRuntime Internal Flow:**
1. `ThinRuntime.run()` receives `messages: list[Message]`, `system_prompt: str`, `active_tools: list[ToolSpec]`
2. Input guardrails checked (parallel, fail-fast)
3. Input filters applied (sequential: RAG retriever, etc.)
4. `detect_mode()` selects strategy from prompt text: `"conversational"` | `"react"` | `"planner"`
5. Selected strategy iterates LLM → tool execution loop (bounded by `max_iterations`, `max_tool_calls`)
6. Cost tracker and output guardrails intercept the `final` event
7. Yields `RuntimeEvent` objects upstream

**Multi-turn Conversation Flow:**
- `Agent.conversation()` returns a `Conversation` object (accumulates `_history: list[Message]`)
- `claude_sdk` runtime: warm subprocess kept alive via `RuntimeAdapter.stream_reply(prompt)` (stateful)
- `thin`/`deepagents`: full `_history` passed in `messages` on each `AgentRuntime.run()` call (stateless runtime)
- `Conversation.say(prompt)` mutates `_history` by extending with `new_messages` from `RuntimeEvent.final`

**State Management:**
- No mutable global state — all state is passed explicitly
- `SessionState` objects managed by `InMemorySessionManager` (optionally persisted via `SessionBackend`)
- Memory stored via `MemoryProvider` Protocol implementations (InMemory / SQLite / Postgres)
- Runtime events emitted via optional `EventBus` (in-process, Redis, or NATS)

---

## Key Abstractions

**AgentRuntime Protocol (`src/swarmline/protocols/runtime.py`):**
- Purpose: Swappable execution loop. Any object implementing `run() -> AsyncIterator[RuntimeEvent]`, `cleanup()`, `cancel()`, `__aenter__/__aexit__` satisfies the Protocol.
- Implementations: `ThinRuntime` (`src/swarmline/runtime/thin/runtime.py`), `ClaudeCodeRuntime` (`src/swarmline/runtime/claude_code.py`), `DeepAgentsRuntime` (`src/swarmline/runtime/deepagents.py`)
- Pattern: async generator contract — every runtime must yield `RuntimeEvent` objects in the standard vocabulary

**RuntimeEvent (`src/swarmline/domain_types.py`):**
- Purpose: Unified streaming event type. All runtimes speak this vocabulary.
- Types: `assistant_delta`, `status`, `tool_call_started`, `tool_call_finished`, `approval_required`, `user_input_requested`, `native_notice`, `final`, `error`
- Pattern: `RuntimeEvent.final(text, new_messages, metrics)` — static factory methods used throughout

**Agent Facade (`src/swarmline/agent/agent.py`):**
- Purpose: High-level public API. Hides runtime dispatch, middleware, and event collection behind three methods.
- Interface: `query(prompt, *, messages) -> Result`, `stream(prompt) -> AsyncIterator`, `conversation() -> Conversation`
- Pattern: Decorator/middleware chain (`Middleware.before_query` → execute → `Middleware.after_result`)

**SwarmlineStack (`src/swarmline/bootstrap/stack.py`):**
- Purpose: Single assembly point — factories all library components (skill registry, context builder, role router, tool policy, runtime factory) from config paths. Application calls `SwarmlineStack.create(prompts_dir=..., skills_dir=...)`.
- Pattern: Factory method + dependency injection. Returns a `@dataclass` with wired components, no global state.

**Memory Protocols (ISP-split, `src/swarmline/protocols/memory.py`):**
- `MessageStore` (4 methods): save/get/count/delete messages
- `FactStore` (2 methods): upsert_fact / get_facts
- `SummaryStore` (2 methods): save_summary / get_summary
- `GoalStore` (2 methods): save_goal / get_active_goal
- `SessionStateStore` (2 methods): save/get session state
- `UserStore` (2 methods): ensure_user / get_user_profile
- `PhaseStore` (2 methods): save/get phase state
- `ToolEventStore` (1 method): save_tool_event
- All implementations: `InMemoryMemoryProvider` (`src/swarmline/memory/inmemory.py`), `SQLiteMemoryProvider` (`src/swarmline/memory/sqlite.py`), `PostgresMemoryProvider` (`src/swarmline/memory/postgres.py`)

**HostAdapter (`src/swarmline/protocols/host_adapter.py`):**
- Purpose: Universal facade for spawning and managing AI agents (for multi-agent orchestration).
- Interface: `spawn_agent(role, goal, ...) -> AgentHandle`, `send_task(handle, task) -> str`, `stop_agent(handle)`, `get_status(handle)`

**DefaultGraphOrchestrator (`src/swarmline/multi_agent/graph_orchestrator.py`):**
- Purpose: Hierarchical multi-agent execution engine. `start(goal)` → root agent decomposes → delegates subtasks → parallel bounded execution via `GraphTaskBoard`.
- Pattern: `AgentRunner` callback (injected at construction) + `GraphOrchestrator` Protocol

---

## Entry Points

**Library API:**
- Location: `src/swarmline/__init__.py`
- Exports: `Agent`, `AgentConfig`, `SwarmlineStack`, all Protocol classes, `RuntimeEvent`, `Message`, `ToolSpec`, `tool` decorator
- Usage: `from swarmline import Agent, AgentConfig`

**CLI:**
- Location: `src/swarmline/cli/__main__.py`, `src/swarmline/cli/_app.py`
- Commands: agent query/stream, memory ops, team management, plan management, MCP server start, serve start
- Triggers: `python -m swarmline.cli` or `swarmline` entry point

**MCP Server:**
- Location: `src/swarmline/mcp/_server.py`, `src/swarmline/mcp/__main__.py`
- Triggers: `swarmline-mcp` or `python -m swarmline.mcp`
- Modes: `headless` (memory/plans/team, no LLM), `full` (+ agent create/query), `auto` (detect API keys)
- Exposes: memory tools, plan tools, team tools, agent tools, code exec tools

**HTTP API (serve):**
- Location: `src/swarmline/serve/app.py`
- Framework: Starlette ASGI
- Auth: Bearer token middleware (exempt: `/v1/health`, `/v1/info`)

**Daemon:**
- Location: `src/swarmline/daemon/runner.py`
- Triggers: `src/swarmline/daemon/cli_entry.py`
- Purpose: Long-running background process manager with scheduler, PID file, health HTTP endpoint

**A2A Protocol:**
- Location: `src/swarmline/a2a/adapter.py`, `src/swarmline/a2a/server.py`
- Purpose: Wraps any `Agent` as an A2A-compatible service (Google A2A protocol)

---

## Error Handling

**Strategy:** Typed errors propagated via `RuntimeEvent(type="error", data=RuntimeErrorData(...))`

**RuntimeErrorData kinds:**
- `runtime_crash` — fatal, non-recoverable
- `bad_model_output` — invalid LLM JSON, retryable
- `loop_limit` — `max_iterations` exceeded
- `budget_exceeded` — `max_tool_calls` or cost budget exceeded
- `mcp_timeout` — MCP call timeout
- `tool_error` — tool execution error
- `dependency_missing` — optional package not installed
- `capability_unsupported` — runtime missing required feature
- `cancelled` — cooperative cancellation via `CancellationToken`
- `guardrail_tripwire` — input/output guardrail failed
- `retry` — LLM call retry in progress

**Infrastructure errors** (network, DB, SDK): caught at the runtime layer, converted to `RuntimeEvent.error(RuntimeErrorData(...))` before yielding upstream. Application never catches raw exceptions from infrastructure.

**Capability errors at startup:** `RuntimeFactory.validate_agent_config(config)` raises `ValueError` on unknown runtime names or missing capabilities — fail-fast before any LLM call.

---

## Cross-Cutting Concerns

**Logging:**
- Framework: `structlog` (all infrastructure and delivery layers)
- `src/swarmline/observability/logger.py` — structured log setup
- Security decisions logged via `log_security_decision()` in `src/swarmline/observability/security.py`

**Observability:**
- `EventBus` (`src/swarmline/observability/event_bus.py`) — in-process pub-sub for tool call events, LLM call start/end
- Redis backend: `src/swarmline/observability/event_bus_redis.py`
- NATS backend: `src/swarmline/observability/event_bus_nats.py`
- OpenTelemetry exporter: `src/swarmline/observability/otel_exporter.py`
- Span tracer: `src/swarmline/observability/tracer.py`
- Activity log (append-only audit): `src/swarmline/observability/activity_log.py`

**Validation:**
- `AgentConfig.__post_init__`: validates non-empty `system_prompt`
- `RuntimeConfig.__post_init__`: validates runtime name, feature mode, required capabilities against registry
- `RuntimeFactory.validate_agent_config()`: capability negotiation gate at bootstrap
- All domain types: `frozen=True` prevents mutation after construction

**Authentication:**
- HTTP serve: Bearer token via `_BearerAuthMiddleware` (`src/swarmline/serve/app.py`)
- Tool policy: default-deny via `DefaultToolPolicy` (`src/swarmline/policy/tool_policy.py`), whitelist with `allowed_system_tools`

**Resilience:**
- Circuit breaker: `src/swarmline/resilience/circuit_breaker.py`
- Retry policy: pluggable `retry_policy` field in `RuntimeConfig` (e.g., `ExponentialBackoff`)
- Cooperative cancellation: `CancellationToken` checked at iteration boundaries in `ThinRuntime`
- Cost budget: `CostBudget` + `CostTracker` enforce `max_budget_usd` with pre- and post-call checks

**Human-in-the-Loop (HITL):**
- `ApprovalGate` (`src/swarmline/hitl/gate.py`) — policy-driven approval requests
- `approval_required` `RuntimeEvent` type surfaces to the streaming caller
- Policies: `src/swarmline/hitl/policies.py`

---

*Architecture analysis: 2026-04-12*
