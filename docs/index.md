---
hide:
  - navigation
  - toc
---

<div class="hero" markdown>

# Cognitia

<p class="hero-subtitle">
LLM-agnostic Python framework for building production AI agents.<br>
Pluggable runtimes. Persistent memory. Secure by default.
</p>

<div class="hero-buttons">
<a href="getting-started/" class="btn-primary">Get Started</a>
<a href="https://github.com/fockus/cognitia" class="btn-secondary">GitHub</a>
</div>
</div>

<div class="stats-bar" markdown>
<div class="stat-item">
<span class="stat-number">3</span>
<span class="stat-label">Runtimes</span>
</div>
<div class="stat-item">
<span class="stat-number">14</span>
<span class="stat-label">Protocols</span>
</div>
<div class="stat-item">
<span class="stat-number">4</span>
<span class="stat-label">LLM Providers</span>
</div>
<div class="stat-item">
<span class="stat-number">1200+</span>
<span class="stat-label">Tests</span>
</div>
</div>

<div class="terminal" markdown>
<code><span class="prompt">$</span> pip install cognitia[thin]</code>
</div>

---

## Build agents in 3 lines

```python
from cognitia import Agent, AgentConfig

agent = Agent(AgentConfig(system_prompt="You are a helpful assistant.", runtime="thin"))
result = await agent.query("What is the capital of France?")
print(result.text)  # "The capital of France is Paris."
```

No config files. No boilerplate. Just an agent that works.

---

<div class="section-header" markdown>

## Why Cognitia?

Every component is a Python Protocol you can swap.

</div>

<div class="feature-grid" markdown>

<div class="feature-card" markdown>
<div class="feature-icon">🔌</div>

### Pluggable Runtimes

Three interchangeable runtimes — `thin` (built-in async loop), `claude_sdk` (Claude Agent SDK), `deepagents` (LangChain). Same business code, different engines.
</div>

<div class="feature-card" markdown>
<div class="feature-icon">🧠</div>

### Persistent Memory

Three storage backends (InMemory, SQLite, PostgreSQL) implementing 8 memory protocols. Facts, goals, summaries, session state — all persisted.
</div>

<div class="feature-card" markdown>
<div class="feature-icon">🛡️</div>

### Secure by Default

Default-deny tool policy. Sandboxed execution. Input validation middleware. Dangerous tools require explicit allowlisting.
</div>

<div class="feature-card" markdown>
<div class="feature-icon">🌐</div>

### Multi-Provider Models

Anthropic, OpenAI, Google, DeepSeek — use any provider with human-friendly aliases. `"sonnet"`, `"gpt-4o"`, `"gemini"`, `"r1"` just work.
</div>

<div class="feature-card" markdown>
<div class="feature-icon">🔧</div>

### Tools & MCP Skills

`@tool` decorator with auto JSON Schema inference. Declarative YAML MCP skills. Role-based tool mapping with priority budgets.
</div>

<div class="feature-card" markdown>
<div class="feature-icon">📐</div>

### Clean Architecture

14 ISP-compliant protocols (≤5 methods each). Dependencies point inward only. Domain has zero external dependencies.
</div>

</div>

---

<div class="section-header" markdown>

## Switch providers without changing code

One config change — your business logic stays the same.

</div>

=== "Anthropic (Claude)"

    ```python
    agent = Agent(AgentConfig(
        system_prompt="You are a helpful assistant.",
        runtime="thin",
        model="sonnet",  # Claude Sonnet 4
    ))
    ```

=== "OpenAI (GPT-4o)"

    ```python
    agent = Agent(AgentConfig(
        system_prompt="You are a helpful assistant.",
        runtime="thin",
        model="gpt-4o",
    ))
    ```

=== "Google (Gemini)"

    ```python
    agent = Agent(AgentConfig(
        system_prompt="You are a helpful assistant.",
        runtime="thin",
        model="gemini",  # Gemini 2.5 Pro
    ))
    ```

=== "DeepSeek (R1)"

    ```python
    agent = Agent(AgentConfig(
        system_prompt="You are a helpful assistant.",
        runtime="thin",
        model="r1",  # DeepSeek Reasoner
    ))
    ```

<div class="provider-row" markdown>
<span class="provider-badge">Anthropic</span>
<span class="provider-badge">OpenAI</span>
<span class="provider-badge">Google</span>
<span class="provider-badge">DeepSeek</span>
</div>

---

<div class="section-header" markdown>

## Swap runtimes, keep your code

Same API surface — different execution engines underneath.

</div>

=== "Thin Runtime"

    ```python
    # Built-in lightweight async loop
    # Direct API calls, no subprocess, fastest startup
    agent = Agent(AgentConfig(
        system_prompt="...",
        runtime="thin",
    ))
    ```

    Best for: fast prototyping, alternative LLMs, direct API control.

