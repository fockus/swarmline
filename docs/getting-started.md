# Getting Started

## Installation

### Core (protocols, types, in-memory providers)

```bash
pip install cognitia
```

### With a runtime

```bash
pip install cognitia[thin]          # Built-in lightweight multi-provider runtime
pip install cognitia[claude]        # Claude Agent SDK runtime (subprocess + MCP)
pip install cognitia[deepagents]    # DeepAgents runtime baseline (native graph + Anthropic path)
```

`cognitia[thin]` bundles the Anthropic, OpenAI-compatible, and Google SDK paths used by ThinRuntime.

DeepAgents provider overrides are installed separately:

```bash
pip install cognitia[deepagents] langchain-openai openai
pip install cognitia[deepagents] langchain-google-genai
```

### With storage

```bash
pip install cognitia[postgres]      # PostgreSQL memory provider
pip install cognitia[sqlite]        # SQLite memory provider
```

### With web tools

```bash
pip install cognitia[web]           # Base web fetch (httpx)
pip install cognitia[web-duckduckgo] # DuckDuckGo search (no API key)
pip install cognitia[web-tavily]    # Tavily AI search
pip install cognitia[web-jina]      # Jina Reader (URL → markdown)
pip install cognitia[web-crawl4ai]  # Crawl4AI (Playwright-based)
```

### With sandbox

```bash
pip install cognitia[e2b]           # E2B cloud sandbox
pip install cognitia[docker]        # Docker sandbox
```

### Everything (for development)

```bash
pip install cognitia[all,dev]
```

## Quick Start: `cognitia init` (recommended)

The fastest way to start a new project — scaffold a full agent in 10 seconds:

```bash
pip install cognitia[cli]
cognitia init my-agent
cd my-agent
cp .env.example .env   # add your ANTHROPIC_API_KEY
pip install -e .
python agent.py "Hello!"
```

Options:

```bash
cognitia init my-agent                    # minimal (thin runtime, in-memory)
cognitia init my-agent --runtime claude   # Claude Agent SDK
cognitia init my-agent --memory sqlite    # persistent SQLite memory
cognitia init my-agent --full             # all features + Docker setup
cognitia init my-agent --output ./projects  # custom output directory
```

Generated structure:

```
my-agent/
├── agent.py          ← main entry point (runnable immediately)
├── config.yaml       ← agent configuration (runtime, memory, tools)
├── tests/
│   └── test_agent.py ← starter test
├── .env.example      ← API key template
├── pyproject.toml    ← project metadata
└── README.md         ← usage instructions
# (--full adds: Dockerfile, docker-compose.yml, skills/)
```

---

## Quick Start: Agent Facade (simplest)

The fastest way to get started without scaffolding — 3 lines of code:

```python
from cognitia import Agent, AgentConfig

agent = Agent(AgentConfig(system_prompt="You are a helpful assistant.", runtime="thin"))
result = await agent.query("What is the capital of France?")
print(result.text)  # "The capital of France is Paris."
```

That's it. No config files, no project structure — just an agent that works.

## Credentials and Environment Variables

Before using a live provider, decide which runtime/provider path you want and set credentials accordingly:

- `thin` reads provider credentials from the current shell environment
- `claude_sdk` can use either local Claude login state or explicit `ANTHROPIC_API_KEY`
- `deepagents` uses provider-specific LangChain credentials
- `cli` forwards credentials to the wrapped CLI via shell env or `CliConfig.env`

Canonical reference:

- [Credentials & Provider Setup](credentials.md)

Fast examples:

```bash
# Thin + Anthropic
export ANTHROPIC_API_KEY=sk-ant-...

# Thin + OpenRouter
export OPENAI_API_KEY=sk-or-...

# DeepAgents + OpenRouter (OpenAI-compatible path)
export OPENAI_API_KEY=sk-or-...
export OPENAI_BASE_URL=https://openrouter.ai/api/v1
```

If you use the high-level `AgentConfig` facade, portable runtimes (`thin`, `deepagents`) currently read credentials from process environment. `AgentConfig.env` is primarily for `claude_sdk`.

