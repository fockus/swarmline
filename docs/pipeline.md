# Pipeline Engine

Multi-phase execution engine for Swarmline agent graphs with quality gates, budget tracking, and circuit breakers. This subsystem was introduced in v1.2.0.

## Overview

The Pipeline Engine orchestrates agent work across sequential phases. Each phase runs an agent graph through the orchestrator, and between phases the engine runs quality gates that decide whether execution should continue. Budget tracking enforces cost limits at the total, per-phase, and per-agent level.

**When to use the Pipeline Engine:**

- You need structured multi-step agent workflows (plan, execute, review, etc.)
- You want automatic cost control with hard limits and warnings
- You need quality checkpoints between stages (tests pass, lint clean, code review)
- You want circuit breaker protection against cascading agent failures

**Key components:**

| Component | Purpose |
|-----------|---------|
| `PipelineBuilder` | Fluent DSL to wire phases, gates, budget, and agents |
| `Pipeline` | Execution engine that runs phases sequentially |
| `PipelineRunner` | Convenience wrapper with event callbacks |
| `BudgetTracker` | In-memory cost tracking and enforcement |
| `PersistentBudgetStore` | Cross-run budget tracking with time windows |
| `QualityGate` | Protocol for verification checkpoints between phases |

## Quick Start

```python
from swarmline.pipeline import PipelineBuilder, BudgetPolicy

async def my_runner(agent_id: str, task_id: str, goal: str, system_prompt: str) -> str:
    """Your LLM runner — called for each agent execution."""
    # Call your LLM here
    return "task completed"

pipeline = await (
    PipelineBuilder()
    .with_agents_from_yaml("agents.yaml")
    .with_runner(my_runner)
    .add_phase("plan", "Planning", "Decompose the goal into tasks")
    .add_phase("exec", "Execution", "Execute all planned tasks")
    .add_phase("review", "Review", "Review and validate results")
    .with_budget(BudgetPolicy(max_total_usd=10.0))
    .build()
)

result = await pipeline.run("Build a REST API for user management")

print(result.status)                # "completed" | "failed" | "stopped"
print(result.total_duration_seconds)
print(result.total_cost_usd)

for phase_result in result.phases:
    print(f"{phase_result.phase_id}: {phase_result.status.value}")
```

## PipelineBuilder DSL

`PipelineBuilder` is a fluent API that wires all pipeline components. Components not explicitly provided get in-memory defaults.

### Agent Graph

Three ways to provide the agent graph:

```python
# From a YAML file
builder = PipelineBuilder().with_agents_from_yaml("org.yaml")

# From a dictionary config
builder = PipelineBuilder().with_agents_from_dict({
    "root": {"name": "CEO", "role": "coordinator"},
    "dev":  {"name": "Developer", "role": "engineer", "parent": "root"},
})

# From a pre-built graph store
builder = PipelineBuilder().with_graph(my_graph_store)
```

### Phases

Phases are added in order of execution:

```python
builder = (
    PipelineBuilder()
    .add_phase("plan", "Planning", "Break the goal into subtasks")
    .add_phase("exec", "Execution", "Execute planned tasks", timeout_seconds=300)
    .add_phase("test", "Testing", "Run tests", agent_filter="tester")
)
```

Parameters:

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | `str` | Unique phase identifier |
| `name` | `str` | Human-readable name |
| `goal` | `str` | Goal description passed to the orchestrator |
| `agent_filter` | `str \| None` | Role filter -- which agents work on this phase |
| `timeout_seconds` | `float \| None` | Phase timeout (None = no limit) |

### Gates

Add quality gates that run after a specific phase:

```python
from swarmline.pipeline import CallbackGate, CompositeGate

# Callback gate -- simple async function
async def tests_pass(phase_id: str, results: dict) -> bool:
    # Run your verification logic
    return True

builder.add_callback_gate("exec", "tests_pass", tests_pass)

# Or add a gate object directly
builder.add_gate("exec", my_custom_gate)
```

### Budget

```python
from swarmline.pipeline import BudgetPolicy

builder.with_budget(BudgetPolicy(
    max_total_usd=10.0,
    max_per_phase_usd=5.0,
    max_per_agent_usd=2.0,
    warn_at_percent=80.0,
))
```

