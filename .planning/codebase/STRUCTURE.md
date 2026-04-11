# Codebase Structure

**Analysis Date:** 2026-04-12

## Directory Layout

```
swarmline/
├── src/swarmline/              # Main package
│   ├── __init__.py             # Public API surface (re-exports everything)
│   ├── domain_types.py         # Pure domain types (Message, ToolSpec, RuntimeEvent, etc.)
│   ├── types.py                # Shared types (TurnContext, ContextPack, SkillSet)
│   ├── guardrails.py           # Input/output guardrail base classes
│   ├── input_filters.py        # Pre-LLM input filter base classes
│   ├── network_safety.py       # Network safety helpers
│   ├── path_safety.py          # Path safety helpers
│   ├── rag.py                  # RAG retriever base (injected into RuntimeConfig)
│   ├── retry.py                # Retry policy types
│   │
│   ├── protocols/              # ISP-compliant Protocol interfaces (Domain layer)
│   │   ├── __init__.py         # Re-exports all protocols
│   │   ├── memory.py           # MessageStore, FactStore, SummaryStore, GoalStore, etc.
│   │   ├── runtime.py          # AgentRuntime, RuntimePort (canonical + deprecated)
│   │   ├── session.py          # SessionFactory, SessionLifecycle, SessionManager, SessionRehydrator
│   │   ├── routing.py          # RoleRouter, ContextBuilder, ModelSelector, RoleSkillsProvider
│   │   ├── tools.py            # LocalToolResolver, ToolIdCodec
│   │   ├── multi_agent.py      # AgentTool, TaskQueue, AgentRegistry
│   │   ├── host_adapter.py     # HostAdapter, AgentHandle, AgentAuthority
│   │   ├── graph_orchestrator.py  # GraphOrchestrator, PersistentOrchestrator
│   │   ├── graph_task.py       # GraphTaskBoard, GraphTaskScheduler, GraphTaskBlocker
│   │   ├── graph_comm.py       # Graph communication protocols
│   │   └── agent_graph.py      # Agent graph store protocols
│   │
│   ├── agent/                  # Application layer — Agent facade
│   │   ├── __init__.py
│   │   ├── agent.py            # Agent class (query/stream/conversation)
│   │   ├── config.py           # AgentConfig frozen dataclass
│   │   ├── conversation.py     # Conversation (multi-turn)
│   │   ├── middleware.py       # Middleware base + CostTracker, SecurityGuard, ToolOutputCompressor
│   │   ├── result.py           # Result frozen dataclass
│   │   ├── tool.py             # @tool decorator + ToolDefinition
│   │   ├── structured.py       # Structured output helpers + StructuredOutputError
│   │   ├── runtime_dispatch.py # dispatch_runtime, run_portable_runtime, stream_claude_one_shot
│   │   ├── runtime_factory_port.py  # RuntimeFactoryPort protocol (application-layer seam)
│   │   └── runtime_wiring.py   # RuntimeAdapter wiring helpers
│   │
│   ├── bootstrap/              # Application layer — assembly
│   │   ├── __init__.py
│   │   ├── stack.py            # SwarmlineStack factory (SwarmlineStack.create())
│   │   └── capabilities.py     # collect_capability_tools() — merges optional capability tools
│   │
│   ├── runtime/                # Infrastructure layer — runtime adapters
│   │   ├── __init__.py
│   │   ├── base.py             # AgentRuntime re-export (backward compat)
│   │   ├── factory.py          # RuntimeFactory (creates runtime by name)
│   │   ├── registry.py         # RuntimeRegistry (extensible, thread-safe, entry points)
│   │   ├── capabilities.py     # RuntimeCapabilities, CapabilityRequirements, VALID_RUNTIME_NAMES
│   │   ├── types.py            # RuntimeConfig, resolve_model_name (re-exports domain types)
│   │   ├── cancellation.py     # CancellationToken
│   │   ├── cost.py             # CostTracker, CostBudget, load_pricing()
│   │   ├── model_registry.py   # ModelRegistry (loads models.yaml)
│   │   ├── model_policy.py     # ModelPolicy (escalation)
│   │   ├── models.yaml         # Model aliases (sonnet → claude-sonnet-4-..., gemini, gpt-4o, etc.)
│   │   ├── provider_resolver.py # Multi-provider resolution (Anthropic/OpenAI/Google/DeepSeek)
│   │   ├── claude_code.py      # ClaudeCodeRuntime (Claude Agent SDK adapter)
│   │   ├── deepagents.py       # DeepAgentsRuntime (LangChain/LangGraph adapter)
│   │   ├── sdk_query.py        # SDK one-shot query helpers
│   │   ├── sdk_tools.py        # MCP tool builder for SDK
│   │   ├── options_builder.py  # ClaudeAgentOptions builder
│   │   ├── portable_memory.py  # Portable memory injection
│   │   ├── structured_output.py # Structured output instruction injection
│   │   ├── ports/              # Runtime port adapters
│   │   │   ├── base.py         # BaseRuntimePort
│   │   │   ├── thin.py         # ThinRuntime port adapter
│   │   │   └── deepagents.py   # DeepAgents port adapter
│   │   └── thin/               # ThinRuntime — built-in lightweight loop
│   │       ├── __init__.py
│   │       ├── runtime.py      # ThinRuntime (main class)
│   │       ├── strategies.py   # run_conversational, run_react, run_planner
│   │       ├── conversational.py # Conversational strategy (single LLM call)
│   │       ├── react_strategy.py # ReAct loop (LLM → tool_call | final)
│   │       ├── planner_strategy.py # Planner (decompose → execute plan)
│   │       ├── modes.py        # detect_mode() — conversational/react/planner
│   │       ├── executor.py     # ToolExecutor (local + MCP tool dispatch)
│   │       ├── llm_client.py   # LLM call wrappers (buffered, streaming)
│   │       ├── llm_providers.py # LlmAdapter: AnthropicAdapter, OpenAIAdapter, GoogleAdapter, etc.
│   │       ├── mcp_client.py   # MCP client for tool calls
│   │       ├── parsers.py      # Response envelope parsing
│   │       ├── finalization.py # Final event construction + validation
│   │       ├── helpers.py      # Message format conversion, metrics
│   │       ├── prompts.py      # System prompt builders (react, planner)
│   │       ├── schemas.py      # JSON Schema helpers
│   │       ├── errors.py       # ThinLlmError, dependency_missing_error
│   │       ├── runtime_support.py # guardrails, cancellation, event bus, retriever wrappers
│   │       ├── builtin_tools.py # Built-in tool specs for ThinRuntime
│   │       ├── stream_parser.py # SSE/stream response parsing
│   │       └── json_utils.py   # JSON extraction from LLM output
│   │
│   ├── memory/                 # Infrastructure layer — memory backends
│   │   ├── __init__.py
│   │   ├── types.py            # MemoryMessage, GoalState, PhaseState, ToolEvent, UserProfile
│   │   ├── inmemory.py         # InMemoryMemoryProvider (all protocols, in-process)
│   │   ├── sqlite.py           # SQLiteMemoryProvider (SQLAlchemy + aiosqlite)
│   │   ├── postgres.py         # PostgresMemoryProvider (SQLAlchemy + asyncpg)
│   │   ├── provider.py         # MemoryProvider composite + factory
│   │   ├── _shared.py          # Shared SQL helpers (build_goal_state, json utils)
│   │   ├── consolidation.py    # Memory consolidation logic
│   │   ├── summarizer.py       # SummaryGenerator interface
│   │   ├── llm_summarizer.py   # LLM-based rolling summary generator
│   │   ├── episodic.py         # Episodic memory (InMemory)
│   │   ├── episodic_sqlite.py  # Episodic memory (SQLite)
│   │   ├── episodic_postgres.py # Episodic memory (Postgres)
│   │   ├── episodic_types.py   # Episodic memory types
│   │   ├── procedural.py       # Procedural memory (InMemory)
│   │   ├── procedural_sqlite.py # Procedural memory (SQLite)
│   │   ├── procedural_postgres.py # Procedural memory (Postgres)
│   │   └── procedural_types.py # Procedural memory types
│   │
│   ├── memory_bank/            # Memory Bank feature — filesystem + DB
│   │   ├── __init__.py
│   │   ├── protocols.py        # MemoryBankProvider protocol
│   │   ├── types.py            # MemoryBankEntry types
│   │   ├── schema.py           # DB schema (SQLAlchemy)
│   │   ├── fs_provider.py      # Filesystem-based memory bank
│   │   ├── db_provider.py      # DB-backed memory bank
│   │   ├── tiered.py           # Tiered memory bank (FS + DB)
│   │   ├── tools.py            # Memory bank tool functions
│   │   ├── knowledge_*.py      # Knowledge base: store, search, types, protocols, etc.
│   │   └── frontmatter.py      # YAML frontmatter parsing for knowledge docs
│   │
│   ├── orchestration/          # Application layer — team/subagent orchestration
│   │   ├── __init__.py
│   │   ├── base_team.py        # BaseTeamOrchestrator ABC
│   │   ├── claude_subagent.py  # ClaudeSubagent (claude_sdk runtime)
│   │   ├── claude_team.py      # ClaudeTeamOrchestrator
│   │   ├── thin_subagent.py    # ThinSubagent (thin runtime)
│   │   ├── thin_team.py        # ThinTeamOrchestrator
│   │   ├── deepagents_subagent.py # DeepAgentsSubagent
│   │   ├── deepagents_team.py  # DeepAgentsTeamOrchestrator
│   │   ├── deepagents_planner.py # DeepAgents-based planner
│   │   ├── team_manager.py     # TeamManager — lifecycle and dispatch
│   │   ├── manager.py          # Orchestration manager
│   │   ├── message_bus.py      # Internal message bus for teams
│   │   ├── message_tools.py    # Message tools for agents
│   │   ├── plan_store.py       # Plan storage
│   │   ├── plan_tools.py       # Plan manipulation tools
│   │   ├── code_verifier.py    # Code verification (runs tests, lint)
│   │   ├── tdd_code_verifier.py # TDD-specific code verifier
│   │   ├── code_workflow_engine.py # Code workflow state machine
│   │   ├── generic_workflow_engine.py # Generic workflow engine
│   │   ├── workflow_executor.py # Workflow executor
│   │   ├── workflow_graph.py    # Workflow DAG
│   │   ├── workflow_pipeline.py # Pipeline workflow
│   │   ├── workflow_langgraph.py # LangGraph workflow adapter
│   │   ├── dod_state_machine.py # DoD (Definition of Done) state machine
│   │   ├── protocols.py        # Orchestration-specific protocols
│   │   ├── subagent_protocol.py # SubagentOrchestrator protocol
│   │   ├── team_protocol.py    # TeamOrchestrator protocol
│   │   ├── subagent_types.py   # SubagentStatus, SubagentConfig types
│   │   ├── team_types.py       # TeamConfig, TeamState, TeamMessage types
│   │   ├── types.py            # Shared orchestration types
│   │   ├── verification_types.py # Verification result types
│   │   ├── verifier_port.py    # Verifier protocol
│   │   ├── runtime_helpers.py  # Runtime helper utilities
│   │   └── coding_standards.py # Coding standards enforcement
│   │
│   ├── multi_agent/            # Infrastructure layer — graph-based multi-agent
│   │   ├── __init__.py
│   │   ├── types.py            # Core multi-agent types
│   │   ├── registry_types.py   # AgentRecord, AgentFilter, AgentStatus
│   │   ├── task_types.py       # TaskItem, TaskFilter, TaskStatus
│   │   ├── agent_registry.py   # InMemoryAgentRegistry
│   │   ├── agent_registry_sqlite.py # SQLiteAgentRegistry
│   │   ├── agent_registry_postgres.py # PostgresAgentRegistry
│   │   ├── task_queue.py       # InMemoryTaskQueue
│   │   ├── task_queue_postgres.py # PostgresTaskQueue
│   │   ├── agent_tool.py       # AgentTool implementation (agent as tool)
│   │   ├── graph_orchestrator.py # DefaultGraphOrchestrator
│   │   ├── graph_orchestrator_state.py # GraphRunStore (run state tracking)
│   │   ├── graph_orchestrator_types.py # AgentRunState, DelegationRequest, OrchestratorRunStatus
│   │   ├── graph_context.py    # GraphContextBuilder
│   │   ├── graph_execution_context.py # AgentExecutionContext (passed to runner callback)
│   │   ├── graph_runtime_config.py # GraphRuntimeResolver
│   │   ├── graph_task_types.py # GraphTaskItem, TaskComment
│   │   ├── graph_task_board.py # InMemoryGraphTaskBoard
│   │   ├── graph_task_board_sqlite.py # SQLiteGraphTaskBoard
│   │   ├── graph_task_board_postgres.py # PostgresGraphTaskBoard
│   │   ├── graph_task_board_shared.py # Shared task board SQL helpers
│   │   ├── graph_store.py      # AgentGraphStore (InMemory)
│   │   ├── graph_store_sqlite.py # SQLiteAgentGraphStore
│   │   ├── graph_store_postgres.py # PostgresAgentGraphStore
│   │   ├── graph_types.py      # AgentNode, GraphEdge, LifecycleMode
│   │   ├── graph_builder.py    # AgentGraph builder helper
│   │   ├── graph_comm_types.py # Communication types
│   │   ├── graph_communication.py # InMemory graph communication
│   │   ├── graph_communication_redis.py # Redis graph communication
│   │   ├── graph_communication_nats.py # NATS graph communication
│   │   ├── graph_communication_postgres.py # Postgres graph communication
│   │   ├── graph_communication_sqlite.py # SQLite graph communication
│   │   ├── graph_governance.py # Agent governance rules
│   │   ├── graph_context.py    # Graph context assembly
│   │   ├── persistent_graph.py # PersistentAgentGraph (full orchestrator + graph)
│   │   ├── shared_agents.py    # Shared agent pool
│   │   ├── workspace.py        # Shared workspace for multi-agent collaboration
│   │   ├── workspace_types.py  # Workspace types
│   │   ├── worktree_orchestrator.py # Git worktree-based orchestration
│   │   ├── worktree_strategy.py # Worktree execution strategies
│   │   ├── execution_context.py # Agent execution context
│   │   └── goal_queue.py       # Persistent goal queue
│   │
│   ├── session/                # Application layer — session lifecycle
│   │   ├── __init__.py
│   │   ├── manager.py          # InMemorySessionManager (async, TTL, snapshot)
│   │   ├── backends.py         # SessionBackend protocol + SQLite impl
│   │   ├── backends_postgres.py # Postgres SessionBackend
│   │   ├── rehydrator.py       # SessionRehydrator (restore session from memory)
│   │   ├── runtime_bridge.py   # run_runtime_turn, stream_runtime_reply
│   │   ├── snapshot_store.py   # Session snapshot serialization/deserialization
│   │   ├── task_session_store.py # Task session store
│   │   ├── task_session_types.py # Task session types
│   │   └── types.py            # SessionKey, SessionState
│   │
│   ├── context/                # Application layer — context assembly
│   │   ├── __init__.py
│   │   ├── builder.py          # DefaultContextBuilder (layered P0→P5 prompt packs)
│   │   └── budget.py           # ContextBudget, estimate_tokens, truncate_to_budget
│   │
│   ├── routing/                # Application layer — role routing
│   │   ├── __init__.py
│   │   └── role_router.py      # KeywordRoleRouter
│   │
│   ├── config/                 # Application layer — config loaders
│   │   ├── __init__.py
│   │   ├── role_router.py      # RoleRouterConfig, load_role_router_config()
│   │   └── role_skills.py      # YamlRoleSkillsLoader
│   │
│   ├── policy/                 # Application layer — tool policy
│   │   ├── __init__.py
│   │   ├── tool_policy.py      # DefaultToolPolicy (default-deny allowlist)
│   │   ├── tool_id_codec.py    # DefaultToolIdCodec (encode/decode tool IDs)
│   │   ├── tool_selector.py    # ToolSelector, ToolBudgetConfig
│   │   └── tool_budget.py      # Tool budget enforcement
│   │
│   ├── skills/                 # Infrastructure layer — MCP skill management
│   │   ├── __init__.py
│   │   ├── registry.py         # SkillRegistry
│   │   ├── loader.py           # YamlSkillLoader
│   │   └── types.py            # LoadedSkill, SkillMetadata
│   │
│   ├── tools/                  # Infrastructure layer — builtin tool implementations
│   │   ├── __init__.py
│   │   ├── builtin.py          # Builtin tool definitions
│   │   ├── protocols.py        # Tool provider protocols
│   │   ├── types.py            # Tool types
│   │   ├── thinking.py         # Thinking tool
│   │   ├── sandbox_local.py    # Local process sandbox
│   │   ├── sandbox_docker.py   # Docker sandbox
│   │   ├── sandbox_e2b.py      # E2B cloud sandbox
│   │   ├── sandbox_openshell.py # OpenShell sandbox
│   │   ├── web_httpx.py        # HTTP web tool (httpx-based)
│   │   ├── web_protocols.py    # Web provider protocol
│   │   └── web_providers/      # Web search provider implementations
│   │       ├── brave.py        # Brave Search
│   │       ├── tavily.py       # Tavily
│   │       ├── duckduckgo.py   # DuckDuckGo
│   │       ├── jina.py         # Jina reader
│   │       ├── searxng.py      # SearXNG
│   │       ├── crawl4ai.py     # Crawl4AI
│   │       └── factory.py      # WebProviderFactory
│   │
│   ├── hooks/                  # Application layer — lifecycle hooks
│   │   ├── __init__.py
│   │   ├── registry.py         # HookRegistry (PreToolUse, PostToolUse, Stop, UserPromptSubmit)
│   │   └── sdk_bridge.py       # Bridge HookRegistry → Claude Agent SDK hooks
│   │
│   ├── observability/          # Infrastructure layer — logging, events, tracing
│   │   ├── __init__.py
│   │   ├── logger.py           # structlog setup
│   │   ├── security.py         # log_security_decision()
│   │   ├── event_bus.py        # InMemoryEventBus (async pub-sub)
│   │   ├── event_bus_redis.py  # RedisEventBus
│   │   ├── event_bus_nats.py   # NATSEventBus
│   │   ├── namespaced_event_bus.py # NamespacedEventBus (per-session isolation)
│   │   ├── otel_exporter.py    # OpenTelemetry span exporter
│   │   ├── tracer.py           # Tracer (span-based tracing)
│   │   ├── activity_log.py     # Append-only activity log
│   │   ├── activity_types.py   # ActivityEntry types
│   │   └── activity_subscriber.py # ActivityLog subscriber
│   │
│   ├── resilience/             # Infrastructure layer — fault tolerance
│   │   ├── __init__.py
│   │   └── circuit_breaker.py  # CircuitBreaker
│   │
│   ├── hitl/                   # Application layer — human-in-the-loop
│   │   ├── __init__.py
│   │   ├── gate.py             # ApprovalGate, ApprovalDeniedError
│   │   ├── policies.py         # ToolApprovalPolicy, AlwaysApprovePolicy
│   │   └── types.py            # ApprovalRequest, ApprovalResponse
│   │
│   ├── eval/                   # Application layer — evaluation framework
│   │   ├── __init__.py
│   │   ├── runner.py           # EvalRunner (runs cases through agent.query())
│   │   ├── scorers.py          # ExactMatch, Contains, LLMJudge scorers
│   │   ├── compare.py          # EvalComparator (A/B comparison)
│   │   ├── history.py          # Eval history tracking
│   │   ├── reporters.py        # Report formatters
│   │   └── types.py            # EvalCase, EvalResult, EvalReport, ScorerResult
│   │
│   ├── daemon/                 # Infrastructure layer — background process management
│   │   ├── __init__.py
│   │   ├── runner.py           # DaemonRunner (signal handling, scheduler, health)
│   │   ├── scheduler.py        # Scheduler (periodic tasks)
│   │   ├── health.py           # HealthServer (HTTP health endpoint)
│   │   ├── pid.py              # PidFile
│   │   ├── protocols.py        # ProcessLock, RunnableScheduler, HealthEndpoint
│   │   ├── types.py            # DaemonConfig, DaemonStatus, DaemonState
│   │   ├── routine_bridge.py   # Bridge daemon routines to agent execution
│   │   ├── routine_types.py    # Routine types
│   │   └── cli_entry.py        # CLI entry point for daemon
│   │
│   ├── todo/                   # Infrastructure layer — task/todo management
│   │   ├── __init__.py
│   │   ├── protocols.py        # TodoProvider protocol
│   │   ├── types.py            # TodoItem types
│   │   ├── schema.py           # DB schema
│   │   ├── tools.py            # Todo tool functions
│   │   ├── inmemory_provider.py # InMemory todo provider
│   │   ├── fs_provider.py      # Filesystem todo provider
│   │   └── db_provider.py      # DB-backed todo provider
│   │
│   ├── commands/               # Application layer — command pattern
│   │   ├── __init__.py
│   │   ├── registry.py         # CommandRegistry
│   │   └── loader.py           # Dynamic command loader
│   │
│   ├── ui/                     # Infrastructure layer — UI projection
│   │   ├── __init__.py
│   │   └── projection.py       # UI state projection from events
│   │
│   ├── a2a/                    # Delivery layer — Agent-to-Agent (A2A) protocol
│   │   ├── __init__.py
│   │   ├── adapter.py          # SwarmlineA2AAdapter (wraps Agent as A2A service)
│   │   ├── server.py           # A2A HTTP server
│   │   ├── client.py           # A2A client
│   │   └── types.py            # A2A types (AgentCard, Task, Message, etc.)
│   │
│   ├── mcp/                    # Delivery layer — MCP server
│   │   ├── __init__.py
│   │   ├── __main__.py         # Entry point: python -m swarmline.mcp
│   │   ├── _server.py          # FastMCP server factory
│   │   ├── _session.py         # StatefulSession for MCP
│   │   ├── _tools_agent.py     # agent_create, agent_list, agent_query tools
│   │   ├── _tools_code.py      # exec_code tool
│   │   ├── _tools_memory.py    # memory_* tools
│   │   ├── _tools_plans.py     # plan_* tools
│   │   ├── _tools_team.py      # team_* tools
│   │   └── _types.py           # MCP tool type helpers
│   │
│   ├── serve/                  # Delivery layer — HTTP API
│   │   ├── __init__.py
│   │   └── app.py              # Starlette ASGI app factory
│   │
│   └── cli/                    # Delivery layer — CLI
│       ├── __init__.py
│       ├── __main__.py         # Entry point: python -m swarmline.cli
│       ├── _app.py             # Typer app root
│       ├── _commands_agent.py  # agent subcommands
│       ├── _commands_mcp.py    # mcp subcommands
│       ├── _commands_memory.py # memory subcommands
│       ├── _commands_plan.py   # plan subcommands
│       ├── _commands_run.py    # run subcommands
│       ├── _commands_team.py   # team subcommands
│       ├── _output.py          # Rich console output helpers
│       └── init_cmd.py         # swarmline init command
│
├── tests/                      # Test suite (mirrors src layout)
│   ├── unit/                   # Unit tests
│   ├── integration/            # Integration tests (real components, mock external)
│   ├── e2e/                    # End-to-end tests
│   └── security/               # Security-focused tests
│
├── pyproject.toml              # Package metadata, dependencies, tool config
├── RULES.md                    # Project-specific coding rules
└── AGENTS.md                   # Agent instructions
```

