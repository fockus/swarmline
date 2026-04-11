# Use Cases

Swarmline is most useful when you need more than a single LLM call but do not want to marry your whole application to one runtime, one provider, or one framework-specific abstraction.

This page is the shortest path to answering: **"Is Swarmline a good fit for what I am building?"**

## 1. Internal assistant for tools, files, or operations

**Typical goal**

Build an internal assistant that can:

- call business tools
- read or write files through a sandbox
- keep session context across turns
- run with guardrails and budget limits

**Why Swarmline fits**

- `@tool` gives you a low-friction tool surface
- the same app can start on `thin` and later move to `claude_sdk` or `cli`
- sessions, memory, and persistence are already part of the library
- security features are opt-in but first-class

**Good starting stack**

- runtime: `thin`
- add later: sandbox, sessions, `CostTracker`, `SecurityGuard`

**Docs to open**

- [Getting Started](getting-started.md)
- [Tools & Skills](tools-and-skills.md)
- [Production Safety](production-safety.md)

---

## 2. Research copilot with web + memory + structured output

**Typical goal**

Build a research or analysis assistant that can:

- search the web or fetch source pages
- retrieve supporting context from a local knowledge base
- return typed summaries, briefs, or reports
- remember user goals and previous work

**Why Swarmline fits**

- web providers and RAG filters plug into the same agent surface
- structured output works across runtimes
- memory and sessions help long-running research flows
- examples already cover research-style scenarios

**Good starting stack**

- runtime: `thin`
- add: web providers, retriever, `output_format`, memory provider

**Docs to open**

- [Web Tools](web-tools.md)
- [RAG](rag.md)
- [Structured Output](structured-output.md)
- [Examples](examples.md)

---

## 3. Provider-agnostic backend for a product team

**Typical goal**

Build an API/backend that powers product features while keeping the LLM layer replaceable for cost, latency, compliance, or integration reasons.

**Why Swarmline fits**

- the `Agent` facade stays stable while the runtime changes
- `thin` supports Anthropic, OpenAI-compatible, and Google paths
- `deepagents` and `claude_sdk` can be introduced later if runtime-specific features become important
- the storage layer is also swappable

**Good starting stack**

- runtime: `thin`
- storage: `InMemory` in development, SQLite/PostgreSQL later
- docs to keep open: runtimes matrix + credentials matrix

**Docs to open**

- [Runtimes](runtimes.md)
- [Credentials & Providers](credentials.md)
- [Configuration](configuration.md)

---

## 4. LangGraph / DeepAgents integration without losing a simple facade

**Typical goal**

Use DeepAgents or LangGraph-native behavior, but keep a simpler top-level application surface for the rest of the codebase.

**Why Swarmline fits**

- `deepagents` runtime lives behind the same `Agent` facade
- you can keep portable mode for the common path and enable native features only where needed
- Swarmline still handles structured output, sessions, orchestration helpers, and shared docs/tests around the facade

**Good starting stack**

- runtime: `deepagents`
- feature mode: `portable` first
- add native built-ins/checkpointer/store only when you need them

**Docs to open**

- [Runtimes](runtimes.md)
- [Credentials & Providers](credentials.md)
- [Design Patterns](design-patterns.md)

---

## 5. Wrapping an existing CLI agent into a product or workflow

**Typical goal**

Reuse an external CLI agent already proven in your team, but expose it through a consistent Swarmline runtime interface.

**Why Swarmline fits**

- `cli` runtime lets you wrap NDJSON-emitting CLIs as `AgentRuntime`
- you keep the same facade-level `query`, `stream`, and `conversation` surface
- credentials stay with the CLI you are wrapping, not with Swarmline-specific assumptions

**Good starting stack**

- runtime: `cli`
- pass env through `CliConfig.env` or shell environment

**Docs to open**

- [CLI Runtime](cli-runtime.md)
- [Credentials & Providers](credentials.md)
- [Examples](examples.md)

---

## 6. Multi-agent workflows and longer-running operations

**Typical goal**

Coordinate more than one agent over a queue, workflow, or task graph.

**Why Swarmline fits**

- workflow graph and orchestration helpers are already included
- sessions and memory give you a place to keep state outside one runtime call
- multi-agent primitives exist without forcing you into a monolithic framework

**Good starting stack**

- start with one agent and a workflow graph
- then add task queue, registry, and team orchestration pieces

**Docs to open**

- [Orchestration](orchestration.md)
- [Multi-Agent Coordination](multi-agent.md)
- [Examples](examples.md)

---

## 7. Code agent infrastructure (Claude Code, Codex, OpenCode)

**Typical goal**

Give your code agent (Claude Code, Codex CLI, OpenCode, or any MCP-compatible client) persistent memory, structured planning, team coordination, and safe code execution — without any LLM cost from Swarmline itself.

**Why Swarmline fits**

- the MCP server exposes 20 tools over STDIO — zero configuration beyond `pip install`
- headless mode (default) adds zero LLM calls — the code agent is the brain, Swarmline is the hands
- memory persists facts, messages, and summaries across tool calls within a session
- plans provide a state machine (draft → approved → step-by-step execution) for structured work
- team tools let multiple agents coordinate via a task queue with priority and claiming
- full mode (opt-in) enables sub-agent creation using your own API key

**Good starting stack**

- install: `pip install swarmline[code-agent]`
- MCP config: add `swarmline-mcp --mode auto` to your client's MCP settings
- start with memory tools for cross-session knowledge
- add plans when tasks have 3+ steps
- add team tools when coordinating multiple agents

**Example scenarios**

| Scenario | Tools Used |
|----------|-----------|
| Research swarm — 3 agents investigate different aspects | team + memory |
| Persistent brain — recall architecture decisions across sessions | memory |
| Code review pipeline — distribute files to reviewers | team + memory |
| Resumable refactoring — 10-step plan survives interruptions | plans |
| Analysis scripts — count lines, check dependencies | code execution |
| Feature development — frontend + backend agents share context | plans + team + memory |
| Learning agent — store and recall coding patterns | memory |

**Docs to open**

- [MCP Server](mcp-server.md)
- [CLI Reference](cli.md)
- [Claude Code Integration](claude-code-integration.md)
- [Codex Integration](codex-integration.md)

---

## When Swarmline is the wrong tool

You may not need Swarmline if:

- you only need a single provider SDK call and no long-lived agent state
- you are already fully committed to one framework and do not want a portability layer
- you do not need tools, memory, sessions, or orchestration

In those cases, using the provider SDK directly can be simpler.

## Recommended First Paths

If you are still deciding where to begin:

- Want the fastest path to a working agent: [Getting Started](getting-started.md)
- Need to compare runtimes before coding: [Runtimes](runtimes.md)
- Need to wire credentials correctly: [Credentials & Providers](credentials.md)
- Want copy-paste recipes: [Cookbook](cookbook.md)
