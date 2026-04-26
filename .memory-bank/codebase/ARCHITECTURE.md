# Architecture

**Generated:** `2026-04-25T10:16:27Z`
**Graph:** not-used (missing)

## Pattern
**Overall:** Clean Architecture — strict one-way dependency: Infrastructure → Application → Domain

## Layers
- **Domain** — `src/swarmline/protocols/` + `src/swarmline/domain_types.py` — ISP-split Protocols (`@runtime_checkable`, ≤5 methods each): `RuntimePort`, `AgentRuntime`, `MessageStore`, `FactStore`, `GoalStore`, `SessionStateStore`, `ToolEventStore`, `TaskQueue`, `GraphTaskBoard`, `AgentRegistry`, `HostAdapter`, etc. Zero external deps (stdlib only).
- **Application** — `src/swarmline/agent/`, `src/swarmline/bootstrap/`, `src/swarmline/orchestration/`, `src/swarmline/multi_agent/` — Agent facade, planning, subagent coordination, multi-agent graph. Imports only domain protocols.
- **Infrastructure** — `src/swarmline/runtime/`, `src/swarmline/memory/{sqlite,postgres}.py`, `src/swarmline/tools/`, `src/swarmline/observability/`, `src/swarmline/a2a/`, `src/swarmline/serve/` — concrete implementations using third-party libs.

## Data Flow
1. Entry: `Agent.query(prompt)` or `Agent.stream(prompt)` at `src/swarmline/agent/agent.py`
2. `RuntimeFactoryPort.create_runtime(config)` resolves correct runtime adapter (`src/swarmline/agent/runtime_factory_port.py`)
3. Runtime loop executes: LLM call → tool dispatch → `HookDispatcher` pre/post hooks → event yield
4. ThinRuntime: `src/swarmline/runtime/thin/runtime.py` strategy selection (react/planner/conversational) → `ToolExecutor` → `LLMClient` streaming
5. Events stream back as `RuntimeEvent` async generator; `Agent` aggregates into `Result`

## Directory Structure
```
src/swarmline/
├── protocols/         # Domain: all Protocols (memory, runtime, multi_agent, session, routing…)
├── domain_types.py    # Domain: frozen dataclasses (TurnContext, ContextPack, SkillSet)
├── agent/             # Application: Agent facade, AgentConfig, Conversation, middleware
├── bootstrap/         # Application: SwarmlineStack factory — single assembly point
├── orchestration/     # Application: planning, subagents, CodingTaskRuntime
├── multi_agent/       # Application + Infra: GraphOrchestrator, TaskQueue, AgentRegistry (SQLite/Postgres)
├── runtime/           # Infrastructure: thin/, claude_code.py, deepagents.py, openai_agents/, adapter.py, models.yaml
├── memory/            # Infrastructure: inmemory.py, sqlite.py, postgres.py, episodic, procedural
├── tools/             # Infrastructure: @tool decorator, sandbox (E2B/Docker/OpenShell), web providers
├── hooks/             # Infrastructure: HookDispatcher, HookRegistry
├── policy/            # Infra/App: DefaultToolPolicy, DefaultToolIdCodec, ToolSelector
├── context/           # Application: DefaultContextBuilder (token-aware)
├── routing/           # Application: KeywordRoleRouter, ModelSelector
├── session/           # Application/Infra: SessionManager, rehydration
├── observability/     # Infrastructure: structlog logger, OTel exporter, event bus (NATS/Redis)
├── resilience/        # Infrastructure: CircuitBreaker
├── pipeline/          # Application: budget store, quality gates, typed pipeline
└── cli/ mcp/ a2a/ serve/ daemon/  # Infrastructure entry points
```

## Entry Points
- `src/swarmline/cli/__init__.py` — `swarmline` CLI (click), `swarmline-mcp` MCP server, `swarmline-daemon`
- `src/swarmline/agent/agent.py` — library entry: `Agent(config).query(prompt)`
- `src/swarmline/bootstrap/stack.py` — `SwarmlineStack.create(...)` — single wiring factory

## Where to Add
- **New runtime adapter:** `src/swarmline/runtime/<name>.py`, implement `RuntimePort` protocol
- **New memory backend:** `src/swarmline/memory/<name>.py`, implement relevant Store protocols
- **New tool:** `src/swarmline/tools/`, use `@tool` decorator from `src/swarmline/agent/tool.py`
- **Tests:** `tests/unit/` (unit), `tests/integration/` (integration), mirror source path

## Cross-cutting
- **Logging:** `structlog.get_logger(component="<name>")` — `src/swarmline/observability/logger.py`; stdlib `logging` also used in application layer
- **Error handling:** raise domain exceptions; `Result` dataclass wraps success/failure at agent boundary (`src/swarmline/agent/result.py`)
- **Auth:** not handled in library — callers inject API keys via env vars; no global auth middleware