---

## Directory Purposes

**`src/swarmline/protocols/`:**
- Purpose: Canonical Protocol (port) definitions for the Domain layer
- Contains: All `@runtime_checkable` `Protocol` classes, split by concern into separate files
- Key files: `runtime.py` (AgentRuntime), `memory.py` (8 memory protocols), `session.py` (session protocols), `host_adapter.py` (HostAdapter)
- Rule: Zero imports from runtime/, memory/, or any infrastructure. Only imports from `swarmline.domain_types`, `swarmline.types`, `swarmline.memory.types`, stdlib

**`src/swarmline/agent/`:**
- Purpose: High-level Agent facade used by all callers
- Key files: `agent.py` (main class), `config.py` (AgentConfig), `conversation.py` (multi-turn), `middleware.py` (chain), `tool.py` (@tool decorator)

**`src/swarmline/runtime/`:**
- Purpose: Runtime adapters — everything that talks to an LLM or subprocess
- Key files: `factory.py` (RuntimeFactory.create()), `registry.py` (extensible RuntimeRegistry), `thin/runtime.py` (built-in loop), `claude_code.py` (SDK adapter)

**`src/swarmline/memory/`:**
- Purpose: Persistent memory (messages, facts, summaries, goals, session state)
- Key files: `inmemory.py` (dev/test), `sqlite.py` (single-host), `postgres.py` (production)

