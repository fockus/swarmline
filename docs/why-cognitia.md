# Why Swarmline?

## The Problem

Building production AI agents requires far more than an LLM API call. A real agent needs:

- **Memory** — conversation history, user facts, session state, summaries
- **Tools** — function calling, MCP servers, security policies, sandboxing
- **Observability** — structured logging, cost tracking, audit trails
- **Session management** — multi-user, multi-topic, rehydration after restart
- **Provider flexibility** — switch between Anthropic, OpenAI, Google without rewriting code

Most frameworks either force you into their ecosystem (vendor lock-in) or provide a thin wrapper that leaves you to build everything else yourself.

## Swarmline's Approach

Swarmline is a **modular, protocol-driven framework** built on Clean Architecture principles. Every component is an abstraction you can swap.

### 1. Protocol-First Design

Every interface in swarmline is a `typing.Protocol` with ≤5 methods (ISP). Your business code depends on abstractions — never on concrete implementations:

```python
# Your code depends on FactStore protocol
async def save_preference(store: FactStore, user_id: str, key: str, value: str):
    await store.upsert_fact(user_id, key, value)

# Works with ANY implementation:
save_preference(InMemoryMemoryProvider(), ...)   # dev
save_preference(PostgresMemoryProvider(...), ...) # production
save_preference(SQLiteMemoryProvider(...), ...)   # lightweight
```

### 2. Pluggable Runtimes

Same business code, different execution engines:

```python
# Development: fast, no subprocess
agent = Agent(AgentConfig(system_prompt="...", runtime="thin"))

# Production: full Claude ecosystem
agent = Agent(AgentConfig(system_prompt="...", runtime="claude_sdk"))

# Experiments: DeepAgents graph runtime
agent = Agent(AgentConfig(system_prompt="...", runtime="deepagents"))

# External CLI subprocess runtime
agent = Agent(AgentConfig(system_prompt="...", runtime="cli"))
```

All four runtimes implement the same `AgentRuntime` protocol. Your application code stays the same.

### 3. Composable Capabilities

Enable only what you need. Each capability is an independent toggle:

```python
stack = SwarmlineStack.create(
    prompts_dir="./prompts",
    skills_dir="./skills",
    project_root=".",
    # Pick and choose:
    sandbox_provider=sandbox,        # file I/O + bash
    web_provider=web,                # search + fetch
    todo_provider=todo,              # task tracking
    memory_bank_provider=memory,     # long-term knowledge
    thinking_enabled=True,           # chain-of-thought
    # plan_manager=plan_mgr,         # step-by-step execution
)
```

### 4. Security by Default

- **Default-deny tool policy** — tools are blocked unless explicitly allowed
- **`ALWAYS_DENIED` set** — dangerous tools (`Bash`, `Write`, `Edit`) require explicit whitelist
- **Sandboxed execution** — path traversal prevention, denied commands, file size limits, timeouts
- **Input validation** — SecurityGuard middleware blocks sensitive patterns

### 5. Multi-Provider Model Support

Use any LLM provider with human-friendly aliases:

| Provider | Models | Aliases |
| -------- | ------ | ------- |
| Anthropic | Claude Sonnet 4, Opus 4, Haiku 3 | `sonnet`, `opus`, `haiku` |
| OpenAI | GPT-4o, GPT-4o-mini, o3 | `gpt-4o`, `4o-mini`, `o3` |
| Google | Gemini 2.5 Pro, Flash | `gemini`, `gemini-flash` |
| DeepSeek | DeepSeek Chat, Reasoner (R1) | `deepseek`, `r1` |

## Design Principles

| Principle | How swarmline applies it |
| --------- | ----------------------- |
| **Clean Architecture** | Infrastructure → Application → Domain. Domain has zero external deps |
| **SOLID** | SRP (focused modules), OCP (extend via protocols), LSP (substitutable implementations), ISP (≤5 methods per protocol), DIP (depend on abstractions) |
| **DRY** | Shared protocols across 3 memory providers. One AgentRuntime contract for 4 runtimes |
| **KISS** | Agent facade: 3 lines for a working agent. Complexity opt-in via capabilities |
| **YAGNI** | No capability loads unless explicitly toggled. Core has 3 dependencies |

## When to Use Swarmline

**Good fit:**

- You're building a production AI agent that needs memory, tools, and observability
- You want to swap LLM providers or runtimes without code changes
- You need multi-user session management with persistent storage
- You value security (default-deny, sandboxing) and clean architecture
- You want to start simple (3 lines) and scale to complex (subagents, teams, planning)

**Not the best fit:**

- You just need a single LLM API call — use the provider SDK directly
- You're deeply committed to LangChain — use it directly (though swarmline integrates via `deepagents` runtime)
- You need a UI framework — swarmline is backend-only; pair with your preferred frontend
