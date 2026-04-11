# Architecture

## Principles

Swarmline is built on Clean Architecture and SOLID:

- **Protocol-driven**: all contracts are `typing.Protocol` with `@runtime_checkable`. No abstract classes.
- **ISP**: each Protocol contains no more than 5 methods.
- **DIP**: consumers depend on Protocols, not on concrete implementations.
- **Immutable types**: all domain objects are frozen dataclasses. Mutation through creating a new instance.
- **No domain leak**: the library knows nothing about the business application. Grep `freedom_agent` across `src/` — 0 matches.

## Layers

```text
┌──────────────────────────────────────────────────────────┐
│  Business Application (your_app)                         │
│  Knows about swarmline. Implements concrete providers.    │
├──────────────────────────────────────────────────────────┤
│  swarmline (library)                                       │
│  bootstrap | context | runtime (claude/thin/cli/deep)    │
│  policy | session | tools | memory | skills | routing     │
│  memory_bank | orchestration | hooks | observability      │
├──────────────────────────────────────────────────────────┤
│  External Dependencies (LLM API, DB, MCP)                 │
└──────────────────────────────────────────────────────────┘
```

## Packages

| Package | Purpose | Dependencies |
| ------- | ------- | ------------ |
| `bootstrap` | Facade: `SwarmlineStack.create()`, capabilities wiring | core |
| `context` | System prompt assembly with token budget | core |
| `session` | SessionManager, Rehydrator, TaskSessionStore | memory |
| `memory` | Message, fact, goal storage + Episodic, Procedural, Consolidation | core |
| `memory_bank` | Long-term file-based memory (FS, DB) + Knowledge Bank | core |
| `multi_agent` | Agent Graph, TaskBoard, Communication, Governance, Registry, TaskQueue | core |
| `pipeline` | Multi-phase execution engine with budget gates, builder DSL | core |
| `todo` | Checklists / task tracking (InMemory, FS, DB) | core |
| `tools` | Sandbox isolation, builtin tools, web, thinking | core |
| `orchestration` | Planning, subagents, team mode, message bus | core |
| `policy` | ToolPolicy (deny/allow), ToolSelector (budget) | core |
| `routing` | KeywordRoleRouter (auto role-switching) | core |
| `skills` | SkillRegistry, LoadedSkill, SkillSpec, McpServerSpec; YAML loader helper in `skills.loader` | core |
| `runtime` | AgentRuntime (Claude SDK, ThinRuntime, CLI, DeepAgents) | extras |
| `resilience` | Circuit breaker for external calls | core |
| `observability` | Structured logging, EventBus, Tracing, OTel, ActivityLog | structlog |
| `hooks` | Lifecycle hooks (pre/post turn) | core |
| `commands` | CommandRegistry (slash-commands) | core |
| `daemon` | Long-running process manager, scheduler, health checks | core |
| `eval` | Agent evaluation: EvalRunner, Scorers, Reporters, Compare | core |
| `plugins` | PluginRunner (subprocess JSON-RPC), worker shim | core |
| `a2a` | Agent-to-Agent protocol (JSON-RPC 2.0 / SSE) | starlette, httpx |
| `serve` | HTTP API (`swarmline serve`) | starlette |

## Protocol Map

```text
MessageStore ─────┐
FactStore ────────┤
GoalStore ────────┤── memory providers (InMemory, Postgres, SQLite)
SummaryStore ─────┤
SessionStateStore ┘

MemoryBankProvider ── memory_bank providers (FS, DB)

KnowledgeStore ───┐
KnowledgeSearcher ┤── knowledge providers (InMemory, FS, SQLite, Postgres)
ProgressLog ──────┤
ChecklistManager ─┤
VerificationStrategy ┘

GraphStore ───────┐
GraphTaskBoard ───┤── graph backends (InMemory, SQLite, Postgres)
GraphCommunication┘

TodoProvider ──────── todo providers (InMemory, FS, DB)

SandboxProvider ───── sandbox providers (Local, E2B, Docker)

WebProvider ────────── web providers (Httpx)

AgentRuntime ──────── runtime (ClaudeCode, Thin, CLI, DeepAgents)

PlanStore ─────────── plan stores (InMemory)
PlannerMode ───────── planners (Thin, DeepAgents)

SubagentOrchestrator ── subagent orchestrators (Thin, DeepAgents, Claude)
TeamOrchestrator ────── team orchestrators (DeepAgents, Claude)

TaskQueue ─────────── task queues (InMemory, SQLite, Postgres)
AgentRegistry ─────── registries (InMemory, SQLite, Postgres)
EventBus ──────────── event buses (InMemory, Redis, NATS)
```

## Dependency Direction

```mermaid
graph TD
    A[Your Application] --> B[Agent Facade]
    B --> C[14 Protocols]
    C --> D[Implementations]
    D --> E[External Dependencies]

    style A fill:#f3e8ff,stroke:#7c3aed
    style B fill:#ede9fe,stroke:#7c3aed
    style C fill:#ddd6fe,stroke:#7c3aed
    style D fill:#c4b5fd,stroke:#7c3aed
    style E fill:#a78bfa,stroke:#7c3aed
```

Dependencies always point **inward** (Infrastructure → Application → Domain). The domain layer has zero external dependencies. Your application code depends only on Protocols — never on concrete implementations.

## Design Decisions

### Why Protocols over ABC?

- `typing.Protocol` supports structural subtyping — no inheritance required
- Implementations don't need to explicitly inherit from the protocol
- Enables duck typing with static type checking
- `@runtime_checkable` for runtime validation where needed

### Why Frozen Dataclasses?

- Immutability prevents accidental state mutation
- Thread-safe by design
- Hashable — can be used in sets and as dict keys
- Forces explicit state transitions through new instance creation

### Why ≤5 Methods per Protocol (ISP)?

- Small interfaces are easier to implement and test
- Reduces coupling between components
- Each protocol represents a single responsibility
- Mix-and-match: implement only the protocols you need