## Security Defaults

Current releases are secure by default:

- `enable_host_exec=False` for MCP server startup
- `allow_host_execution=False` for `LocalSandboxProvider`
- `allow_unauthenticated_query=False` for `cognitia serve`

Enable any of these only when you intentionally trust the operator boundary and have compensating controls in place.

## Step-by-Step Guide

### 1. Custom Tools

Define tools as async Python functions. Cognitia auto-infers JSON Schema from type hints:

```python
from cognitia import Agent, AgentConfig, tool

@tool(name="weather", description="Get current weather for a city")
async def get_weather(city: str, units: str = "celsius") -> str:
    # In production, call a real weather API here
    return f"Weather in {city}: 22 {units}"

agent = Agent(AgentConfig(
    system_prompt="You are a weather assistant.",
    runtime="thin",
    tools=(get_weather,),
))

result = await agent.query("What's the weather in Paris?")
print(result.text)  # "The weather in Paris is 22 celsius."
```

Type mapping: `str` → `"string"`, `int` → `"integer"`, `float` → `"number"`, `bool` → `"boolean"`. Parameters with defaults are optional in the schema.

### 2. Streaming

Get tokens as they arrive from the model:

```python
agent = Agent(AgentConfig(system_prompt="You are a writer.", runtime="thin"))

async for event in agent.stream("Write a haiku about Python"):
    if event.type == "text_delta":
        print(event.text, end="", flush=True)
    elif event.type == "tool_use_start":
        print(f"\n[Tool: {event.tool_name}]")
```

Event types: `text_delta`, `tool_use_start`, `tool_use_result`, `done`, `error`. Use attributes like `event.type`, `event.text`, `event.tool_name`.

### 3. Multi-Turn Conversation

Maintain context across turns:

```python
async with agent.conversation() as conv:
    r1 = await conv.say("My name is Alice")
    r2 = await conv.say("What's my name?")
    print(r2.text)  # "Your name is Alice."

    # Streaming in conversation
    async for event in conv.stream("Tell me a joke"):
        if event.type == "text_delta":
            print(event.text, end="", flush=True)
```

### 4. Structured Output

Force the model to return validated data using a Pydantic model:

```python
from pydantic import BaseModel

class UserInfo(BaseModel):
    name: str
    age: int

from cognitia.runtime.structured_output import extract_pydantic_schema

agent = Agent(AgentConfig(
    system_prompt="Extract user info from text.",
    runtime="thin",
    output_format=extract_pydantic_schema(UserInfo),
))

result = await agent.query("John is 30 years old")
print(result.structured_output)  # UserInfo(name='John', age=30)
```

You can also use a raw JSON Schema dict via `output_format=` for simpler cases without Pydantic.

See [Structured Output](structured-output.md) for nested models, retry logic, and low-level API.

### 5. Middleware

Intercept requests and responses for cost tracking, security, logging:

```python
from cognitia.agent import CostTracker, SecurityGuard

tracker = CostTracker(budget_usd=5.0)
guard = SecurityGuard(block_patterns=["password", "secret", "api_key"])

agent = Agent(AgentConfig(
    system_prompt="You are a helpful assistant.",
    runtime="thin",
    middleware=(tracker, guard),
))

result = await agent.query("Hello!")
print(tracker.total_cost_usd)    # 0.002
```

If a turn pushes the cumulative spend above the configured budget,
`CostTracker` raises `BudgetExceededError`.

You can write custom middleware by extending the `Middleware` base class:

```python
from cognitia.agent import Middleware

class LoggingMiddleware(Middleware):
    async def before_query(self, prompt: str, config) -> str:
        print(f"→ {prompt}")
        return prompt

    async def after_result(self, result) -> "Result":
        print(f"← {result.text[:50]}")
        return result
```

### 6. Switching Runtimes

Same code, different execution engines. Switch with one config change:

```python
# Development: fast, no subprocess
agent = Agent(AgentConfig(system_prompt="...", runtime="thin"))

# Production: full Claude ecosystem with MCP
agent = Agent(AgentConfig(system_prompt="...", runtime="claude_sdk"))

# Experiments: DeepAgents graph runtime
agent = Agent(AgentConfig(system_prompt="...", runtime="deepagents"))
```

