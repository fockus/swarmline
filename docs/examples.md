# Examples

The runnable examples live in [`examples/`](https://github.com/fockus/cognitia/tree/main/examples).
They are designed as release-surface smoke targets: default invocation should exit cleanly,
write useful output to `stdout`, and stay quiet on `stderr`.

## Running

```bash
pip install -e ".[dev,all]"
python examples/01_agent_basics.py
```

Default behavior:

- Examples `01-23` run offline with mock data.
- Examples `24-27` run mock/demo flows by default.
- Examples `24` and `27` also expose optional `--live` modes guarded by `ANTHROPIC_API_KEY` or `OPENROUTER_API_KEY`.
- Examples `25` and `26` are intentionally mock-only demos.

## Catalog

### Getting Started (01-03)

| # | File | What it demonstrates |
|---|------|----------------------|
| 01 | `01_agent_basics.py` | Agent facade: `query()`, `stream()`, `conversation()` |
| 02 | `02_tool_decorator.py` | `@tool` decorator and inferred JSON Schema |
| 03 | `03_structured_output.py` | Structured output validation with Pydantic |

### Processing Pipeline (04-07)

| # | File | What it demonstrates |
|---|------|----------------------|
| 04 | `04_middleware_chain.py` | Middleware composition: cost, security, compression |
| 05 | `05_hooks.py` | Lifecycle hooks: `PreToolUse`, `PostToolUse`, `Stop` |
| 06 | `06_input_filters.py` | Input pre-processing and prompt shaping |
| 07 | `07_guardrails.py` | Input/output safety guardrails |

### Data & Context (08-10)

| # | File | What it demonstrates |
|---|------|----------------------|
| 08 | `08_rag.py` | Retrieval-augmented generation with `SimpleRetriever` |
| 09 | `09_memory_providers.py` | Memory providers: messages, facts, goals, summaries |
| 10 | `10_sessions.py` | Session persistence, scopes, and scoped keys |

### Safety & Resilience (11-14)

| # | File | What it demonstrates |
|---|------|----------------------|
| 11 | `11_cost_budget.py` | Cost budget tracking and enforcement |
| 12 | `12_retry_fallback.py` | Retry policies, fallback chains, circuit breaker |
| 13 | `13_cancellation.py` | Cooperative cancellation |
| 14 | `14_thinking_tool.py` | Structured reasoning with the thinking tool |

### Observability (15-16)

| # | File | What it demonstrates |
|---|------|----------------------|
| 15 | `15_event_bus_tracing.py` | Event bus and tracing subscriber |
| 16 | `16_ui_projection.py` | Projecting runtime events into UI state |

### Runtimes (17-19)

| # | File | What it demonstrates |
|---|------|----------------------|
| 17 | `17_runtime_switching.py` | Comparing runtime capabilities and switching runtimes |
| 18 | `18_custom_runtime.py` | Registering a custom runtime in `RuntimeRegistry` |
| 19 | `19_cli_runtime.py` | CLI subprocess runtime and NDJSON parsing |

### Orchestration (20-23)

| # | File | What it demonstrates |
|---|------|----------------------|
| 20 | `20_workflow_graph.py` | Declarative workflow graph with loops and HITL |
| 21 | `21_agent_as_tool.py` | Agent-as-tool composition |
| 22 | `22_task_queue.py` | Priority task queue |
| 23 | `23_agent_registry.py` | Agent registry and lifecycle tracking |

### Complex Scenarios (24-27)

| # | File | What it demonstrates |
|---|------|----------------------|
| 24 | `24_deep_research.py` | Multi-step research pipeline with optional `--live` mode |
| 25 | `25_shopping_agent.py` | Shopping assistant with HITL and parallel search |
| 26 | `26_code_project_team.py` | Multi-agent development team workflow |
| 27 | `27_nano_claw.py` | Claude Code-like CLI assistant with optional `--live` mode |

### Integrations (28+)

| # | File | What it demonstrates |
|---|------|----------------------|
| 28 | `28_opentelemetry_tracing.py` | OpenTelemetry span export from EventBus events |
| 29 | `29_structured_output_pydantic.py` | Type-safe structured output with `Agent.query_structured()` |
| 30 | `30_a2a_agent.py` | A2A protocol: expose agent as service, send tasks, streaming |

## Picking a Starting Point

- Start with `01`, `02`, `03` if you are new to the facade API.
- Jump to `17`, `18`, `19` if you are evaluating runtime integration.
- Use `20-23` for orchestration and multi-agent primitives.
- Use `24-27` when you want end-to-end demo scenarios instead of isolated features.

## Notes on Live Modes

When a live mode is available, the example should fail fast if required credentials are
missing instead of silently falling back to mock behavior:

```bash
python examples/24_deep_research.py --live
python examples/27_nano_claw.py --live
```

Both commands require either `ANTHROPIC_API_KEY` or `OPENROUTER_API_KEY`.
