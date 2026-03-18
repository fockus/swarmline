---
hide:
  - navigation
  - toc
---

<div class="home-shell">
  <section class="hero-panel">
    <div class="hero-grid">
      <div>
        <div class="eyebrow">One API · Four runtimes · Real agent infrastructure</div>
        <h1>Build agents once.<br>Choose the runtime later.</h1>
        <p class="hero-lead">
          Cognitia is a Python framework for teams that want production-ready agents without
          hard-coding the whole stack to one SDK, one provider, or one orchestration style.
          Start with a simple facade. Add tools, memory, sessions, workflows, and runtime-specific
          power only when you need them.
        </p>
        <div class="hero-actions">
          <a class="button-primary" href="getting-started/">Start in 5 minutes</a>
          <a class="button-secondary" href="use-cases/">See use cases</a>
          <a class="button-tertiary" href="runtimes/">Compare runtimes</a>
        </div>
        <div class="hero-proof">
          <span class="proof-pill">Thin runtime</span>
          <span class="proof-pill">Claude SDK</span>
          <span class="proof-pill">CLI runtime</span>
          <span class="proof-pill">DeepAgents</span>
          <span class="proof-pill">SQLite / PostgreSQL memory</span>
        </div>
      </div>

      <aside class="hero-card">
        <div class="terminal">
          <pre><code><span class="prompt">$</span> pip install cognitia[thin]

from cognitia import Agent, AgentConfig

agent = Agent(AgentConfig(
    system_prompt="You are a pragmatic research assistant.",
    runtime="thin",
))

