# Detailed Competitive Analysis: Swarmline vs 7 Agent Frameworks

**Date:** 2026-03-30
**Context:** Rebranding cognitia → swarmline, full competitive positioning
**Frameworks:** CrewAI, AutoGen, OpenAI Agents SDK, Claude Agent SDK, Semantic Kernel, Swarms, LangGraph Swarm

---

## General Summary

| | **Stars** | **Providers** | **Status** | **Core** |
|---|---|---|---|---|
| **Swarmline** | — (private) | 4 runtime (Anthropic, OpenAI, Google, DeepSeek) | Active v1.2.0 | Protocol-driven agent toolkit, Clean Architecture |
| **CrewAI** | 47.5K | 5 native + LiteLLM (200+) | Active, $18M funding | Role-playing crews + Flows |
| **AutoGen** (MS) | 56.4K | 8+ dedicated clients | **Maintenance mode** → Agent Framework | Conversation-driven multi-agent |
| **OpenAI Agents SDK** | 20.4K | OpenAI-first + LiteLLM | Active, pre-1.0 (v0.13) | Minimal handoff-based agents |
| **Claude Agent SDK** | 6K (SDK), 81K (CLI) | Claude only (multi-cloud) | Active, v0.1.51 | Subprocess CLI + MCP native |
| **Semantic Kernel** | 27.6K | 11+ connectors | **Maintenance mode** → Agent Framework | Enterprise Kernel + plugins |
| **Swarms** | 6.1K | LiteLLM (100+) | Active, v10.0.1 | 17+ swarm patterns |
| **LangGraph Swarm** | 1.4K | LangChain ecosystem | Active, v0.1.0 | ~300 LOC handoff layer |

---

## Architecture Comparison

| | Approach | Agent class | SRP | Protocols |
|---|---|---|---|---|
| **Swarmline** | Clean Architecture, 3 layers | AgentConfig frozen DC + thin facade | High | 20+ ISP (≤5 methods) |
| **CrewAI** | Crews + Flows | BaseAgent 30 fields, Crew 1650 LOC/85 methods | **Low** (God Objects) | 1 Protocol (15 methods) |
| **AutoGen** | Core/AgentChat/Extensions | ConversableAgent class hierarchy | Medium | No formal Protocols |
| **OpenAI SDK** | 4 primitives (Agent, Runner, Handoff, Guardrail) | Agent generic `Agent[TContext]` | High | Custom `Model` interface |
| **Claude SDK** | Subprocess CLI | `ClaudeSDKClient` + `query()` | Medium | No (MCP + hooks) |
| **Semantic Kernel** | Thick Kernel + DI | KernelFunction + plugin classes | Medium | No ISP Protocols |
| **Swarms** | Monolith structs/ | **6175 LOC, 100+ params** | **Very Low** | 1 BaseSwarm ABC (30 methods) |
| **LangGraph Swarm** | StateGraph + handoff | 4 functions, 0 classes | N/A (~300 LOC) | 0 |

---

## Multi-Agent Orchestration