**`src/swarmline/multi_agent/`:**
- Purpose: Graph-based hierarchical multi-agent execution infrastructure
- Key files: `graph_orchestrator.py` (DefaultGraphOrchestrator), `graph_task_board.py` (task management), `agent_registry.py` (agent registry)

**`src/swarmline/orchestration/`:**
- Purpose: Higher-level team/subagent abstractions, workflows, code verification
- Key files: `base_team.py` (BaseTeamOrchestrator ABC), `claude_team.py`, `thin_team.py` (runtime-specific teams)

**`src/swarmline/bootstrap/`:**
- Purpose: Single assembly point — `SwarmlineStack.create()` wires all components
- Key files: `stack.py` (SwarmlineStack), `capabilities.py` (capability tool collection)

---

## Key File Locations

**Entry Points:**
- `src/swarmline/__init__.py`: Public library API (all public re-exports)
- `src/swarmline/cli/__main__.py`: CLI entry point (`python -m swarmline.cli`)
- `src/swarmline/mcp/__main__.py`: MCP server entry point (`python -m swarmline.mcp`)
- `src/swarmline/serve/app.py`: HTTP API (Starlette factory)

**Configuration:**
- `src/swarmline/agent/config.py`: `AgentConfig` — primary configuration object
- `src/swarmline/runtime/types.py`: `RuntimeConfig` — runtime-level configuration
- `src/swarmline/runtime/models.yaml`: Model alias registry (sonnet, opus, gemini, gpt-4o, etc.)
- `src/swarmline/runtime/capabilities.py`: `VALID_RUNTIME_NAMES`, `VALID_FEATURE_MODES`