Or via environment variable:

```bash
export COGNITIA_RUNTIME=thin
```

### 6.1 DeepAgents: portable first

If you want the smallest migration gap between `claude_sdk` and `deepagents`, start with portable mode:

```python
agent = Agent(AgentConfig(
    system_prompt="You are a helpful assistant.",
    runtime="deepagents",
    feature_mode="portable",
))
result = await agent.query("What is 2+2?")
print(result.text)
```

Feature modes:

- `portable` — tested parity baseline for `query()`, `stream()`, `conversation()`
- `hybrid` — portable core + DeepAgents native built-ins/store seams
- `native_first` — prefer DeepAgents native built-ins and graph behavior

Practical note: the baseline `cognitia[deepagents]` extra is Anthropic-ready. For OpenAI or Google provider paths, install the provider bridge package separately. If you enable native built-ins, also pass an explicit `native_config["backend"]`; Cognitia now fails fast instead of silently falling back to DeepAgents `StateBackend`. For tool-heavy Gemini built-ins, prefer `portable` mode unless you are explicitly testing native provider behavior.

### 7. Model Selection

Use human-friendly aliases for any supported provider:

```python
# Anthropic
agent = Agent(AgentConfig(runtime="thin", model="sonnet"))   # Claude Sonnet 4
agent = Agent(AgentConfig(runtime="thin", model="opus"))     # Claude Opus 4
agent = Agent(AgentConfig(runtime="thin", model="haiku"))    # Claude Haiku 3

# OpenAI (via base_url or thin runtime)
agent = Agent(AgentConfig(runtime="thin", model="gpt-4o"))

# Google
agent = Agent(AgentConfig(runtime="thin", model="gemini"))

# DeepSeek
agent = Agent(AgentConfig(runtime="thin", model="r1"))
```

### 8. Resource Cleanup

Always clean up when done:

```python
# Option 1: async context manager (recommended)
async with Agent(config) as agent:
    result = await agent.query("Hello")
# cleanup called automatically

# Option 2: explicit cleanup
agent = Agent(config)
try:
    result = await agent.query("Hello")
finally:
    await agent.cleanup()
```

## Advanced: CognitiaStack

For production applications that need memory, sandbox, web tools, planning, and MCP skills — use `CognitiaStack`:

### Project Structure

```
your_app/
├── prompts/
│   ├── identity.md         # Agent personality
│   ├── guardrails.md       # Security constraints
│   ├── role_router.yaml    # Auto role-switching rules
│   ├── role_skills.yaml    # Role → tools/skills mapping
│   └── roles/
│       └── assistant.md    # Per-role prompts
├── skills/                 # MCP skills (optional)
│   └── my_skill/
│       ├── skill.yaml
│       └── INSTRUCTION.md
└── main.py
```

### Minimal Stack

```python
from pathlib import Path
from cognitia.bootstrap.stack import CognitiaStack
from cognitia.runtime.types import RuntimeConfig
from cognitia.todo.inmemory_provider import InMemoryTodoProvider

stack = CognitiaStack.create(
    prompts_dir=Path("prompts"),
    skills_dir=Path("skills"),
    project_root=Path("."),
    runtime_config=RuntimeConfig(runtime_name="thin", model="sonnet"),
    todo_provider=InMemoryTodoProvider(user_id="user-1", topic_id="general"),
    thinking_enabled=True,
)
```

### Full-Featured Stack

