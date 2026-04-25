# Swarmline Examples

Standalone runnable examples demonstrating Swarmline features.
Examples 01-23 use mock data and run without API keys.
Complex scenarios (24-27) run mock pipelines by default.
Examples 24 and 27 also expose optional `--live` modes with `ANTHROPIC_API_KEY` or `OPENROUTER_API_KEY`; 25 and 26 are mock-only demos.

## Running

```bash
pip install -e ".[dev,all]"
python examples/01_agent_basics.py
```

## Examples

### Getting Started (01-03)

| # | File | Feature | Key Imports |
|---|------|---------|-------------|
| 01 | `01_agent_basics.py` | Agent facade: query, stream, conversation | `Agent`, `AgentConfig`, `Conversation` |
| 02 | `02_tool_decorator.py` | `@tool` decorator with type hints | `tool`, `ToolDefinition` |
| 03 | `03_structured_output.py` | Pydantic structured output | `validate_structured_output`, `extract_pydantic_schema` |

### Processing Pipeline (04-07)

| # | File | Feature | Key Imports |
|---|------|---------|-------------|
| 04 | `04_middleware_chain.py` | Middleware: cost, security, compression | `CostTracker`, `SecurityGuard`, `ToolOutputCompressor` |
| 05 | `05_hooks.py` | Lifecycle hooks: pre/post tool use | `HookRegistry` |
| 06 | `06_input_filters.py` | Input pre-processing | `MaxTokensFilter`, `SystemPromptInjector` |
| 07 | `07_guardrails.py` | Input/output safety checks | `ContentLengthGuardrail`, `RegexGuardrail`, `CallerAllowlistGuardrail` |

### Data & Context (08-10)

| # | File | Feature | Key Imports |
|---|------|---------|-------------|
| 08 | `08_rag.py` | Retrieval-augmented generation | `SimpleRetriever`, `RagInputFilter`, `Document` |
| 09 | `09_memory_providers.py` | Memory: messages, facts, goals, summaries | `InMemoryMemoryProvider` |
| 10 | `10_sessions.py` | Session persistence + scopes | `InMemorySessionBackend`, `MemoryScope`, `scoped_key` |

### Safety & Resilience (11-14)

| # | File | Feature | Key Imports |
|---|------|---------|-------------|
| 11 | `11_cost_budget.py` | Cost budget tracking and enforcement | `CostBudget`, `CostTracker`, `ModelPricing` |
| 12 | `12_retry_fallback.py` | Retry, fallback chains, circuit breaker | `ExponentialBackoff`, `ModelFallbackChain`, `CircuitBreaker` |
| 13 | `13_cancellation.py` | Cooperative async cancellation | `CancellationToken` |
| 14 | `14_thinking_tool.py` | CoT + ReAct structured reasoning | `create_thinking_tool` |

### Observability (15-16)

| # | File | Feature | Key Imports |
|---|------|---------|-------------|
| 15 | `15_event_bus_tracing.py` | Pub-sub events + span tracing | `InMemoryEventBus`, `NoopTracer`, `TracingSubscriber` |
| 16 | `16_ui_projection.py` | Event stream to UI state | `ChatProjection`, `project_stream`, `UIState` |

### Runtimes (17-19)

| # | File | Feature | Key Imports |
|---|------|---------|-------------|
| 17 | `17_runtime_switching.py` | Compare and switch runtimes | `RuntimeFactory`, `RuntimeRegistry`, `RuntimeCapabilities` |
| 18 | `18_custom_runtime.py` | Register custom runtime | `RuntimeRegistry.register()` |
| 19 | `19_cli_runtime.py` | CLI subprocess runtime + NDJSON | `CliAgentRuntime`, `CliConfig`, `ClaudeNdjsonParser` |

### Orchestration (20-23)

| # | File | Feature | Key Imports |
|---|------|---------|-------------|
| 20 | `20_workflow_graph.py` | Declarative graphs: conditions, loops, HITL | `WorkflowGraph`, `InMemoryCheckpoint`, `WorkflowInterrupt` |
| 21 | `21_agent_as_tool.py` | Agent calls another agent | `execute_agent_tool`, `create_agent_tool_spec` |
| 22 | `22_task_queue.py` | Priority task queue | `InMemoryTaskQueue`, `TaskItem`, `TaskPriority` |
| 23 | `23_agent_registry.py` | Agent lifecycle management | `InMemoryAgentRegistry`, `AgentRecord`, `AgentStatus` |

### Complex Scenarios (24-27)

| # | File | Feature | Key Imports |
|---|------|---------|-------------|
| 24 | `24_deep_research.py` | Multi-step research agent | `WorkflowGraph`, `@tool`, `SimpleRetriever`, structured output |
| 25 | `25_shopping_agent.py` | Shopping assistant with HITL | `WorkflowGraph` interrupts, parallel search, structured output |
| 26 | `26_code_project_team.py` | Multi-agent dev team | `AgentRegistry`, `TaskQueue`, `WorkflowGraph` |
| 27 | `27_nano_claw.py` | Simple Claude Code-like CLI agent | `Agent`, `@tool`, `Conversation`, streaming |