**Core Types:**
- `src/swarmline/domain_types.py`: `Message`, `ToolSpec`, `RuntimeEvent`, `RuntimeErrorData`, `TurnMetrics`
- `src/swarmline/types.py`: `TurnContext`, `ContextPack`, `SkillSet`
- `src/swarmline/agent/result.py`: `Result` — what callers receive back

**All Protocols:**
- `src/swarmline/protocols/__init__.py`: Re-exports all 18+ protocol classes

**Bootstrap:**
- `src/swarmline/bootstrap/stack.py`: `SwarmlineStack.create()` — start here for wiring

**Testing:**
- `tests/unit/` — fast, isolated unit tests
- `tests/integration/` — real DB/runtime components, mock external LLM APIs
- `tests/e2e/` — full end-to-end (requires actual API keys, marked `live`)
- `tests/security/` — security-specific tests

---

## Naming Conventions

**Files:**
- `snake_case.py` for all Python files
- Prefix `_` for internal/private modules within a package (e.g., `_app.py`, `_server.py`, `_commands_agent.py`)
- Suffix `_types.py` for type-only modules (e.g., `graph_task_types.py`, `subagent_types.py`)
- Suffix `_postgres.py` / `_sqlite.py` for backend-specific implementations (e.g., `backends_postgres.py`, `task_queue_postgres.py`)
- Suffix `_protocol.py` for subpackage protocol files (e.g., `subagent_protocol.py`, `team_protocol.py`)