### Additional Options

```python
builder = (
    PipelineBuilder()
    # ... phases, agents, runner ...
    .with_event_bus(my_event_bus)           # Lifecycle events
    .with_max_concurrent(3)                 # Max concurrent agent executions
    .with_circuit_breaker(threshold=3, cooldown=30.0)  # Per-agent circuit breaker
    .with_task_board(my_task_board)         # Custom task board
    .with_communication(my_comm)           # Custom communication backend
)
```

### Build

`build()` is async -- it assembles all components and returns a ready-to-run `Pipeline`:

```python
pipeline = await builder.build()
```

Requirements:
- A runner is required (`.with_runner()`)
- At least one phase is required (`.add_phase()`)

Missing components get in-memory defaults:
- `InMemoryAgentGraph` for the graph store
- `InMemoryGraphTaskBoard` for the task board
- `InMemoryGraphCommunication` for communication
- `InMemoryEventBus` for the event bus

## Phases

A `PipelinePhase` is a frozen dataclass defining one stage of the pipeline.

```python
from swarmline.pipeline import PipelinePhase

phase = PipelinePhase(
    id="exec",
    name="Execution",
    goal="Execute all planned tasks",
    agent_filter="engineer",  # Only agents with this role participate
    order=1,                  # Execution order (lower first)
    timeout_seconds=300.0,    # Phase timeout
    metadata={"retry": True}, # Arbitrary metadata
)
```

### Phase Lifecycle

Each phase goes through these statuses (`PhaseStatus`):

| Status | Meaning |
|--------|---------|
| `PENDING` | Not yet started |
| `RUNNING` | Currently executing |
| `GATE_CHECK` | Running quality gates |
| `COMPLETED` | Finished successfully, all gates passed |
| `FAILED` | Execution error, timeout, budget exceeded, or gate failure |
| `SKIPPED` | Skipped because a previous phase failed or the pipeline was stopped |

### Phase Results

```python
from swarmline.pipeline import PhaseResult

# After pipeline.run():
for phase_result in result.phases:
    print(phase_result.phase_id)
    print(phase_result.status)            # PhaseStatus enum
    print(phase_result.duration_seconds)
    print(phase_result.gate_results)      # Tuple of GateResult
    print(phase_result.error)             # Error message if failed
```

## Gates

Quality gates are verification checkpoints that run after each phase. If any gate fails, the pipeline stops and marks remaining phases as `SKIPPED`.

### QualityGate Protocol

```python
from swarmline.pipeline import QualityGate, GateResult

class MyGate:
    async def check(self, phase_id: str, results: dict[str, Any]) -> GateResult:
        passed = run_my_checks()
        return GateResult(
            passed=passed,
            gate_name="my_gate",
            details="All checks passed" if passed else "Lint errors found",
        )
```

The `results` dict contains `{"goal": str, "run_id": str}` from the phase execution.

### CallbackGate

For simple cases, wrap an async function:

```python
from swarmline.pipeline import CallbackGate

async def check_tests(phase_id: str, results: dict) -> bool:
    # Return True if tests pass
    return True

gate = CallbackGate("test_suite", check_tests)
```

### CompositeGate

Chain multiple gates -- all must pass:

```python
from swarmline.pipeline import CompositeGate

composite = CompositeGate([gate_lint, gate_tests, gate_coverage])
# Runs gates in order, stops on first failure
```

### GateResult

```python
from swarmline.pipeline import GateResult

# Returned by gate.check()
result = GateResult(
    passed=True,
    gate_name="tests",
    details="42 tests passed",
    # timestamp auto-set
)
```

## Budget

Budget tracking operates at two levels: in-pipeline tracking (`BudgetTracker`) for a single run, and persistent tracking (`PersistentBudgetStore`) across runs.

### BudgetPolicy

Defines limits for a pipeline run:

```python
from swarmline.pipeline import BudgetPolicy

policy = BudgetPolicy(
    max_total_usd=10.0,        # Total budget for the entire pipeline
    max_per_phase_usd=5.0,     # Max cost per individual phase
    max_per_agent_usd=2.0,     # Max cost per individual agent
    warn_at_percent=80.0,      # Emit warning event at this threshold
)
```