result = await agent.query("Summarize the release plan")
print(result.text)</code></pre>
        </div>
        <p class="micro-note">
          Keep the same facade while moving between provider-backed, SDK-backed, CLI-wrapped,
          or graph-driven execution paths.
        </p>
      </aside>
    </div>
  </section>

  <section>
    <div class="section-intro">
      <div class="section-kicker">Why Cognitia</div>
      <h2>Designed for the moment when “just call the model” stops being enough.</h2>
      <p>
        Most agent projects become difficult when they need runtime portability, tool policies,
        persistent state, multi-turn sessions, or workflow control. Cognitia gives you one stable
        application surface and lets the infrastructure evolve underneath it.
      </p>
    </div>

    <div class="value-grid">
      <article class="value-card">
        <div class="card-top">
          <span class="mono-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M7 7h10v10H7z"></path>
              <path d="M4 12h3m10 0h3M12 4v3m0 10v3"></path>
            </svg>
          </span>
          <h3>Stable facade, swappable engine</h3>
        </div>
        <p>
          Start with one `Agent` API, then switch runtimes as requirements change: thin runtime for
          speed, Claude SDK for Claude-native workflows, CLI for existing agent tools, DeepAgents for graph-heavy paths.
        </p>
      </article>

      <article class="value-card">
        <div class="card-top">
          <span class="mono-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M4 7.5C4 5.57 7.58 4 12 4s8 1.57 8 3.5S16.42 11 12 11 4 9.43 4 7.5Z"></path>
              <path d="M4 12c0 1.93 3.58 3.5 8 3.5s8-1.57 8-3.5"></path>
              <path d="M4 16.5C4 18.43 7.58 20 12 20s8-1.57 8-3.5"></path>
            </svg>
          </span>
          <h3>Memory and sessions built in</h3>
        </div>
        <p>
          Use in-memory storage for prototypes, SQLite for local products, or PostgreSQL in production.
          Keep session state, facts, summaries, and runtime history behind the same protocol surface.
        </p>
      </article>

      <article class="value-card">
        <div class="card-top">
          <span class="mono-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M12 3l7 4v5c0 4.4-2.65 7.9-7 9-4.35-1.1-7-4.6-7-9V7l7-4Z"></path>
              <path d="m9.5 12 1.7 1.7 3.8-3.9"></path>
            </svg>
          </span>
          <h3>Guardrails without ceremony</h3>
        </div>
        <p>
          Add default-deny tool policy, security middleware, cost budgets, sandboxed execution,
          and explicit runtime contracts without inventing a second framework around your app.
        </p>
      </article>

      <article class="value-card">
        <div class="card-top">
          <span class="mono-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M4 19h16"></path>
              <path d="M7 15V9"></path>
              <path d="M12 15V5"></path>
              <path d="M17 15v-3"></path>
            </svg>
          </span>
          <h3>Structured, observable, testable</h3>
        </div>
        <p>
          Stream typed events, return structured output, hook into observability, and test portable
          behavior across runtimes instead of coupling tests to one provider SDK.
        </p>
      </article>
    </div>
  </section>

  <section>
    <div class="section-intro">
      <div class="section-kicker">Runtime Matrix</div>
      <h2>Choose the execution model that matches the job.</h2>
      <p>
        Cognitia is not one runtime pretending to fit every workload. It gives you a consistent
        application layer and lets you pick the runtime with the right trade-offs.
      </p>
    </div>

    <div class="runtime-grid">
      <article class="runtime-card">
        <div class="runtime-top">
          <div class="runtime-title">
            <span class="mono-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M6 4h12l2 4-8 12L4 8l2-4Z"></path>
                <path d="M9 8h6"></path>
              </svg>
            </span>
            <h3>Thin runtime</h3>
          </div>
          <span class="runtime-badge">Default</span>
        </div>
        <p>Fastest path to a working agent with tools, structured output, streaming, and provider portability.</p>
        <div class="runtime-meta">
          <div><strong>Best for</strong> New apps, internal assistants, product backends</div>
          <div><strong>Providers</strong> Anthropic, OpenAI-compatible, Gemini, DeepSeek, OpenRouter</div>
        </div>
      </article>

      <article class="runtime-card">
        <div class="runtime-top">
          <div class="runtime-title">
            <span class="mono-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M5 7.5 12 4l7 3.5v9L12 20l-7-3.5v-9Z"></path>
                <path d="M12 4v16"></path>
                <path d="M5 7.5 12 11l7-3.5"></path>
              </svg>
            </span>
            <h3>Claude SDK</h3>
          </div>
          <span class="runtime-badge">Claude-native</span>
        </div>
        <p>Use the Claude agent surface while keeping Cognitia’s facade, sessions, middleware, and docs model.</p>
        <div class="runtime-meta">
          <div><strong>Best for</strong> Claude-centric workflows and Claude tool ecosystems</div>
          <div><strong>Strength</strong> Native Claude execution semantics with a cleaner top-level app API</div>
        </div>
      </article>

      <article class="runtime-card">
        <div class="runtime-top">
          <div class="runtime-title">
            <span class="mono-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M4 6h16v12H4z"></path>
                <path d="m8 10 2 2-2 2"></path>
                <path d="M12 14h4"></path>
              </svg>
            </span>
            <h3>CLI runtime</h3>
          </div>
          <span class="runtime-badge">Wrap existing agents</span>
        </div>
        <p>Expose an NDJSON-emitting CLI as a Cognitia runtime and keep the same `query`, `stream`, and session surface.</p>
        <div class="runtime-meta">
          <div><strong>Best for</strong> Teams that already trust a CLI agent and want a cleaner integration layer</div>
          <div><strong>Strength</strong> Preserve external toolchains without rewriting your whole app</div>
        </div>
      </article>

      <article class="runtime-card">
        <div class="runtime-top">
          <div class="runtime-title">
            <span class="mono-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M4 7h6v4H4z"></path>
                <path d="M14 4h6v4h-6z"></path>
                <path d="M14 16h6v4h-6z"></path>
                <path d="M10 9h4M17 8v8"></path>
              </svg>
            </span>
            <h3>DeepAgents</h3>
          </div>
          <span class="runtime-badge">Graph-heavy</span>
        </div>
        <p>Bring in deeper workflow and graph semantics while preserving a simpler application entrypoint for the rest of your codebase.</p>
        <div class="runtime-meta">
          <div><strong>Best for</strong> Research systems, agent teams, graph-native orchestration</div>
          <div><strong>Strength</strong> Portable facade first, native graph power where you actually need it</div>
        </div>
      </article>
    </div>
  </section>

  <section>
    <div class="section-intro">
      <div class="section-kicker">Capabilities</div>
      <h2>Add the pieces you need, not a monolith you have to work around.</h2>
      <p>
        Cognitia stays modular: bring tools, memory, orchestration, structured output, web access,
        and production safety in gradually instead of adopting a giant runtime-shaped abstraction on day one.
      </p>
    </div>

    <div class="capability-grid">
      <article class="capability-card">
        <div class="card-top">
          <span class="mono-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M8 8h8v8H8z"></path>
              <path d="M4 12h4m8 0h4M12 4v4m0 8v4"></path>
            </svg>
          </span>
          <h3>Tooling surface</h3>
        </div>
        <p>Register Python functions with `@tool`, apply policy and middleware, then keep the tool contract stable across runtimes.</p>
        <a href="tools-and-skills/">Open tools and skills</a>
      </article>

      <article class="capability-card">
        <div class="card-top">
          <span class="mono-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M5 5h14v14H5z"></path>
              <path d="M9 9h6v6H9z"></path>
            </svg>
          </span>
          <h3>Structured output</h3>
        </div>
        <p>Return validated Pydantic or JSON Schema output without abandoning your runtime portability.</p>
        <a href="structured-output/">Open structured output</a>
      </article>

      <article class="capability-card">
        <div class="card-top">
          <span class="mono-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M4 7.5C4 5.57 7.58 4 12 4s8 1.57 8 3.5S16.42 11 12 11 4 9.43 4 7.5Z"></path>
              <path d="M4 12c0 1.93 3.58 3.5 8 3.5s8-1.57 8-3.5"></path>
              <path d="M4 16.5C4 18.43 7.58 20 12 20s8-1.57 8-3.5"></path>
            </svg>
          </span>
          <h3>Memory providers</h3>
        </div>
        <p>Promote the same app from in-memory prototypes to SQLite or PostgreSQL without replacing your agent surface.</p>
        <a href="memory/">Open memory providers</a>
      </article>

      <article class="capability-card">
        <div class="card-top">
          <span class="mono-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M3 6h18"></path>
              <path d="M6 3v6"></path>
              <path d="M18 3v6"></path>
              <path d="M6 14h4"></path>
              <path d="M14 14h4"></path>
              <path d="M6 18h4"></path>
              <path d="M14 18h4"></path>
            </svg>
          </span>
          <h3>Sessions and history</h3>
        </div>
        <p>Keep multi-turn context, runtime history, and rehydration paths explicit instead of hiding state in framework internals.</p>
        <a href="sessions/">Open sessions</a>
      </article>

      <article class="capability-card">
        <div class="card-top">
          <span class="mono-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M4 4h7v7H4z"></path>
              <path d="M13 4h7v7h-7z"></path>
              <path d="M13 13h7v7h-7z"></path>
              <path d="M4 16h4"></path>
              <path d="M8 13v7"></path>
            </svg>
          </span>
          <h3>Workflows and multi-agent</h3>
        </div>
        <p>Coordinate teams, queues, and workflow graphs without tying application code to one orchestration stack.</p>
        <a href="multi-agent/">Open multi-agent docs</a>
      </article>

      <article class="capability-card">
        <div class="card-top">
          <span class="mono-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M12 3v6"></path>
              <path d="M12 15v6"></path>
              <path d="M4.93 4.93l4.24 4.24"></path>
              <path d="M14.83 14.83l4.24 4.24"></path>
              <path d="M3 12h6"></path>
              <path d="M15 12h6"></path>
              <path d="M4.93 19.07l4.24-4.24"></path>
              <path d="M14.83 9.17l4.24-4.24"></path>
            </svg>
          </span>
          <h3>Observability and hooks</h3>
        </div>
        <p>Track event streams, middleware, and lifecycle hooks so the agent system stays explainable in production.</p>
        <a href="observability/">Open observability</a>
      </article>
    </div>
  </section>

  <section>
    <div class="section-intro">
      <div class="section-kicker">Use cases</div>
      <h2>Useful when your agent has to survive real product constraints.</h2>
      <p>
        Cognitia is strongest when you need runtime portability and long-lived agent behavior,
        not just a single provider call hidden inside one helper function.
      </p>
    </div>

    <div class="usecase-grid">
      <article class="usecase-card">
        <div class="card-top">
          <span class="mono-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M4 5h16v14H4z"></path>
              <path d="M8 9h8"></path>
              <path d="M8 13h5"></path>
            </svg>
          </span>
          <h3>Internal copilots</h3>
        </div>
        <p>Build assistants for operations, support, or internal tooling with tools, memory, and guardrails already wired in.</p>
        <div class="tag-row">
          <span class="tag">Tools</span>
          <span class="tag">Sessions</span>
          <span class="tag">Policy</span>
        </div>
      </article>

      <article class="usecase-card">
        <div class="card-top">
          <span class="mono-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <circle cx="11" cy="11" r="6"></circle>
              <path d="m20 20-3.5-3.5"></path>
              <path d="M11 8v6"></path>
              <path d="M8 11h6"></path>
            </svg>
          </span>
          <h3>Research and analysis</h3>
        </div>
        <p>Combine web access, memory, and structured output for reports, briefs, research copilots, and analysis workflows.</p>
        <div class="tag-row">
          <span class="tag">Web</span>
          <span class="tag">RAG</span>
          <span class="tag">Structured output</span>
        </div>
      </article>

      <article class="usecase-card">
        <div class="card-top">
          <span class="mono-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M4 8h16"></path>
              <path d="M4 16h10"></path>
              <path d="M17 13l3 3-3 3"></path>
            </svg>
          </span>
          <h3>Provider-agnostic backends</h3>
        </div>
        <p>Keep product APIs stable while swapping models or runtimes for cost, latency, compliance, or operational reasons.</p>
        <div class="tag-row">
          <span class="tag">Thin</span>
          <span class="tag">OpenRouter</span>
          <span class="tag">Runtime portability</span>
        </div>
      </article>

      <article class="usecase-card">
        <div class="card-top">
          <span class="mono-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M5 5h6v6H5z"></path>
              <path d="M13 13h6v6h-6z"></path>
              <path d="M11 8h2a3 3 0 0 1 3 3v2"></path>
              <path d="M13 5h6v6h-6z"></path>
            </svg>
          </span>
          <h3>Multi-agent systems</h3>
        </div>
        <p>Coordinate teams, queues, and workflow graphs without forcing the whole application into a graph-native mental model.</p>
        <div class="tag-row">
          <span class="tag">Task queue</span>
          <span class="tag">Teams</span>
          <span class="tag">Workflow graph</span>
        </div>
      </article>
    </div>
  </section>

  <section class="snippet-panel">
    <div class="section-intro">
      <div class="section-kicker">Quick win</div>
      <h2>Start small, then scale the system around it.</h2>
      <p>
        The fastest path is still simple: create an agent, ask a question, then add tools,
        sessions, or a different runtime when the product actually needs them.
      </p>
    </div>

    <div class="path-grid">
      <article class="path-card">
        <div class="path-step">1</div>
        <h3>Ask one useful question</h3>
        <div class="terminal">
          <pre><code>from cognitia import Agent, AgentConfig