**Classes:**
- `PascalCase` for all classes
- Protocol classes named after the port they represent: `MessageStore`, `AgentRuntime`, `HostAdapter`
- Concrete implementations named `{Backend}{Concept}`: `SQLiteMemoryProvider`, `InMemoryAgentRegistry`, `PostgresTaskQueue`
- Runtime names: `ThinRuntime`, `ClaudeCodeRuntime`, `DeepAgentsRuntime`

**Directories:**
- `snake_case` for all package directories
- Responsibility grouping: `protocols/`, `runtime/`, `memory/`, `agent/`, `multi_agent/`, `orchestration/`

---

## Where to Add New Code

**New runtime adapter (e.g., OpenAI-native runtime):**
- Implementation: `src/swarmline/runtime/openai_native.py` — implement `AgentRuntime` Protocol
- Register: `src/swarmline/runtime/registry.py` — add to `_register_builtins()`
- Capabilities: `src/swarmline/runtime/capabilities.py` — define `RuntimeCapabilities` for it
- Tests: `tests/unit/runtime/test_openai_native.py` + `tests/integration/runtime/`

**New memory protocol + backend:**
- Protocol: `src/swarmline/protocols/memory.py` — add `@runtime_checkable class NewStore(Protocol)`
- InMemory impl: `src/swarmline/memory/inmemory.py` — add methods to `InMemoryMemoryProvider`
- SQLite impl: `src/swarmline/memory/sqlite.py` — add SQL methods
- Postgres impl: `src/swarmline/memory/postgres.py` — add async SQL methods
- Export: `src/swarmline/protocols/__init__.py` and `src/swarmline/__init__.py`
- Tests: `tests/unit/memory/` + `tests/integration/memory/`