### BudgetTracker

In-memory tracker for a single pipeline run. Created automatically by `PipelineBuilder` when you call `.with_budget()`.

```python
from swarmline.pipeline import BudgetTracker, BudgetPolicy, CostRecord

tracker = BudgetTracker(BudgetPolicy(max_total_usd=5.0))

# Record a cost entry
tracker.record(CostRecord(
    agent_id="dev-1",
    task_id="task-42",
    phase_id="exec",
    cost_usd=0.05,
    tokens_in=1000,
    tokens_out=500,
    duration_seconds=2.3,
))

# Check limits
tracker.total_cost()              # 0.05
tracker.phase_cost("exec")       # 0.05
tracker.agent_cost("dev-1")      # 0.05
tracker.is_exceeded()            # False
tracker.is_phase_exceeded("exec") # False
```

#### Runner Wrapping

`BudgetTracker.wrap_runner()` wraps your agent runner to automatically check budget before each call and record costs after:

```python
def extract_cost(result: str) -> float:
    """Parse cost from runner result."""
    return 0.01  # Your extraction logic

wrapped_runner = tracker.wrap_runner(
    my_runner,
    phase_id="exec",
    cost_extractor=extract_cost,
)
```

When the budget is exceeded, the wrapped runner raises `BudgetExceededError`.

### PersistentBudgetStore

Cross-run budget tracking with time windows. Two implementations are provided.

#### Scopes and Windows

```python
from swarmline.pipeline import BudgetScope, BudgetScopeType, BudgetWindow

# Track by agent, graph, or tenant
scope = BudgetScope(scope_type=BudgetScopeType.AGENT, scope_id="dev-1")

# Aggregate over monthly or lifetime windows
window = BudgetWindow.MONTHLY   # Resets each month
window = BudgetWindow.LIFETIME  # Cumulative, never resets
```

#### InMemoryPersistentBudgetStore

For testing and development:

```python
from swarmline.pipeline import (
    InMemoryPersistentBudgetStore,
    BudgetScope,
    BudgetScopeType,
    BudgetWindow,
    BudgetThreshold,
)

store = InMemoryPersistentBudgetStore()

scope = BudgetScope(scope_type=BudgetScopeType.TENANT, scope_id="acme-corp")

# Register a threshold
store.register_threshold(BudgetThreshold(
    scope=scope,
    window=BudgetWindow.MONTHLY,
    limit_usd=100.0,
    warn_at_percent=80.0,
    hard_stop=True,
))

# Record costs
await store.record_cost(scope, 25.0, "pipeline run #1")
await store.record_cost(scope, 30.0, "pipeline run #2")

# Check usage
usage = await store.get_usage(scope, BudgetWindow.MONTHLY)  # 55.0

# Check threshold
result = await store.check_threshold(scope, BudgetWindow.MONTHLY)
print(result.percent)   # 55.0
print(result.action)    # ThresholdAction.OK

# List incidents (warnings and stops)
incidents = await store.list_incidents(scope)
```

#### SqlitePersistentBudgetStore

File-based persistence with WAL mode for concurrent reads:

```python
from swarmline.pipeline import SqlitePersistentBudgetStore

store = SqlitePersistentBudgetStore(db_path="budget.db")

# Same API as InMemoryPersistentBudgetStore
await store.record_cost(scope, 10.0, "run #1")
usage = await store.get_usage(scope, BudgetWindow.LIFETIME)

# Close when done
store.close()
```

Uses `asyncio.to_thread()` internally to avoid blocking the event loop.

#### Threshold Actions

When `check_threshold()` detects a breach, it returns a `ThresholdResult` with one of:

| Action | Meaning |
|--------|---------|
| `ThresholdAction.OK` | Within budget |
| `ThresholdAction.WARN` | Usage >= `warn_at_percent` but below limit |
| `ThresholdAction.STOP` | Usage >= 100% and `hard_stop=True` |

Breaches are automatically recorded as `BudgetIncident` entries and emitted as `pipeline.budget.threshold_exceeded` events.

## Execution

### Pipeline.run()

