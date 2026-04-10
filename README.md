# Swarmline

**Build AI agents in Python** — from a single assistant to hierarchical multi-agent systems.

[![PyPI version](https://img.shields.io/pypi/v/swarmline.svg)](https://pypi.org/project/swarmline/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-3200%2B%20passed-brightgreen.svg)](https://github.com/fockus/swarmline)
[![Docs](https://img.shields.io/badge/docs-readthedocs-blue.svg)](https://swarmline.readthedocs.io/)

> Provider-agnostic, pluggable runtimes (Anthropic, OpenAI, Google, DeepSeek), persistent memory, agent graphs with governance, knowledge banks, pipeline execution, and Clean Architecture.

## Why Swarmline?

Swarmline covers the full spectrum: **simple single-agent assistants** that you build in 3 lines, and **complex multi-agent systems** with org charts, task delegation, and shared knowledge — using the same API.

**For simple agents:**
- 3-line quick start — `Agent` + `AgentConfig` + `query()`
- Swap LLM provider (Anthropic, OpenAI, Google, DeepSeek) with one config change
- Built-in tools, middleware, structured output, streaming
- InMemory / SQLite / PostgreSQL storage — pick what fits

**For multi-agent systems:**
- Agent Graph — hierarchical organizations with governance and delegation
- Knowledge Bank — structured knowledge shared across agents with search
- Pipeline Engine — multi-phase execution with budget gates and quality checks
- Memory that learns — episodic + procedural + consolidation: agents remember and improve
- Human-in-the-Loop — approval patterns at tool, plan, and output level

**For both:**
- 4 pluggable runtimes — `thin`, `claude_sdk`, `deepagents`, `cli` — same business code
- Clean Architecture with 20+ ISP-compliant protocols — swap any component without touching the rest
- Default-secure — deny-all tool policy, sandboxed execution, input validation

### Key Differentiators

| vs. | Swarmline advantage |
|-----|-------------------|
| **LangChain/LangGraph** | True multi-provider (not just wrapper), Clean Architecture, governance built-in, no vendor lock-in |
| **CrewAI** | Protocol-first (swap any layer), hierarchical graphs (not flat crews), persistent memory with consolidation |
| **AutoGen (Microsoft)** | Structured task boards with DAG dependencies, budget enforcement, knowledge bank with search |
| **Claude Code SDK** | LLM-agnostic (4 providers), multi-agent graphs, pipeline engine, evaluation framework |
| **OpenAI Agents SDK** | Multi-runtime (not locked to OpenAI), persistent episodic/procedural memory, HITL approval patterns |
| **Semantic Kernel** | Python-native (not C# port), simpler API (3-line agent), built-in knowledge consolidation |

## Install

```bash
pip install cognitia                # core (protocols, types, in-memory providers)
pip install cognitia[thin]          # + lightweight built-in multi-provider runtime
pip install cognitia[claude]        # + Claude Agent SDK runtime (subprocess + MCP)
pip install cognitia[deepagents]    # + DeepAgents runtime baseline (native graph + Anthropic path)
```

For DeepAgents provider overrides install the provider bridge explicitly:

```bash
pip install cognitia[deepagents] langchain-openai openai
pip install cognitia[deepagents] langchain-google-genai
```

## Credentials & Provider Setup

Provider credentials depend on the runtime and provider path you choose:

- `thin` reads provider credentials from the current process environment
- `claude_sdk` can use local Claude login state or explicit `ANTHROPIC_API_KEY`
- `deepagents` uses provider-specific LangChain credentials
- `cli` passes through whatever env the wrapped CLI expects

Canonical reference:

- [docs/credentials.md](docs/credentials.md)

Common cases:

```bash
# Thin + Anthropic
export ANTHROPIC_API_KEY=sk-ant-...

# Thin + OpenRouter
export OPENAI_API_KEY=sk-or-...

# DeepAgents + OpenRouter (OpenAI-compatible path)
export OPENAI_API_KEY=sk-or-...
export OPENAI_BASE_URL=https://openrouter.ai/api/v1
```

Important: `deepagents` does not use `openrouter:*` as a native provider prefix. Use the OpenAI-compatible path instead, for example `model="openai:anthropic/claude-3.5-haiku"`.

## Quick Start

### Simple agent (3 lines)

```python
from cognitia import Agent, AgentConfig

agent = Agent(AgentConfig(system_prompt="You are a helpful assistant.", runtime="thin"))
result = await agent.query("What is the capital of France?")
print(result.text)  # "The capital of France is Paris."
```

### Streaming

```python
async for event in agent.stream("Explain quantum computing"):
    if event.type == "text_delta":
        print(event.text, end="", flush=True)
```

### Multi-turn conversation

```python
async with agent.conversation() as conv:
    r1 = await conv.say("My name is Alice")
    r2 = await conv.say("What's my name?")
    print(r2.text)  # "Your name is Alice."
```

### Custom tools

```python
from cognitia import AgentConfig, Agent, tool

@tool(name="calculate", description="Calculate a math expression")
async def calculate(expression: str) -> str:
    return str(eval(expression))  # simplified for demo

agent = Agent(AgentConfig(
    system_prompt="You are a calculator assistant.",
    runtime="thin",
    tools=(calculate,),
))
result = await agent.query("What is 15 * 23?")
print(result.text)  # "345"
```

### Structured output

```python
agent = Agent(AgentConfig(
    system_prompt="Extract user info.",
    runtime="thin",
    output_format={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
        },
        "required": ["name", "age"],
    },
))
result = await agent.query("John is 30 years old")
print(result.structured_output)  # {"name": "John", "age": 30}
```

### Middleware (cost tracking, security)

```python
from cognitia.agent import CostTracker, SecurityGuard

tracker = CostTracker(budget_usd=1.0)
guard = SecurityGuard(blocked_patterns=["password", "secret"])

agent = Agent(AgentConfig(
    system_prompt="You are a helpful assistant.",
    runtime="thin",
    middleware=(tracker, guard),
))
result = await agent.query("Hello")
print(tracker.total_cost_usd)  # 0.002
```

### Scale up: multi-agent systems

When a single agent isn't enough, scale to teams:

### Agent graph (hierarchical teams)

```python
from cognitia.multi_agent.graph_builder import GraphBuilder
from cognitia.multi_agent.graph_orchestrator import GraphOrchestrator

# Build an agent org chart
graph = (
    GraphBuilder()
    .add_agent("lead", role="lead", capabilities={"can_delegate": True, "can_hire": True})
    .add_agent("researcher", role="researcher")
    .add_agent("coder", role="coder")
    .set_root("lead")
    .connect("lead", "researcher")
    .connect("lead", "coder")
    .build()
)

# Run with task delegation
orchestrator = GraphOrchestrator(graph=graph, runner=my_runner)
result = await orchestrator.run("Build a REST API for user management")
```

### Knowledge Bank (shared agent memory)

```python
from cognitia.memory_bank.knowledge_inmemory import InMemoryKnowledgeStore

store = InMemoryKnowledgeStore()
await store.save("api-patterns", "REST API best practices: versioning, pagination, error handling",
                 kind="reference", tags=["api", "patterns"])

results = await store.search("REST API versioning")
```

### Pipeline (multi-phase execution)

```python
from cognitia.pipeline.builder import PipelineBuilder

pipeline = (
    PipelineBuilder("deploy-pipeline")
    .add_phase("test", handler=run_tests)
    .add_phase("build", handler=build_artifacts, depends_on=["test"])
    .add_phase("deploy", handler=deploy_to_prod, depends_on=["build"])
    .set_budget(max_cost_usd=5.0)
    .build()
)
result = await pipeline.run()
```

## Features

### Core

| Feature | Description |
|---------|-------------|
| **Agent Facade** | High-level API: `query()`, `stream()`, `conversation()` — build agents in 3-5 lines |
| **4 Pluggable Runtimes** | `thin` (built-in multi-provider loop), `claude_sdk` (Claude Agent SDK), `deepagents` (LangChain), `cli` (subprocess NDJSON runtime) |
| **@tool Decorator** | Define tools with auto-inferred JSON Schema from Python type hints |
| **Middleware Chain** | Pluggable request/response interceptors: `CostTracker`, `SecurityGuard`, custom |
| **14 ISP Protocols** | Every interface has ≤5 methods. Depend on abstractions, swap implementations freely |
| **Multi-provider Models** | Anthropic, OpenAI, Google, DeepSeek — alias resolution (`"sonnet"` → `claude-sonnet-4-20250514`) |

### Multi-Agent & Orchestration (v1.2.0)

| Feature | Description |
|---------|-------------|
| **Agent Graph System** | Hierarchical multi-agent with org charts, governance, delegation, and task boards |
| **Graph Builder DSL** | Declarative agent hierarchy construction with YAML/dict support |
| **Agent Governance** | Capabilities (can_hire, can_delegate, max_children), permission enforcement |
| **Graph Task Board** | Hierarchical tasks with DAG dependencies, progress auto-calculation, BLOCKED status |
| **Graph Communication** | Inter-agent messaging (InMemory, SQLite, Postgres, Redis, NATS) |
| **Knowledge Bank** | Universal domain-agnostic structured knowledge storage with 5 ISP protocols |
| **Pipeline Engine** | Multi-phase execution with budget gates, builder DSL |
| **Human-in-the-Loop** | Approval patterns for tool-level, plan-level, and output-level human review |
| **Plugin Runner** | Subprocess JSON-RPC plugin host for extensible agent capabilities |
| **HostAdapter Protocol** | Universal agent management API (spawn/send/stop/status) with AgentSDKAdapter (Claude) and CodexAdapter (OpenAI) |
| **Three Lifecycle Modes** | EPHEMERAL (self-terminate), SUPERVISED (creator controls), PERSISTENT (survives across goals) |
| **Authority & Capability Delegation** | Hierarchical permission system: can_hire, max_depth, can_delegate_authority with governance checks |
| **Persistent Agent Graphs** | Long-lived agent organizations with FIFO goal queues for sequential goal processing |

### Memory & Persistence

| Feature | Description |
|---------|-------------|
| **3 Memory Providers** | InMemory (dev), SQLite (single-user), PostgreSQL (production) — same 8 protocols |
| **8 Memory Protocols** | `MessageStore`, `FactStore`, `GoalStore`, `SummaryStore`, `UserStore`, `SessionStateStore`, `PhaseStore`, `ToolEventStore` |
| **Episodic Memory** | Store and recall past agent experiences with InMemory, SQLite, PostgreSQL backends |
| **Procedural Memory** | Learn from repeated tool use patterns — automatic tool sequence recognition |
| **Memory Consolidation** | Pipeline from episodic memory to long-term knowledge bank |
| **Memory Bank** | Long-term file-based memory across sessions (filesystem or database backend) |
| **Auto-summarization** | Template-based or LLM-powered conversation summarization |

### Capabilities (toggle independently)

| Capability | What it does | Tools provided |
| ----------- | ------------- | ---------------- |
| **Sandbox** | Isolated file I/O and command execution | `bash`, `read`, `write`, `edit`, `glob`, `grep`, `ls` |
| **Web** | Internet access with pluggable providers | `web_fetch`, `web_search` |
| **Todo** | Structured task tracking | `todo_read`, `todo_write` |
| **Memory Bank** | Persistent knowledge across sessions | `memory_read`, `memory_write`, `memory_list`, `memory_delete` |
| **Planning** | Step-by-step task decomposition and execution | `plan_create`, `plan_status`, `plan_execute` |
| **Thinking** | Chain-of-thought reasoning | `thinking` |

### Advanced

| Feature | Description |
|---------|-------------|
| **Tool Policy** | Default-deny with allowlists per role/skill. `ALWAYS_DENIED` set for dangerous tools |
| **Tool Budget** | Priority-based tool selection when too many tools would confuse the model |
| **MCP Skills** | Declarative YAML skill definitions with automatic MCP server management |
| **Role Routing** | Keyword-based automatic role switching with per-role tool/skill mapping |
| **Context Builder** | Token-budget-aware system prompt assembly with priority-based overflow |
| **Hooks** | Lifecycle hooks: `PreToolUse`, `PostToolUse`, `Stop`, `UserPromptSubmit` |
| **Observability** | Structured JSON logging via structlog + OpenTelemetry export + ActivityLog audit trail |
| **Evaluation Framework** | Agent eval with custom scorers, compare/history, console + JSON reporters |
| **HTTP API** | `cognitia serve` — REST API for agent interaction |
| **Daemon** | Universal long-running process manager with health checks, scheduler, PID management |
| **Circuit Breaker** | Resilience pattern for external service calls |
| **Session Management** | Multi-session support with rehydration from persistent storage |
| **Orchestration** | Subagents, team mode (lead + workers), planning mode |
| **Commands** | Custom slash-command registry |

## Runtimes

Swarmline supports 4 interchangeable runtimes. Switch with a single config change — your business code stays the same:

```python
# Built-in lightweight loop (direct multi-provider API)
agent = Agent(AgentConfig(system_prompt="...", runtime="thin"))

# Claude Agent SDK (subprocess with full MCP support)
agent = Agent(AgentConfig(system_prompt="...", runtime="claude_sdk"))

# DeepAgents graph runtime
agent = Agent(AgentConfig(system_prompt="...", runtime="deepagents"))

# CLI subprocess runtime (NDJSON stream, light tier)
agent = Agent(AgentConfig(system_prompt="...", runtime="cli"))
```

Or via environment variable:
```bash
export COGNITIA_RUNTIME=thin
```

| Runtime | Best For | LLM Support | MCP | Install |
| ------- | -------- | ----------- | --- | ------- |
| `thin` | Fast prototyping, direct API, alternative LLMs | Anthropic, OpenAI-compatible, Google | Built-in client | `cognitia[thin]` |
| `claude_sdk` | Full Claude ecosystem, native MCP, subagents | Claude only | Native | `cognitia[claude]` |
| `deepagents` | DeepAgents graph runtime, LangGraph workflows | Anthropic baseline; OpenAI/Google via provider package | Not a portable guarantee | `cognitia[deepagents]` |
| `cli` | External CLI agents, NDJSON subprocess integrations | Whatever the wrapped CLI provides | No portable MCP guarantee | `cognitia` |

### Runtime Feature Matrix

Each runtime brings unique native strengths. Swarmline's library layer fills the gaps — so your code works the same regardless of which runtime is active.

```
┌──────────────────────────┬──────────┬───────────┬───────┬──────────────┐
│ Feature                  │ claude   │ deep      │ thin  │ Swarmline    │
│                          │ _sdk     │ agents    │       │ library      │
├──────────────────────────┼──────────┼───────────┼───────┼──────────────┤
│ MCP Servers              │ ✅ SDK   │ ❌        │ ✅    │ ✅ bridge    │
│ Streaming (token-level)  │ ✅       │ ✅        │ ⚠️    │ ✅ portable  │
│ Structured Output        │ ✅ SDK   │ ✅ both   │ ✅    │ ✅ portable  │
│ Tool Masking             │ ✅ SDK   │ ✅ auto   │ ✅    │ ✅ config    │
│ Hooks (PreToolUse etc)   │ ✅       │ ❌        │ ❌    │ ✅ middleware │
│ Subagents                │ ✅       │ ✅        │ ✅    │ ✅ lib       │
│ Team Mode                │ ✅ lead  │ ✅ super  │ ⚠️    │ ✅ lib       │
│ Resume / Stateful        │ ✅ SDK   │ ✅ CP     │ ❌    │ ✅ lib       │
│ HITL / Approvals         │ ✅ SDK   │ ✅ int    │ ❌    │ ✅ event     │
│ Budget Enforcement       │ ✅ SDK   │ ❌        │ ✅    │ ✅ middleware │
│ Provider Override        │ ❌       │ ✅        │ ✅    │ ✅ registry  │
│ Built-in Planner Mode    │ ❌       │ ⚠️ LG     │ ✅    │ ✅ lib       │
│ Native Built-in Tools    │ ✅ SDK   │ ✅ (9)    │ ❌    │ —            │
│ State Persistence        │ ✅ SDK   │ ✅ CP     │ ❌    │ ✅ lib       │
│ Graph Workflows          │ ❌       │ ✅ LG     │ ❌    │ —            │
│ Multi-Provider           │ ❌       │ ✅        │ ✅    │ ✅ registry  │
│ Memory Bank              │ —        │ —         │ —     │ ✅ FS/DB     │
│ DoD Verification         │ —        │ —         │ —     │ ✅ lib       │
│ Context Builder          │ —        │ —         │ —     │ ✅ budget    │
│ Planning & Orchestration │ —        │ —         │ —     │ ✅ lib       │
└──────────────────────────┴──────────┴───────────┴───────┴──────────────┘

Legend: ✅ = Supported  ⚠️ = Partial  ❌ = Not supported  — = N/A
CP = Checkpointer  LG = LangGraph  int = interrupt_on
```

The **Swarmline library** column shows what works with **any** runtime — memory bank, planning, DoD verification, context builder, middleware, and orchestration are all runtime-agnostic.

### Portable Matrix

- `claude_sdk` and `deepagents` share an offline-tested portable baseline for `query()`, `stream()`, and `conversation()` when `feature_mode="portable"`.
- `deepagents` keeps native power through `feature_mode="hybrid"` and `feature_mode="native_first"`; native notices and resume metadata surface through `native_metadata`.
- `thin` is the lightweight tier. It is intentionally not treated as a full-runtime parity target.
- DeepAgents provider notes:
  - `cognitia[deepagents]` installs the baseline runtime and Anthropic-ready path.
  - OpenAI and Google paths require `langchain-openai` / `openai` or `langchain-google-genai`.
  - Native built-ins require an explicit `native_config["backend"]`; without it Swarmline now fails fast instead of silently falling back to DeepAgents `StateBackend`.
  - Tool-heavy Gemini built-ins remain a provider-specific limitation today; use `feature_mode="portable"` when you need the strongest parity guarantees.

### DeepAgents Portable Quick Start

```python
agent = Agent(AgentConfig(
    system_prompt="You are a helpful assistant.",
    runtime="deepagents",
    feature_mode="portable",
))
result = await agent.query("What is 2+2?")
print(result.text)
```

### Capability negotiation

Each runtime declares its capabilities. Use `CapabilityRequirements` to ensure your chosen runtime supports what you need:

```python
from cognitia.runtime.capabilities import CapabilityRequirements

agent = Agent(AgentConfig(
    system_prompt="...",
    runtime="claude_sdk",
    require_capabilities=CapabilityRequirements(
        tier="full",
        flags=("mcp", "resume"),
    ),
))
# Fails fast if the runtime doesn't support required features
```

## Architecture

```
Your Application
       │
       │ depends on protocols (DIP)
       ▼
╔══════════════════════════════════════════════════════════╗
║                      Swarmline                           ║
║                                                          ║
║  ┌─────────────────────────────────────────────────────┐ ║
║  │  Agent Facade                                       │ ║
║  │  Agent · AgentConfig · @tool · Middleware · Result   │ ║
║  └─────────────────┬───────────────────────────────────┘ ║
║                    │                                     ║
║  ┌─────────────────▼───────────────────────────────────┐ ║
║  │  14 Protocols (ISP: ≤5 methods each)                │ ║
║  │  MessageStore · FactStore · GoalStore · SummaryStore │ ║
║  │  UserStore · SessionStateStore · PhaseStore          │ ║
║  │  ToolEventStore · RoleRouter · ToolIdCodec          │ ║
║  │  ModelSelector · ContextBuilder · RuntimePort       │ ║
║  │  AgentRuntime                                       │ ║
║  └─────────────────┬───────────────────────────────────┘ ║
║                    │                                     ║
║  ┌─────────────────▼───────────────────────────────────┐ ║
║  │  Implementations                                    │ ║
║  │  memory/      InMemory │ PostgreSQL │ SQLite        │ ║
║  │               + Episodic · Procedural · Consolidation│ ║
║  │  runtime/     thin │ claude_sdk │ deepagents │ cli  │ ║
║  │  multi_agent/ AgentGraph · TaskBoard · Communication│ ║
║  │               Governance · Knowledge Bank            │ ║
║  │  pipeline/    Pipeline · Builder · Budget · Gates   │ ║
║  │  context/     DefaultContextBuilder (token budget)  │ ║
║  │  policy/      DefaultToolPolicy (default-deny)      │ ║
║  │  routing/     KeywordRoleRouter                     │ ║
║  │  skills/      SkillRegistry + YAML loader helper    │ ║
║  │  hooks/       HookRegistry + SDK bridge             │ ║
║  │  tools/       Sandbox · Web · Todo · MemoryBank     │ ║
║  │  orchestration/  Planning · Subagents · Team        │ ║
║  │  observability/  Logging · Tracing · OTel · Activity│ ║
║  │  daemon/      Process manager · Scheduler · Health  │ ║
║  │  eval/        EvalRunner · Scorers · Reporters      │ ║
║  │  plugins/     PluginRunner (subprocess JSON-RPC)    │ ║
║  └─────────────────────────────────────────────────────┘ ║
╚══════════════════════════════════════════════════════════╝
```

**Key principles:**

- **Domain-agnostic** — no business domain logic in the library
- **Protocol-first** — depend on abstractions, not implementations
- **Pluggable** — swap any component with a single line change
- **Clean Architecture** — dependencies point inward only (Infrastructure → Application → Domain)
- **ISP** — Interface Segregation: each protocol has ≤5 focused methods
- **Immutable types** — all domain objects are frozen dataclasses

## Memory Providers

Three interchangeable providers, all implementing the same 8 protocols:

```python
# Development — no database needed
from cognitia.memory import InMemoryMemoryProvider
memory = InMemoryMemoryProvider()

# Lightweight persistence — SQLite
from cognitia.memory import SQLiteMemoryProvider
memory = SQLiteMemoryProvider(db_path="./agent.db")

# Production — PostgreSQL
from cognitia.memory import PostgresMemoryProvider
memory = PostgresMemoryProvider(session_factory)
```

## Capabilities

Enable only what you need — each capability is an independent toggle:

```python
from cognitia.bootstrap import CognitiaStack
from cognitia.runtime.types import RuntimeConfig
from cognitia.tools.sandbox_local import LocalSandboxProvider
from cognitia.tools.web_httpx import HttpxWebProvider
from cognitia.todo.inmemory_provider import InMemoryTodoProvider

stack = CognitiaStack.create(
    prompts_dir="./prompts",
    skills_dir="./skills",
    project_root=".",
    runtime_config=RuntimeConfig(runtime_name="thin"),
    # Toggle capabilities independently:
    sandbox_provider=LocalSandboxProvider(sandbox_config),  # file I/O, bash
    web_provider=HttpxWebProvider(),                        # web search/fetch
    todo_provider=InMemoryTodoProvider(user_id="u1", topic_id="t1"),
    thinking_enabled=True,                                  # chain-of-thought
)
```

## Web Search Providers

Pluggable web search with 4 providers and 3 fetch backends:

```python
# Search providers (pick one)
from cognitia.tools.web_providers.duckduckgo import DuckDuckGoSearchProvider  # no API key
from cognitia.tools.web_providers.brave import BraveSearchProvider            # BRAVE_API_KEY
from cognitia.tools.web_providers.tavily import TavilySearchProvider          # TAVILY_API_KEY
from cognitia.tools.web_providers.searxng import SearXNGSearchProvider        # self-hosted

# Fetch providers (pick one)
from cognitia.tools.web_httpx import HttpxWebProvider           # default (httpx)
from cognitia.tools.web_providers.jina import JinaReaderFetchProvider    # JINA_API_KEY
from cognitia.tools.web_providers.crawl4ai import Crawl4AIFetchProvider  # Playwright
```

## Model Registry

Multi-provider model resolution with human-friendly aliases:

```python
from cognitia.runtime.types import resolve_model_name

resolve_model_name("sonnet")   # "claude-sonnet-4-20250514"
resolve_model_name("opus")     # "claude-opus-4-20250514"
resolve_model_name("gpt-4o")   # "gpt-4o"
resolve_model_name("gemini")   # "gemini-2.5-pro"
resolve_model_name("r1")       # "deepseek-reasoner"
```

Supported providers: **Anthropic** (Claude), **OpenAI** (GPT-4o, o3), **Google** (Gemini), **DeepSeek** (R1).

## Optional Dependencies

| Extra | Packages | Purpose |
|-------|----------|---------|
| `thin` | anthropic, httpx | Built-in lightweight runtime |
| `claude` | claude-agent-sdk | Claude Agent SDK runtime |
| `deepagents` | langchain-core, langchain-anthropic | LangChain runtime |
| `postgres` | asyncpg, sqlalchemy | PostgreSQL memory provider |
| `sqlite` | aiosqlite, sqlalchemy | SQLite memory provider |
| `web` | httpx | Web fetch (base) |
| `web-duckduckgo` | ddgs | DuckDuckGo search (no API key) |
| `web-tavily` | tavily-python | Tavily AI search |
| `web-jina` | httpx | Jina Reader (URL → markdown) |
| `web-crawl4ai` | crawl4ai | Crawl4AI (Playwright-based) |
| `e2b` | e2b | E2B cloud sandbox |
| `docker` | docker | Docker sandbox |
| `otel` | opentelemetry-api, opentelemetry-sdk | OpenTelemetry tracing export |
| `a2a` | starlette, httpx | Agent-to-Agent protocol |
| `mcp` | fastmcp | MCP server for code agents |
| `redis` | redis | Redis EventBus + Graph Communication |
| `nats` | nats-py | NATS EventBus + Graph Communication |
| `all` | All of the above | Development convenience |

## Framework Comparison

How Swarmline compares to popular agent frameworks:

```
┌───────────────────────────┬───────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
│ Capability                │ Swarmline │ LangGraph│ CrewAI   │ AutoGen  │ OpenAI   │ Claude   │
│                           │           │          │          │(Microsoft│ Agents   │ Code SDK │
│                           │           │          │          │)         │ SDK      │          │
├───────────────────────────┼───────────┼──────────┼──────────┼──────────┼──────────┼──────────┤
│ Multi-provider (4+ LLMs)  │ ✅        │ ✅       │ ✅       │ ✅       │ ❌ OpenAI│ ❌ Claude│
│ Hierarchical agent graph  │ ✅        │ ⚠️ manual│ ❌ flat  │ ⚠️ manual│ ❌       │ ❌       │
│ Agent governance          │ ✅        │ ❌       │ ❌       │ ❌       │ ❌       │ ❌       │
│ Task board + DAG deps     │ ✅        │ ⚠️ graph │ ❌       │ ⚠️       │ ❌       │ ❌       │
│ Knowledge bank + search   │ ✅        │ ❌       │ ❌       │ ❌       │ ❌       │ ❌       │
│ Episodic + procedural mem │ ✅        │ ❌       │ ⚠️ basic │ ❌       │ ❌       │ ❌       │
│ Memory consolidation      │ ✅        │ ❌       │ ❌       │ ❌       │ ❌       │ ❌       │
│ Pipeline + budget gates   │ ✅        │ ❌       │ ❌       │ ❌       │ ❌       │ ❌       │
│ Human-in-the-Loop         │ ✅        │ ✅       │ ⚠️       │ ✅       │ ❌       │ ✅       │
│ Evaluation framework      │ ✅        │ ⚠️ langsmith│ ❌    │ ❌       │ ❌       │ ❌       │
│ Clean Architecture        │ ✅ ISP    │ ❌       │ ❌       │ ❌       │ ❌       │ ❌       │
│ Default-deny security     │ ✅        │ ❌       │ ❌       │ ❌       │ ❌       │ ✅       │
│ OpenTelemetry             │ ✅        │ ✅       │ ❌       │ ❌       │ ❌       │ ❌       │
│ MCP support               │ ✅        │ ❌       │ ❌       │ ❌       │ ❌       │ ✅ native│
│ Swappable storage backends│ ✅ 3      │ ⚠️ CP   │ ❌       │ ❌       │ ❌       │ ❌       │
│ A2A protocol              │ ✅        │ ❌       │ ❌       │ ❌       │ ❌       │ ❌       │
│ Structured output         │ ✅        │ ✅       │ ✅       │ ✅       │ ✅       │ ✅       │
│ 3-line quick start        │ ✅        │ ❌       │ ✅       │ ❌       │ ✅       │ ✅       │
└───────────────────────────┴───────────┴──────────┴──────────┴──────────┴──────────┴──────────┘

Legend: ✅ Built-in  ⚠️ Partial/manual  ❌ Not available  CP = Checkpointer
```

**When to choose Swarmline:**
- You need **multi-agent teams** with governance, delegation, and hierarchical task management
- You want **LLM-agnostic** code that works across Anthropic, OpenAI, Google, and DeepSeek
- You need agents that **learn and remember** across sessions (episodic + procedural memory)
- You want **Clean Architecture** — protocol-driven, testable, swappable at every layer
- You need **production safety** — budget enforcement, default-deny tools, HITL approvals

**When other frameworks may be better:**
- **LangGraph** — if you need the LangSmith ecosystem and are OK with LangChain lock-in
- **CrewAI** — if you prefer declarative YAML agent definitions and simpler flat teams
- **Claude Code SDK** — if you only use Claude and want maximum native integration
- **AutoGen** — if you need Microsoft ecosystem integration

## Documentation

### Getting Started
- [Why Swarmline?](docs/why-cognitia.md) — value proposition, design philosophy
- [Getting Started](docs/getting-started.md) — installation, first agent, step-by-step
- [Agent Facade API](docs/agent-facade.md) — Agent, AgentConfig, @tool, Result, Conversation, Middleware

### Core
- [Runtimes](docs/runtimes.md) — Claude SDK vs ThinRuntime vs DeepAgents
- [Memory](docs/memory.md) — InMemory, PostgreSQL, SQLite + Episodic, Procedural, Consolidation
- [Tools & Skills](docs/tools-and-skills.md) — @tool decorator, MCP skills, tool policy
- [Capabilities](docs/capabilities.md) — sandbox, web, todo, memory bank, planning, thinking
- [Configuration](docs/configuration.md) — CognitiaStack, RuntimeConfig, environment variables

### Multi-Agent (v1.2.0)
- [Agent Graph System](docs/graph-agents.md) — hierarchical multi-agent with governance, task boards, communication
- [Knowledge Bank](docs/knowledge-bank.md) — universal structured knowledge storage
- [Multi-Agent Coordination](docs/multi-agent.md) — agent-as-tool, task queues, agent registry
- [Pipeline Engine](docs/pipeline.md) — multi-phase execution with budget gates
- [Human-in-the-Loop](docs/hitl.md) — approval patterns for agent actions
- [HostAdapter Protocol](docs/host-adapter.md) — universal agent management API with two adapters
- [Lifecycle Modes](docs/lifecycle-modes.md) — EPHEMERAL, SUPERVISED, PERSISTENT agent lifecycles
- [Authority System](docs/authority-system.md) — capability delegation and governance checks
- [Persistent Graph](docs/persistent-graph.md) — long-lived agent orgs with goal queues

### Advanced
- [Orchestration](docs/orchestration.md) — planning, subagents, team mode
- [Evaluation](docs/evaluation.md) — agent quality measurement framework
- [Observability](docs/observability.md) — EventBus, tracing, OpenTelemetry, ActivityLog
- [Architecture](docs/architecture.md) — layers, protocols, packages
- [Web Tools](docs/web-tools.md) — search and fetch providers
- [Advanced](docs/advanced.md) — hooks, circuit breaker, context builder
- [API Reference](docs/api-reference.md) — comprehensive API documentation
- [Examples](docs/examples.md) — integration examples for different domains
- [Changelog](CHANGELOG.md)
- [Contributing](CONTRIBUTING.md)

## License

[MIT](LICENSE)