=== "Claude SDK"

    ```python
    # Full Claude Agent SDK with native MCP support
    # Subprocess-based, supports resume/interrupt
    agent = Agent(AgentConfig(
        system_prompt="...",
        runtime="claude_sdk",
    ))
    ```

    Best for: production Claude deployments, MCP ecosystem, native permissions.

=== "DeepAgents"

    ```python
    # LangChain/LangGraph integration
    # Access to the entire LangChain ecosystem
    agent = Agent(AgentConfig(
        system_prompt="...",
        runtime="deepagents",
    ))
    ```

    Best for: LangChain workflows, existing LangGraph pipelines, multi-framework setups.

---

<div class="section-header" markdown>

## Composable Capabilities

Enable only what you need. Each capability is an independent toggle.

</div>

| Capability | What it does | Tools provided |
| ----------- | ------------- | ---------------- |
| **Sandbox** | Isolated file I/O and command execution | `bash`, `read`, `write`, `edit`, `glob`, `grep` |
| **Web** | Internet access with pluggable providers | `web_fetch`, `web_search` |
| **Todo** | Structured task tracking | `todo_read`, `todo_write` |
| **Memory Bank** | Persistent knowledge across sessions | `memory_read`, `memory_write`, `memory_list` |
| **Planning** | Step-by-step task decomposition | `plan_create`, `plan_status`, `plan_execute` |
| **Thinking** | Chain-of-thought reasoning | `thinking` |

---

<div class="section-header" markdown>

## Custom tools in seconds

Type hints become JSON Schema automatically.

</div>

```python
from cognitia import Agent, AgentConfig, tool

@tool(name="weather", description="Get current weather for a city")
async def get_weather(city: str, units: str = "celsius") -> str:
    return f"Weather in {city}: 22 {units}"

agent = Agent(AgentConfig(
    system_prompt="You are a weather assistant.",
    runtime="thin",
    tools=(get_weather,),
))
result = await agent.query("What's the weather in Tokyo?")
```

!!! info "Type mapping"
    `str` → `"string"` · `int` → `"integer"` · `float` → `"number"` · `bool` → `"boolean"` · `Optional[T]` → nullable

---

<div class="section-header" markdown>

## Multi-turn conversations

Context preserved automatically across turns.

</div>

```python
async with agent.conversation() as conv:
    r1 = await conv.say("My name is Alice")
    r2 = await conv.say("What's my name?")
    print(r2.text)  # "Your name is Alice."

    # Streaming works too
    async for event in conv.stream("Tell me a joke"):
        if event.type == "text_delta":
            print(event.text, end="", flush=True)
```

---

<div class="section-header" markdown>

## Built-in safety

Cost tracking, input filtering, and budget enforcement — out of the box.

</div>

```python
from cognitia.agent import CostTracker, SecurityGuard

tracker = CostTracker(budget_usd=5.0)
guard = SecurityGuard(blocked_patterns=["password", "secret", "api_key"])

agent = Agent(AgentConfig(
    system_prompt="You are a helpful assistant.",
    runtime="thin",
    middleware=(tracker, guard),
))

result = await agent.query("Hello!")
print(tracker.total_cost_usd)  # 0.002
```

---

<div class="section-header" markdown>

## Production-ready architecture

</div>

```
Your Application
       │
       ▼ depends on protocols (DIP)
╔═══════════════════════════════════════════════════╗
║                    Cognitia                        ║
║                                                    ║
║  ┌──────────────────────────────────────────────┐  ║
║  │  Agent Facade                                │  ║
║  │  Agent · AgentConfig · @tool · Middleware     │  ║
║  └─────────────────┬────────────────────────────┘  ║
║                    │                                ║
║  ┌─────────────────▼────────────────────────────┐  ║
║  │  14 Protocols (ISP: ≤5 methods each)         │  ║
║  │  MessageStore · FactStore · AgentRuntime ...  │  ║
║  └─────────────────┬────────────────────────────┘  ║
║                    │                                ║
║  ┌─────────────────▼────────────────────────────┐  ║
║  │  Implementations                             │  ║
║  │  memory/   InMemory │ PostgreSQL │ SQLite    │  ║
║  │  runtime/  thin │ claude_sdk │ deepagents    │  ║
║  │  tools/    Sandbox · Web · Todo · MemoryBank │  ║
║  └──────────────────────────────────────────────┘  ║
╚═══════════════════════════════════════════════════╝
```

<div class="cta-section" markdown>

## Ready to build?

<div class="hero-buttons" markdown>
<a href="getting-started/" class="btn-primary">Get Started</a>
<a href="api-reference/" class="btn-secondary">API Reference</a>
</div>

<br>

```bash
pip install cognitia[thin]
```

</div>