Runs all phases sequentially. Between each phase, quality gates are checked. The pipeline stops on first failure.

```python
result = await pipeline.run("Build a REST API")
```

Execution flow for each phase:

1. **Budget check** -- is the total or phase budget exceeded?
2. **Run phase** -- execute via orchestrator (with optional timeout)
3. **Quality gates** -- run all gates registered for this phase
4. **Result** -- `COMPLETED` if all gates pass, `FAILED` otherwise

If a phase fails, all remaining phases are marked `SKIPPED`.

### Pipeline.run_phase()

Run a single phase by ID:

```python
phase_result = await pipeline.run_phase("exec")
```

### Pipeline.stop()

Gracefully stop the pipeline. The current phase finishes, remaining phases are skipped:

```python
await pipeline.stop()
```

### Pipeline.get_status()

Inspect the pipeline state during execution:

```python
status = pipeline.get_status()
# {
#     "current_phase": "exec",
#     "stopped": False,
#     "completed_phases": 1,
#     "total_phases": 3,
#     "phase_results": [{"phase_id": "plan", "status": "completed"}],
# }
```

### PipelineResult

Aggregate result returned by `pipeline.run()`:

```python
result = await pipeline.run(goal)

result.status                  # "completed" | "failed" | "stopped"
result.total_duration_seconds  # Wall clock time for entire run
result.total_cost_usd          # Sum of all cost records
result.phases                  # Tuple[PhaseResult, ...]
```

### PipelineRunner

Convenience wrapper with event callbacks:

```python
from swarmline.pipeline import PipelineRunner

runner = PipelineRunner(pipeline)

# Register callbacks
runner.on_phase_complete(lambda event: print(f"Phase done: {event}"))
runner.on_budget_warning(lambda event: print(f"Budget warning: {event}"))

result = await runner.run_all("Build the system")

# Or run a single phase
phase_result = await runner.run_phase("plan")

# Check status
print(runner.get_status())

# Stop
await runner.stop()
```

### Event Bus Topics

The pipeline emits events through the event bus during execution:

| Topic | Data | When |
|-------|------|------|
| `pipeline.started` | `goal`, `phase_count` | Pipeline run begins |
| `pipeline.completed` | `status` | Pipeline run ends |
| `pipeline.stopped` | `{}` | Pipeline stopped via `stop()` |
| `pipeline.phase.started` | `phase_id`, `name` | Phase begins |
| `pipeline.phase.completed` | `phase_id` | Phase completed successfully |
| `pipeline.phase.failed` | `phase_id`, `error` | Phase failed |
| `pipeline.budget.warning` | `current_usd`, `limit_usd`, `percent` | Budget warning threshold reached |
| `pipeline.budget.threshold_exceeded` | `scope_type`, `scope_id`, `window`, `usage_usd`, `limit_usd`, `percent`, `action` | Persistent budget threshold breached |

## Protocols

### QualityGate

```python
@runtime_checkable
class QualityGate(Protocol):
    async def check(self, phase_id: str, results: dict[str, Any]) -> GateResult: ...
```

### CostTracker

```python
@runtime_checkable
class CostTracker(Protocol):
    def record(self, cost: CostRecord) -> None: ...
    def total_cost(self) -> float: ...
    def check_budget(self) -> bool: ...
```

### GoalDecomposer

```python
@runtime_checkable
class GoalDecomposer(Protocol):
    async def decompose(self, goal: Goal) -> list[Goal]: ...
```

### PersistentBudgetStore

```python
@runtime_checkable
class PersistentBudgetStore(Protocol):
    async def record_cost(self, scope: BudgetScope, amount_usd: float, description: str = "") -> None: ...
    async def get_usage(self, scope: BudgetScope, window: BudgetWindow) -> float: ...
    async def check_threshold(self, scope: BudgetScope, window: BudgetWindow) -> ThresholdResult: ...
    async def list_incidents(self, scope: BudgetScope) -> list[BudgetIncident]: ...
```

## Next Steps

- [Multi-Agent Graphs](multi-agent.md) -- agent graph setup, roles, and communication
- [Orchestration](orchestration.md) -- how the orchestrator dispatches tasks to agents
- [Observability](observability.md) -- structured logging and event bus integration