**New capability tool (e.g., new sandbox):**
- Implementation: `src/swarmline/tools/sandbox_newprovider.py`
- Protocol: `src/swarmline/tools/protocols.py` if new contract needed
- Wire into: `src/swarmline/bootstrap/capabilities.py` — `collect_capability_tools()`
- Factory: `src/swarmline/tools/` — follow existing sandbox pattern

**New orchestration workflow:**
- Types: `src/swarmline/orchestration/workflow_types.py` (or extend `types.py`)
- Implementation: `src/swarmline/orchestration/new_workflow.py`
- Register: `src/swarmline/orchestration/__init__.py`

**New middleware:**
- Implementation: `src/swarmline/agent/middleware.py` — extend `Middleware` base class
- Export: `src/swarmline/agent/__init__.py`

**New MCP tool group:**
- Implementation: `src/swarmline/mcp/_tools_newgroup.py`
- Register: `src/swarmline/mcp/_server.py` — add to `create_server()`

**New Protocol:**
- File: `src/swarmline/protocols/newconcept.py` — `@runtime_checkable class NewPort(Protocol)` with ≤5 methods
- Export: `src/swarmline/protocols/__init__.py` and `src/swarmline/__init__.py`

**Shared utilities:**
- Domain utilities (no external deps): `src/swarmline/domain_types.py` or a new file in `src/swarmline/`
- Infrastructure helpers: within the relevant subpackage (e.g., `src/swarmline/memory/_shared.py`)

---

## Special Directories

**`tests/`:**
- Purpose: Test suite mirroring source structure
- Generated: No
- Committed: Yes

**`src/swarmline/runtime/models.yaml`:**
- Purpose: Model alias registry loaded at runtime
- Generated: No (manually maintained)
- Committed: Yes

**`.planning/`:**
- Purpose: GSD planning documents (architecture, roadmap, phases)
- Generated: By GSD tooling
- Committed: Yes (in private repo)

**`.memory-bank/`:**
- Purpose: Session memory bank (STATUS, checklist, plan, notes, progress)
- Generated: By Claude Code Memory Bank skill
- Committed: Yes (in private repo, filtered from public)

---

*Structure analysis: 2026-04-12*