| | Patterns | Hierarchical | Task Board/DAG | Governance | Parallel |
|---|---|---|---|---|---|
| **Swarmline** | Graph + teams + subagents + pipeline | Graph Agents (governance, delegation) | DAG deps, progress, BLOCKED | Capabilities, permissions, limits | Semaphore-bounded |
| **CrewAI** | Sequential, Hierarchical, Flows | Manager-worker (**broken** per #4783) | Flows (event-driven) | **Stub** (fingerprint only) | Flows only |
| **AutoGen** | 6+ conversation patterns | GroupChat with manager | Nested chat | None in core | Async (0.4) |
| **OpenAI SDK** | Handoff + as_tool | None | None | None | None |
| **Claude SDK** | Subagents + Teams (TS only) | 1 level nesting | None | 5-step permission chain | Subagents parallel |
| **Semantic Kernel** | 5 patterns (experimental) | Sequential + Concurrent | Process Framework | Filters (3 types) | Concurrent orchestration |
| **Swarms** | **17+ via SwarmRouter** | HierarchicalSwarm (basic) | None | None | ConcurrentWorkflow |
| **LangGraph Swarm** | 1 (handoff) | None | None | None | None (1 active agent) |

---

## Memory

| | Conversation | Persistent backends | Episodic | Procedural | Knowledge/RAG | Consolidation |
|---|---|---|---|---|---|---|
| **Swarmline** | 8 ISP protocols | InMemory, SQLite, Postgres | Yes | Yes | Knowledge Bank (5 protocols) | Yes |
| **CrewAI** | Unified Memory | LanceDB, Qdrant, ChromaDB | No | No | Built-in RAG | Yes (merge similar) |
| **AutoGen** | Chat history | ChromaDB, Redis, Mem0 | No | Teachability | Via extensions | No |
| **OpenAI SDK** | Session history | 7+ backends (SQLite, Redis, SQLAlchemy, Dapr) | No | No | No | No |
| **Claude SDK** | JSONL files | Filesystem only | No | No | CLAUDE.md files | No |
| **Semantic Kernel** | No built-in | 15 vector store connectors | No | No | Kernel Memory (external) | No |
| **Swarms** | In-memory list | JSON/YAML files | No | No | External (abandoned) | No |
| **LangGraph Swarm** | Messages list | LangGraph checkpointer | No | No | No | No |

---

## Security & Governance

| | Tool policy | Budget tracking | Guardrails | HITL | Audit trail |
|---|---|---|---|---|---|
| **Swarmline** | **Default-deny**, allowlists | CostBudget + PersistentBudgetStore | Input + Output + Tool | ApprovalGate + policies | ActivityLog (InMem/SQLite) |
| **CrewAI** | No | No in OSS (enterprise paywall) | guardrail param | Flows feedback | OpenTelemetry |
| **AutoGen** | No | No in core | No | UserProxyAgent | No |
| **OpenAI SDK** | No default-deny | No | Input + Output + **Tool** guardrails | Tool approve/reject | OpenAI Traces (lock-in) |
| **Claude SDK** | **5-step eval chain** + sandboxing | No | Via hooks | Permissions | Via hooks |
| **Semantic Kernel** | No | No | 3 filter types (GA) | No built-in | No |
| **Swarms** | No | No | SAFETY_PROMPT (text) | No | Telemetry (sends data) |
| **LangGraph Swarm** | No | No | No | LangGraph interrupt | No |

---

## Testing Quality

| | Tests | Coverage | Contract tests | Offline default |
|---|---|---|---|---|
| **Swarmline** | 3200+ | 89%+ | Yes | Yes |
| **CrewAI** | 223 files (count unknown) | Not published | No | VCR + block-network |
| **AutoGen** | Unknown | Not published | No | Mock LLM |
| **OpenAI SDK** | Present | Not published | No | Mock |
| **Claude SDK** | Community plugin | Not published | No | No |
| **Semantic Kernel** | 3231+ | 90% | No | Mock |
| **Swarms** | ~54 files | Not published | No | Requires API keys |
| **LangGraph Swarm** | 2 files | No | No | pytest-socket |

---

## Vendor Lock-in Risk

| | Lock-in | What ties you |
|---|---|---|
| **Swarmline** | **Minimal** | Provider-agnostic, protocol-driven |
| **CrewAI** | Medium | LiteLLM dep, telemetry to CrewAI cloud, enterprise paywall |
| **AutoGen** | High | **Maintenance mode** → Microsoft Agent Framework (new API) |
| **OpenAI SDK** | Medium-High | Hosted tools OpenAI-only, tracing → OpenAI Traces, pre-1.0 |
| **Claude SDK** | **High** | Claude-only, Node.js dep, subprocess model |
| **Semantic Kernel** | High | **Maintenance mode**, Azure-centric, → Agent Framework |
| **Swarms** | Medium | LiteLLM pinned, telemetry, 10 majors/3yr |
| **LangGraph Swarm** | High | Tight LangChain coupling |

---

## Ideas to Borrow — Detailed

### From AutoGen

**Teachability (persistent learning via vector DB)**
Agent remembers user corrections between sessions. When user corrects ("no, I meant X not Y"), saves (mistake → correct answer) pair as embedding in ChromaDB. Next conversation — searches similar situations and loads as context. Agent literally learns from mistakes.
- For Swarmline: extend FactStore + vector search. We have Procedural Memory (tool sequences), Teachability = next level (user preferences + corrections).

**Nested Chat**
Agent can invoke internal dialogue between other agents as "inner monologue". Main agent receives question, launches nested chat between researcher and critic, they argue, main agent gets only final result. User sees only final answer.
- For Swarmline: implement as "deliberation subgraph" tool via Graph Agents.

**Carryover Mechanism**
In sequential multi-agent chains, summary of previous dialogue auto-transfers as context to next agent. Not full chat — just extract. Saves tokens, removes noise.
- For Swarmline: auto-generate summary context when delegating in Graph Agents instead of passing full history.

### From OpenAI Agents SDK

**MCP Transport Diversity (5 vs 1)**
We only have stdio (subprocess). OpenAI SDK: HostedMCPTool (OpenAI infra), HTTP Streamable (self-hosted, recommended), SSE (legacy), stdio (local), MCPServerManager (multi-server). HTTP Streamable = connect remote MCP servers without subprocess.
- For Swarmline: add HTTP transport for MCP — one httpx client. Enables remote MCP servers.

**Tool Guardrails**
Beyond input/output guardrails: `@tool_input_guardrail` — validate args before tool call, `@tool_output_guardrail` — validate result after. Guardrail can reject, allow, or **replace** result.
- For Swarmline: extend PostToolUse hook contract to allow `modified_result` return.

**Nested Handoff History Compression**
When handing off between agents, full chat history transfers. Expensive. `nest_handoff_history` (beta) compresses previous history into summary wrapped in special message.
- For Swarmline: directly applicable to Graph Agents delegation. LLM-summary instead of full history.

### From Claude Agent SDK

**5-Step Permission Eval Chain**
Most mature permission model. Chain: Hooks (PreToolUse can block) → Deny rules (disallowed_tools, always wins) → Permission mode (default/dontAsk/acceptEdits/bypass/plan) → Allow rules (allowed_tools) → canUseTool callback (app's final decision). Deny always wins even in bypass mode.
- For Swarmline: make ToolPolicy composable — chain of policy layers, each can allow/deny/pass-through. Cascading eval without subprocess model.

**Hook Granularity (12+ events)**
12+ lifecycle hooks: PreToolUse, PostToolUse, PostToolUseFailure, UserPromptSubmit, Stop, SubagentStart, SubagentStop, PreCompact, PermissionRequest, Notification (+ SessionStart, SessionEnd, TeammateIdle, TaskCompleted in TS). We cover only 4 events.
- For Swarmline: add SubagentStart/Stop, PreCompact, PermissionRequest. Extends HookRegistry without breaking.

**Session Fork/Resume**
Create branch from existing session (fork) for A/B exploration. Agent reaches decision point, user forks, tries two paths in parallel, picks best.
- For Swarmline: `SessionManager.fork(session_id) -> new_session_id` — copy history, continue from new state. Useful for interactive exploration and pipeline "what if".

### From Semantic Kernel

**OpenAPI Plugin Import**
Auto-generate plugins from OpenAPI spec (swagger.json). Give URL swagger — get set of tools. Each endpoint becomes callable function with correct params.
- For Swarmline: `OpenApiToolLoader("https://api.example.com/openapi.json")` → list[ToolSpec]. Killer-feature for REST API integration.

**Named Orchestration Patterns**
Instead of "build graph manually" — ready-made named patterns: SequentialOrchestration, ConcurrentOrchestration, HandoffOrchestration, GroupChatOrchestration. Unified API: `orchestration.invoke(task, runtime)`.
- For Swarmline: factory shortcuts: `swarmline.sequential([a, b])`, `swarmline.parallel([agents])`, `swarmline.hierarchy(lead, workers)` — create Graph under the hood. On top of existing API, not replacing it.

**Prompt Render Filter**
Intercept prompt after assembly but before LLM call. Can: inject RAG context, redact PII, cache (semantic caching), block send.
- For Swarmline: middleware between ContextBuilder and LLM call. Useful for dynamic RAG injection and PII redaction.

### From Swarms

**SwarmRouter (Strategy Selector)**
Single entry point: pass task + agents, SwarmRouter picks optimal strategy. `swarm_type="auto"` — LLM decides which pattern fits the task.
- For Swarmline: `auto` idea interesting but risky (unpredictable). Better as opt-in suggestion.

**AgentRearrange DSL**
Compact string syntax: `"A -> B, C -> D"` means "A passes to B and C in parallel, both pass to D".
- For Swarmline: `Graph.from_dsl("lead -> [researcher, coder] -> reviewer")`. Trivial parser, big readability win.

**MixtureOfAgents**
Multiple "experts" get same task in parallel, each responds independently, aggregator synthesizes best answer. Like ML ensemble.
- For Swarmline: first-class pattern: `swarmline.mixture([expert1, expert2, expert3], aggregator=synth)`.

**Auto Swarm Selection**
LLM analyzes task, auto-picks: sequential, parallel, mixture, hierarchical.
- For Swarmline: questionable — adds unpredictability. Maybe as opt-in "suggest me a pattern".

### From LangGraph Swarm

**Command Handoff Pattern**
Agent calls handoff tool → returns `Command(goto=target, update={state_delta})`. Atomic operation: navigation + state update in one object. No race condition, no partial state.
- For Swarmline: `DelegationCommand(target="coder", context_update={...})` — atomic delegate + state update.

**Agent-Isolated Message Keys**
By default all agents see all messages (privacy problem). Solution: each agent stores messages in own state key. Agent sees only own messages + shared context.
- For Swarmline: scoped shared context — agent sees own messages + parent messages + broadcast, not sibling conversations.

---

## Confirmed Roadmap Items (user-approved)

1. **CLI scaffolding** (`swarmline create/run`) — IDEA-029, priority → High
2. **Vector store / RAG connectors** — IDEA-028, priority → High
3. **LiteLLM adapter** (4 → 200+ providers) — IDEA-030, priority → High

## Explicitly Rejected

- Visualization (graph/flow) — use external tools instead
- Enterprise SaaS — documentation site + community only

---

## Strategic Conclusions

### Swarmline unique position (no competitor has all):
- Clean Architecture with 20+ ISP protocols
- Default-deny tool policy + CostBudget + Guardrails in OSS
- Episodic + Procedural memory + Consolidation pipeline
- Knowledge Bank with 5 ISP protocols and multi-backend search
- Graph Agents with governance (capabilities, permissions, limits)
- Pipeline Engine with budget gates
- 3200+ tests, 89%+ coverage, contract tests

### Frameworks entering maintenance mode (opportunity):
- AutoGen → Microsoft Agent Framework
- Semantic Kernel → Microsoft Agent Framework
- Both losing new features, communities migrating

### Biggest competitive threats:
1. CrewAI — 47K stars, $18M funding, enterprise SaaS
2. OpenAI Agents SDK — fast growth, good DX
3. Microsoft Agent Framework (SK+AutoGen merger) — enterprise backing

### Anti-patterns observed across competitors:
- God Object Agent: Swarms (6175 LOC), CrewAI Crew (1650 LOC/85 methods)
- No governance in OSS: CrewAI, Swarms, AutoGen, LangGraph Swarm
- Maintenance mode without migration: AutoGen, Semantic Kernel
- Telemetry without opt-out: Swarms, CrewAI
- API instability: Swarms (10 majors/3yr), OpenAI SDK (pre-1.0)