agent = Agent(
    AgentConfig(
        system_prompt="You summarize release notes for engineers.",
        runtime="thin",
    )
)

result = await agent.query("Summarize the last deployment in 5 bullets.")
print(result.text)</code></pre>
        </div>
      </article>

      <article class="path-card">
        <div class="path-step">2</div>
        <h3>Add one tool</h3>
        <div class="terminal">
          <pre><code>from cognitia import tool

@tool
async def get_ticket_status(ticket_id: str) -> str:
    return f"{ticket_id}: in review"

agent = Agent(
    AgentConfig(
        system_prompt="You are a release assistant.",
        runtime="thin",
        tools=(get_ticket_status,),
    )
)</code></pre>
        </div>
      </article>

      <article class="path-card">
        <div class="path-step">3</div>
        <h3>Keep the conversation alive</h3>
        <div class="terminal">
          <pre><code>async with agent.conversation() as conv:
    await conv.say("My team owns checkout.")
    result = await conv.say("Which team owns checkout?")
    print(result.text)</code></pre>
        </div>
      </article>
    </div>
  </section>

  <section>
    <div class="section-intro">
      <div class="section-kicker">Learn fast</div>
      <h2>Use the docs by intent, not by file dump.</h2>
      <p>
        If you are evaluating the library, these are the shortest paths to understanding what it does,
        how to wire it, and where it fits in a real product stack.
      </p>
    </div>

    <div class="docs-grid">
      <article class="docs-card">
        <div class="card-top">
          <span class="mono-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M6 4h9l3 3v13H6z"></path>
              <path d="M15 4v4h4"></path>
            </svg>
          </span>
          <h3>Getting Started</h3>
        </div>
        <p>Install, set credentials, create your first agent, and understand the default happy path.</p>
        <a href="getting-started/">Read the quick start</a>
      </article>

      <article class="docs-card">
        <div class="card-top">
          <span class="mono-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M4 12h16"></path>
              <path d="M8 6h12"></path>
              <path d="M12 18h8"></path>
            </svg>
          </span>
          <h3>Runtimes</h3>
        </div>
        <p>See which runtime to use first, what changes across them, and where each one shines.</p>
        <a href="runtimes/">Read the runtime guide</a>
      </article>

      <article class="docs-card">
        <div class="card-top">
          <span class="mono-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <circle cx="8" cy="8" r="3"></circle>
              <circle cx="16" cy="16" r="3"></circle>
              <path d="M10.5 10.5 13.5 13.5"></path>
              <path d="M13.5 8.5h6"></path>
            </svg>
          </span>
          <h3>Use Cases</h3>
        </div>
        <p>Map your product idea to the right runtime, storage, and capability set before you overbuild.</p>
        <a href="use-cases/">Open use cases</a>
      </article>

      <article class="docs-card">
        <div class="card-top">
          <span class="mono-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M4 6h16"></path>
              <path d="M4 12h16"></path>
              <path d="M4 18h10"></path>
            </svg>
          </span>
          <h3>Cookbook</h3>
        </div>
        <p>Copy-paste recipes for tools, structured output, streaming, and common application patterns.</p>
        <a href="cookbook/">Open recipes</a>
      </article>

      <article class="docs-card">
        <div class="card-top">
          <span class="mono-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M5 5h14v14H5z"></path>
              <path d="M9 9h6v6H9z"></path>
            </svg>
          </span>
          <h3>Architecture</h3>
        </div>
        <p>Understand the protocol-first layering and how Cognitia keeps domain and infrastructure separated.</p>
        <a href="architecture/">Open architecture</a>
      </article>

      <article class="docs-card">
        <div class="card-top">
          <span class="mono-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M12 3v18"></path>
              <path d="M5 8h14"></path>
              <path d="M5 16h14"></path>
            </svg>
          </span>
          <h3>Credentials &amp; Providers</h3>
        </div>
        <p>Wire env vars and provider settings correctly for Thin, Claude SDK, CLI, and DeepAgents paths.</p>
        <a href="credentials/">Open provider setup</a>
      </article>
    </div>
  </section>

  <section class="final-cta">
    <h2>Good fit if you want agent infrastructure without framework lock-in.</h2>
    <p>
      Cognitia is strongest when you care about runtime portability, session state, tools,
      storage, and gradual adoption. Start with the default facade now, then layer in the rest
      only when your product actually demands it.
    </p>
    <div class="hero-actions">
      <a class="button-primary" href="getting-started/">Build your first agent</a>
      <a class="button-secondary" href="why-cognitia/">See when Cognitia is the right tool</a>
    </div>
  </section>
</div>