```python
from cognitia.bootstrap.stack import CognitiaStack
from cognitia.runtime.types import RuntimeConfig
from cognitia.tools.sandbox_local import LocalSandboxProvider
from cognitia.tools.types import SandboxConfig
from cognitia.tools.web_httpx import HttpxWebProvider
from cognitia.todo.inmemory_provider import InMemoryTodoProvider
from cognitia.memory_bank.fs_provider import FilesystemMemoryBankProvider
from cognitia.memory_bank.types import MemoryBankConfig

sandbox = LocalSandboxProvider(SandboxConfig(
    root_path="/data/sandbox",
    user_id="user-1",
    topic_id="project-1",
    timeout_seconds=30,
    denied_commands=frozenset({"rm", "sudo"}),
    allow_host_execution=False,  # host execution remains opt-in
))

memory = FilesystemMemoryBankProvider(
    MemoryBankConfig(enabled=True, root_path=Path("/data/memory")),
    user_id="user-1",
    topic_id="project-1",
)

stack = CognitiaStack.create(
    prompts_dir=Path("prompts"),
    skills_dir=Path("skills"),
    project_root=Path("."),
    runtime_config=RuntimeConfig(runtime_name="thin", model="sonnet"),
    sandbox_provider=sandbox,
    web_provider=HttpxWebProvider(timeout=30),
    todo_provider=InMemoryTodoProvider(user_id="user-1", topic_id="project-1"),
    memory_bank_provider=memory,
    thinking_enabled=True,
    allowed_system_tools={"bash", "read", "write", "edit"},
)
```

### Running the Stack

```python
from cognitia.runtime.types import Message

# Create runtime
runtime = stack.runtime_factory.create(
    runtime_name="thin",
    config=stack.runtime_config,
)

# Run a query
messages = [Message(role="user", content="Help me analyze this project")]

async for event in runtime.run(
    messages=messages,
    system_prompt="You are a helpful assistant.",
    active_tools=list(stack.capability_specs.values()),
):
    if event.type == "assistant_delta":
        print(event.data["text"], end="")
    elif event.type == "tool_call_started":
        print(f"\n[Tool: {event.data['name']}]")
    elif event.type == "final":
        new_messages = event.data["new_messages"]
```

> **Note:** When using `runtime.run()` directly, events have raw `RuntimeEvent` types
> (`assistant_delta`, `tool_call_started`, `tool_call_finished`, `final`).
> When using `Agent.stream()`, these are adapted to `text_delta`, `tool_use_start`,
> `tool_use_result`, `done` — see the [Streaming](#2-streaming) section above.

### 9. Cost Budget

Track LLM spending and enforce limits using the middleware API:

```python
from cognitia.agent import Agent, AgentConfig, CostTracker

tracker = CostTracker(budget_usd=5.0)

agent = Agent(AgentConfig(
    system_prompt="You are a helpful assistant.",
    runtime="thin",
    middleware=(tracker,),
))

result = await agent.query("Hello!")
print(f"Total cost: ${tracker.total_cost_usd:.4f}")
```

For lower-level control, see `CostBudget` and `CostTracker` in [Production Safety](production-safety.md).

### 10. Guardrails

Pre- and post-LLM content checks via `RuntimeConfig`:

```python
from cognitia.guardrails import ContentLengthGuardrail, RegexGuardrail

# Guardrails are applied at the RuntimeConfig level
length_guard = ContentLengthGuardrail(max_length=8000)
regex_guard = RegexGuardrail(patterns=[r"ignore previous instructions"])

# Check content before sending to LLM
result = await length_guard.check("Some user input here")
print(result.passed)  # True if within limits
```

### 11. Sessions

Persist session state across restarts:

```python
from cognitia.session.backends import SqliteSessionBackend, MemoryScope, scoped_key

backend = SqliteSessionBackend(db_path="sessions.db")
key = scoped_key(MemoryScope.AGENT, "user:42:session:abc")
await backend.save(key, {"turn": 7, "role": "coach"})
```

See [Sessions](sessions.md) for `InMemorySessionBackend`, custom backends, and `SessionManager` integration.

### 12. Observability

Event bus and tracing for runtime instrumentation:

```python
from cognitia.observability.event_bus import InMemoryEventBus
from cognitia.observability.tracer import ConsoleTracer, TracingSubscriber

bus = InMemoryEventBus()
tracer = ConsoleTracer()
subscriber = TracingSubscriber(bus, tracer)
subscriber.attach()

# Subscribe to specific events
await bus.subscribe("llm_call_end", lambda data: print(f"LLM call: {data}"))

# Fire events (ThinRuntime does this automatically)
await bus.publish("llm_call_end", {"model": "sonnet", "tokens": 150})
```

See [Observability](observability.md) for custom tracers and event subscriptions.

### 13. UI Projection

Convert `RuntimeEvent` streams into UI-friendly state for frontends:

```python
from cognitia.ui.projection import ChatProjection, project_stream
from cognitia.runtime.types import RuntimeEvent

projection = ChatProjection()

# project_stream wraps an async event iterator into UIState updates
async def demo_events():
    yield RuntimeEvent.assistant_delta(text="Hello, ")
    yield RuntimeEvent.assistant_delta(text="world!")
    yield RuntimeEvent.final(text="Hello, world!", new_messages=[])

async for ui_state in project_stream(demo_events(), projection):
    for msg in ui_state.messages:
        print(msg.blocks)  # [TextBlock(text="Hello, world!")]
```

See [UI Projection](ui-projection.md) for custom projections and `UIState.to_dict()` serialization.

### 14. RAG

Inject relevant documents into LLM context using `RagInputFilter`:

```python
from cognitia.rag import Document, SimpleRetriever, RagInputFilter
from cognitia.runtime.types import Message

docs = [
    Document(content="Paris is the capital of France."),
    Document(content="Python was created by Guido van Rossum."),
]

retriever = SimpleRetriever(documents=docs)
rag_filter = RagInputFilter(retriever=retriever, top_k=2)

messages = [Message(role="user", content="What is the capital of France?")]
filtered_msgs, enriched_prompt = await rag_filter.filter(messages, "You are helpful.")
print(enriched_prompt)  # System prompt with relevant docs injected
```

See [RAG](rag.md) for custom retrievers (Pinecone, pgvector) and filter chain integration.

## What's New in v1.0.0

- **CLI Runtime** — subprocess-based runtime with NDJSON protocol (`CliAgentRuntime`, see example `19_cli_runtime.py`)
- **Multi-Agent** — agent-as-tool composition, priority task queues, agent registry with lifecycle management (examples `21`-`23`)
- **Workflow Graphs** — declarative graphs with conditions, loops, parallel branches, and human-in-the-loop interrupts (`WorkflowGraph`, example `20_workflow_graph.py`)
- **RAG** — retrieval-augmented generation with pluggable retrievers and `RagInputFilter` (example `08_rag.py`)
- **27 runnable examples** — from basics to complex multi-agent scenarios, see [Examples](examples.md)

## Next Steps

- [Agent Facade API](agent-facade.md) — full reference for Agent, AgentConfig, @tool, Result, Conversation, Middleware
- [Runtimes](runtimes.md) — Claude SDK vs ThinRuntime vs DeepAgents vs CLI: comparison, switching, capabilities
- [Capabilities](capabilities.md) — sandbox, web, todo, memory bank, planning, thinking
- [Memory Providers](memory.md) — InMemory, PostgreSQL, SQLite: 8 protocols, summarization
- [Tools & Skills](tools-and-skills.md) — @tool decorator, MCP skills (YAML), tool policy
- [Web Tools](web-tools.md) — search providers (DuckDuckGo, Brave, Tavily, SearXNG), fetch providers
- [Configuration](configuration.md) — CognitiaStack, RuntimeConfig, ToolPolicy, environment variables
- [Orchestration](orchestration.md) — planning mode, subagents, team mode, agent-as-tool, task queues, workflow graphs
- [Structured Output](structured-output.md) — Pydantic validation, retry on failure, nested models
- [Production Safety](production-safety.md) — cost budgets, guardrails, input filters, retry/fallback
- [Sessions](sessions.md) — session backends, memory scopes, persistence
- [Observability](observability.md) — event bus, tracing, custom tracers
- [UI Projection](ui-projection.md) — RuntimeEvent to UIState for frontends
- [RAG](rag.md) — retrieval-augmented generation, custom retrievers, filter chains
- [Runtime Registry](runtime-registry.md) — custom runtimes, entry point plugins
- [Architecture](architecture.md) — Clean Architecture layers, protocols, design principles
- [Examples](examples.md) — 27 runnable examples from basics to complex scenarios
