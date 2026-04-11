# Orchestration — Planning, Subagents, Team Mode, Code Verification

## Readiness Status

| Component | Status | Notes |
|-----------|--------|-------|
| Planning API (`PlanManager`) | staged | Base flow ready, InMemory storage |
| Subagents | ready | Thin/DeepAgents/Claude orchestrators with unified protocol |
| Team Mode core | ready | `TeamManager` + `DeepAgents/ClaudeTeamOrchestrator` |
| Team command surface (app layer) | staged | `/team_*` commands available with `CAP_TEAM_ENABLED` |
| Code Verification Pipeline | **ready** | `CodeVerifier` + `TddCodeVerifier` + `DoDStateMachine` (v0.4.0) |

---

## Team Mode

Lead agent coordinates a team of worker agents. Workers run in parallel and communicate via `MessageBus`.

### Architecture

```
TeamManager (app API)
    └── TeamOrchestrator Protocol
        ├── ClaudeTeamOrchestrator     (SDK Task-based, lead delegation)
        ├── DeepAgentsTeamOrchestrator (supervisor pattern)
        │   └── SubagentOrchestrator (workers)
        └── MessageBus (inter-agent communication)
    └── ResumableTeamOrchestrator Protocol (extends TeamOrchestrator)
            └── + resume_agent(team_id, agent_id)
```

### TeamOrchestrator Protocol

```python
from swarmline.orchestration.team_protocol import TeamOrchestrator, ResumableTeamOrchestrator

class TeamOrchestrator(Protocol):
    """ISP-compliant: exactly 5 methods."""
    async def start(self, config: TeamConfig, task: str) -> str: ...
    async def stop(self, team_id: str) -> None: ...
    async def get_team_status(self, team_id: str) -> TeamStatus: ...
    async def send_message(self, team_id: str, message: TeamMessage) -> None: ...
    async def pause_agent(self, team_id: str, agent_id: str) -> None: ...

class ResumableTeamOrchestrator(Protocol):
    """Extends TeamOrchestrator with resume capability."""
    async def resume_agent(self, team_id: str, agent_id: str) -> None: ...
```

### Creating a Team

```python
from swarmline.orchestration.team_manager import TeamManager
from swarmline.orchestration.claude_team import ClaudeTeamOrchestrator
from swarmline.orchestration.claude_subagent import ClaudeSubagentOrchestrator
from swarmline.orchestration.team_types import TeamConfig
from swarmline.orchestration.subagent_types import SubagentSpec

# 1. Build orchestrator stack
subagent_orch = ClaudeSubagentOrchestrator(max_concurrent=4)
team_orch = ClaudeTeamOrchestrator(subagent_orchestrator=subagent_orch)
manager = TeamManager(orchestrator=team_orch)

# 2. Define team configuration
config = TeamConfig(
    lead_prompt="You are a team lead. Coordinate research and development.",
    worker_specs=[
        SubagentSpec(name="researcher", system_prompt="Find relevant data and references."),
        SubagentSpec(name="developer", system_prompt="Implement code based on research findings."),
        SubagentSpec(name="reviewer", system_prompt="Review code for quality and correctness."),
    ],
    max_workers=4,
    communication="message_passing",
)

# 3. Start team
team_id = await manager.start_team(config, task="Build a REST API for user management")

# 4. Monitor status
status = await manager.get_status(team_id)
print(status.state)        # "running" | "completed" | "failed"
print(status.workers)      # dict[str, SubagentStatus]

# 5. Pause/resume individual agents
await manager.pause_agent(team_id, "researcher")
await manager.resume_agent(team_id, "researcher")

# 6. Stop team
await manager.stop_team(team_id)
```

### Communication via MessageBus

Workers exchange messages through an in-memory `MessageBus`. Each team gets its own bus instance.

```python
from swarmline.orchestration.team_types import TeamMessage
from datetime import datetime, timezone

# Lead → Worker
await team_orch.send_message(team_id, TeamMessage(
    from_agent="lead",
    to_agent="researcher",
    content="Analyze deposit rates for top 5 banks",
    timestamp=datetime.now(tz=timezone.utc),
))

# Read inbox/outbox
bus = team_orch.get_message_bus(team_id)
inbox = bus.get_inbox("lead")        # messages TO lead
outbox = bus.get_outbox("researcher") # messages FROM researcher
history = bus.get_history()           # all messages

# Broadcast to multiple agents
bus.broadcast(from_agent="lead", content="Status update: phase 1 complete",
              recipients=["researcher", "developer", "reviewer"])
```

### Claude vs DeepAgents Team Modes

| Feature | `ClaudeTeamOrchestrator` | `DeepAgentsTeamOrchestrator` |
|---------|--------------------------|------------------------------|
| Worker task | Personalized (lead_prompt + worker name + task) | Same task for all workers |
| Pattern | Lead delegation | Supervisor |
| Resume support | Yes (via `ResumableTeamOrchestrator`) | Yes |

---

## Planning

Agent decomposes complex tasks into steps and executes them sequentially.

### Architecture

```
PlanManager (app API)
    ├── PlannerMode Protocol (LLM logic)
    │   ├── ThinPlannerMode        (lightweight, direct LLM)
    │   └── DeepAgentsPlannerMode  (optional LangGraph integration)
    └── PlanStore Protocol (persistence)
        └── InMemoryPlanStore
```

### PlannerMode Protocol

```python
from swarmline.orchestration.protocols import PlannerMode

class PlannerMode(Protocol):
    """ISP-compliant: exactly 5 methods."""
    async def generate_plan(self, goal: str, context: str) -> Plan: ...
    async def approve(self, plan: Plan, by: str) -> Plan: ...
    async def execute_step(self, plan: Plan, step_id: str) -> PlanStep: ...
    async def execute_all(self, plan: Plan) -> AsyncIterator[PlanStep]: ...
    async def replan(self, plan: Plan, feedback: str) -> Plan: ...
```

### Plan State Machine

```
draft ──→ approved ──→ executing ──→ completed
  │                        │
  └────────────────────────┴──────→ cancelled
```

- **draft** — plan created, awaiting approval
- **approved** — approved (by user, system, or agent)
- **executing** — steps running sequentially
- **completed** — all steps finished
- **cancelled** — terminated (from any state)

### PlanStep with DoD Criteria

Each step can carry Definition of Done criteria that the verification pipeline checks:

```python
from swarmline.orchestration.types import PlanStep

step = PlanStep(
    id="step-1",
    description="Implement user authentication",
    status="pending",
    dod_criteria=["contracts", "tests", "linters", "coverage"],
    dod_verified=False,
)

# After execution, step carries verification results
completed = step.complete(result="Auth module implemented")
print(completed.dod_verified)      # True/False
print(completed.verification_log)  # detailed check results
```

### Creating Plans via LLM

```python
from swarmline.orchestration.manager import PlanManager
from swarmline.orchestration.thin_planner import ThinPlannerMode
from swarmline.orchestration.plan_store import InMemoryPlanStore

# Wire up
store = InMemoryPlanStore()
planner = ThinPlannerMode(llm=my_llm_callable, plan_store=store, max_steps=10)
manager = PlanManager(planner=planner, plan_store=store)

# Create and execute
plan = await manager.create_plan(
    goal="Build a REST API with auth",
    user_id="user-1",
    topic_id="project-1",
    auto_approve=False,
)

plan = await manager.approve_plan(plan.id, by="user")

async for step in manager.execute_plan(plan.id):
    print(f"[{step.status}] {step.description}: {step.result}")
```

### Agent-Facing Planning Tools

When planning tools are enabled, the agent receives three tools:

```python
from swarmline.orchestration.plan_tools import create_plan_tools

tools, executors = create_plan_tools(manager, user_id="u1", topic_id="t1")
# tools: {"plan_create": ToolSpec, "plan_status": ToolSpec, "plan_execute": ToolSpec}

# Agent flow:
# 1. plan_create(goal="Complex task", auto_execute=True)
# 2. LLM generates steps → steps execute → results stream back
```

### PlanStore Protocol

```python
from swarmline.orchestration.protocols import PlanStore

class PlanStore(Protocol):
    """Multi-tenant plan persistence. ISP: 4 methods."""
    async def save(self, plan: Plan) -> None: ...
    async def load(self, plan_id: str) -> Plan | None: ...
    async def list_plans(self, user_id: str, topic_id: str) -> list[Plan]: ...
    async def update_step(self, plan_id: str, step: PlanStep) -> None: ...
```

---

## Code Verification Pipeline (v0.4.0)

A structured pipeline for verifying code quality against configurable standards. Integrates TDD checks, linting, coverage, and Definition of Done verification.

### Architecture

```
CodingStandardsConfig (what to check)
    │
    ▼
CodeVerifier Protocol ◄── TddCodeVerifier (implementation)
    │                         └── CommandRunner Protocol (shell)
    ▼
DoDStateMachine (retry loop: verify → fix → re-verify)
    │
    ▼
CodeWorkflowEngine (full pipeline: plan → execute → verify)
    │
    ▼
WorkflowPipeline Protocol (generic pipeline contract)
```

### CodingStandardsConfig

Declarative configuration — all flags OFF by default for safety:

```python
from swarmline.orchestration.coding_standards import (
    CodingStandardsConfig,
    WorkflowAutomationConfig,
    AutonomousLoopConfig,
    CodePipelineConfig,
    TeamAgentsConfig,
)

# Factory methods for common presets
strict = CodingStandardsConfig.strict()
# tdd_enabled=True, solid_enabled=True, dry_enabled=True, kiss_enabled=True,
# clean_arch_enabled=True, integration_tests_required=True, e2e_tests_required=True,
# min_coverage_pct=85

minimal = CodingStandardsConfig.minimal()
# tdd_enabled=True, solid_enabled=False, ..., min_coverage_pct=60

off = CodingStandardsConfig.off()
# all flags False, min_coverage_pct=0

# Custom configuration
custom = CodingStandardsConfig(
    tdd_enabled=True,
    solid_enabled=True,
    dry_enabled=False,
    kiss_enabled=True,
    clean_arch_enabled=True,
    integration_tests_required=True,
    e2e_tests_required=False,
    min_coverage_pct=80,
)
```

### WorkflowAutomationConfig

Controls which pipeline steps run automatically:

```python
full = WorkflowAutomationConfig.full()
# auto_lint=True, auto_format=True, auto_test=True, auto_commit=True, auto_review=True

light = WorkflowAutomationConfig.light()
# auto_lint=True, auto_format=True, rest False

off = WorkflowAutomationConfig.off()
# all False
```

### AutonomousLoopConfig

Controls the agent's autonomous execution loop:

```python
strict = AutonomousLoopConfig.strict()
# max_iterations=10, max_cost_credits=0, stop_on_failure=True, require_approval=True

light = AutonomousLoopConfig.light()
# max_iterations=5, max_cost_credits=0, stop_on_failure=False, require_approval=False
```

### CodePipelineConfig (Aggregate)

Combines all configs into a single pipeline configuration:

```python
# Production preset: strict standards, full automation, strict loop, full team
prod = CodePipelineConfig.production()

# Development preset: minimal standards, light automation, light loop
dev = CodePipelineConfig.development()

# Custom
pipeline = CodePipelineConfig(
    standards=CodingStandardsConfig.strict(),
    workflow=WorkflowAutomationConfig.full(),
    loop=AutonomousLoopConfig.strict(),
    team=TeamAgentsConfig(use_architect=True, use_developer=True,
                          use_tester=True, use_reviewer=True, max_parallel_agents=3),
)
```

### CodeVerifier Protocol

```python
from swarmline.orchestration.code_verifier import CodeVerifier, CommandRunner, CommandResult

class CommandRunner(Protocol):
    """Shell command execution abstraction."""
    async def run(self, command: str) -> CommandResult: ...

class CodeVerifier(Protocol):
    """ISP-compliant: exactly 5 verification methods."""
    async def verify_contracts(self) -> VerificationResult: ...
    async def verify_tests_substantive(self) -> VerificationResult: ...
    async def verify_tests_before_code(self) -> VerificationResult: ...
    async def verify_linters(self) -> VerificationResult: ...
    async def verify_coverage(self, min_pct: int) -> VerificationResult: ...
```

### TddCodeVerifier

Implements `CodeVerifier` with TDD awareness — disabled checks auto-skip:

```python
from swarmline.orchestration.tdd_code_verifier import TddCodeVerifier

verifier = TddCodeVerifier(
    config=CodingStandardsConfig.strict(),
    runner=my_command_runner,
)

# Each check respects config flags:
contracts = await verifier.verify_contracts()      # runs pytest -m contract (if SOLID enabled)
tests = await verifier.verify_tests_substantive()  # runs pytest (if TDD enabled)
tdd = await verifier.verify_tests_before_code()    # git log heuristic (if TDD enabled)
lint = await verifier.verify_linters()             # runs ruff check .
coverage = await verifier.verify_coverage(85)      # runs pytest --cov (uses max of min_pct and config)

# Disabled checks return VerificationStatus.SKIP
off_verifier = TddCodeVerifier(config=CodingStandardsConfig.off(), runner=my_runner)
result = await off_verifier.verify_contracts()
assert result.status == VerificationStatus.SKIP
```

### Verification Types

```python
from swarmline.orchestration.verification_types import (
    VerificationStatus,  # PASS | FAIL | SKIP
    CheckDetail,         # name, status, message
    VerificationResult,  # status, checks[], summary
)

result = await verifier.verify_linters()
print(result.passed)    # True if status == PASS
for check in result.checks:
    print(f"  {check.name}: {check.status} — {check.message}")
```

### DoDStateMachine

Runs a verification loop: check criteria → report failures → retry (up to `max_loops`):

```python
from swarmline.orchestration.dod_state_machine import DoDStateMachine, DoDStatus

dod = DoDStateMachine(max_loops=3)

result = await dod.verify_dod(
    criteria=("contracts", "tests", "linters", "coverage"),
    verifier=verifier,
)

print(result.status)          # DoDStatus.PASSED | FAILED | MAX_LOOPS_EXCEEDED
print(result.loop_count)      # number of verification attempts
print(result.verification_log) # detailed log of all checks
```

**DoDStatus flow:**

```
PENDING ──→ VERIFYING ──→ PASSED
                │
                ├──→ (retry if loop_count < max_loops) ──→ VERIFYING
                │
                └──→ MAX_LOOPS_EXCEEDED
```

**Supported criterion names:** `"contracts"`, `"tests"`, `"tdd"`, `"linters"`, `"coverage"`

### CodeWorkflowEngine

Full pipeline: plan → execute → verify DoD:

```python
from swarmline.orchestration.code_workflow_engine import CodeWorkflowEngine, WorkflowStatus

engine = CodeWorkflowEngine(
    verifier=verifier,
    dod=DoDStateMachine(max_loops=3),
    planner=planner_mode,
)

result = await engine.run(
    goal="Implement user authentication module",
    dod_criteria=("contracts", "tests", "linters", "coverage"),
)

print(result.status)      # WorkflowStatus.SUCCESS | FAILED | DOD_NOT_MET
print(result.output)      # execution output
print(result.loop_count)  # DoD verification attempts
print(result.dod_log)     # detailed verification log
```

### WorkflowPipeline Protocol

Generic pipeline contract for custom implementations:

```python
from swarmline.orchestration.workflow_pipeline import WorkflowPipeline

class WorkflowPipeline(Protocol):
    """5-stage pipeline: research → plan → execute → review → verify."""
    async def research(self, goal: str) -> str: ...
    async def plan(self, research: str) -> Plan: ...
    async def execute(self, plan: Plan) -> str: ...
    async def review(self, result: str) -> str: ...
    async def verify(self, result: str) -> VerificationResult: ...
```

### End-to-End Example

```python
from swarmline.orchestration.coding_standards import CodingStandardsConfig, CodePipelineConfig
from swarmline.orchestration.tdd_code_verifier import TddCodeVerifier
from swarmline.orchestration.dod_state_machine import DoDStateMachine
from swarmline.orchestration.code_workflow_engine import CodeWorkflowEngine

# 1. Configure standards
config = CodePipelineConfig.production()

# 2. Build verification stack
verifier = TddCodeVerifier(config=config.standards, runner=shell_runner)
dod = DoDStateMachine(max_loops=3)

# 3. Run code workflow with DoD enforcement
engine = CodeWorkflowEngine(verifier=verifier, dod=dod, planner=my_planner)
result = await engine.run(
    goal="Add billing webhook handler",
    dod_criteria=("contracts", "tests", "tdd", "linters", "coverage"),
)

if result.status == WorkflowStatus.SUCCESS:
    print("All DoD criteria met!")
elif result.status == WorkflowStatus.DOD_NOT_MET:
    print(f"DoD failed after {result.loop_count} attempts")
    print(result.dod_log)
```

---

## Subagents

Parent agent spawns child agents for parallel work.

### Architecture

```
SubagentOrchestrator Protocol
    ├── ThinSubagentOrchestrator       (asyncio.Task)
    ├── ClaudeSubagentOrchestrator     (Claude SDK, extends Thin)
    └── DeepAgentsSubagentOrchestrator (DeepAgents runtime, extends Thin)
```

### SubagentOrchestrator Protocol

```python
from swarmline.orchestration.subagent_protocol import SubagentOrchestrator

class SubagentOrchestrator(Protocol):
    """ISP-compliant: exactly 5 methods. @runtime_checkable."""
    async def spawn(self, spec: SubagentSpec, task: str) -> str: ...
    async def get_status(self, agent_id: str) -> SubagentStatus: ...
    async def cancel(self, agent_id: str) -> None: ...
    async def wait(self, agent_id: str) -> SubagentResult: ...
    async def list_active(self) -> list[str]: ...
```

### Lifecycle

```
pending ──→ running ──→ completed
                    ──→ failed
                    ──→ cancelled
```

### Usage

```python
from swarmline.orchestration.thin_subagent import ThinSubagentOrchestrator
from swarmline.orchestration.subagent_types import SubagentSpec

orch = ThinSubagentOrchestrator(max_concurrent=4)

spec = SubagentSpec(
    name="researcher",
    system_prompt="You are a research agent. Find relevant information.",
    tools=[...],
)

agent_id = await orch.spawn(spec, task="Find best deposit rates")
status = await orch.get_status(agent_id)
result = await orch.wait(agent_id)
print(result.output)

# Cancel
await orch.cancel(agent_id)

# List active
active = await orch.list_active()
```

### Safety

- `max_concurrent` limits parallel subagents (default: 4)
- Subagent crash does not crash parent — graceful `status=failed`
- Each subagent can have its own `SandboxConfig` (isolation)

---

## Message Bus

In-memory inter-agent communication system. Each team gets its own bus instance.

```python
from swarmline.orchestration.message_bus import MessageBus
from swarmline.orchestration.team_types import TeamMessage

bus = MessageBus()

# Send direct message
bus.send(TeamMessage(
    from_agent="lead", to_agent="researcher",
    content="Start phase 2", timestamp=now,
))

# Broadcast to multiple agents
bus.broadcast(
    from_agent="lead",
    content="Phase 1 complete, moving to phase 2",
    recipients=["researcher", "developer", "reviewer"],
)

# Query messages
inbox = bus.get_inbox("researcher")   # messages TO researcher
outbox = bus.get_outbox("lead")       # messages FROM lead
history = bus.get_history()           # all messages
bus.clear()                           # reset
```

---

## Types Reference

### Core Planning Types

| Type | Module | Description |
|------|--------|-------------|
| `Plan` | `types` | Multi-step execution plan (frozen dataclass) |
| `PlanStep` | `types` | Single step with DoD criteria (frozen dataclass) |
| `PlanApproval` | `types` | Audit record for plan approvals |
| `PlanStatus` | `types` | `"draft" \| "approved" \| "executing" \| "completed" \| "cancelled"` |
| `PlanStepStatus` | `types` | `"pending" \| "in_progress" \| "completed" \| "failed" \| "skipped"` |
| `ApprovalSource` | `types` | `"user" \| "system" \| "agent"` |

### Subagent Types

| Type | Module | Description |
|------|--------|-------------|
| `SubagentSpec` | `subagent_types` | Worker configuration (name, prompt, tools, sandbox) |
| `SubagentStatus` | `subagent_types` | Runtime state (state, progress, timestamps) |
| `SubagentResult` | `subagent_types` | Execution result (output, messages, metrics) |
| `SubagentState` | `subagent_types` | `"pending" \| "running" \| "completed" \| "failed" \| "cancelled"` |

### Team Types

| Type | Module | Description |
|------|--------|-------------|
| `TeamConfig` | `team_types` | Team specification (lead_prompt, worker_specs, max_workers) |
| `TeamMessage` | `team_types` | Inter-agent message (from, to, content, timestamp) |
| `TeamStatus` | `team_types` | Runtime state (workers dict, messages_exchanged) |
| `TeamState` | `team_types` | `"idle" \| "running" \| "completed" \| "failed"` |

### Verification Types

| Type | Module | Description |
|------|--------|-------------|
| `VerificationStatus` | `verification_types` | `PASS \| FAIL \| SKIP` |
| `CheckDetail` | `verification_types` | Single check (name, status, message) |
| `VerificationResult` | `verification_types` | Aggregated (status, checks[], summary) |
| `DoDStatus` | `dod_state_machine` | `PENDING \| VERIFYING \| PASSED \| FAILED \| MAX_LOOPS_EXCEEDED` |
| `DoDResult` | `dod_state_machine` | Loop result (status, loop_count, verification_log) |
| `WorkflowStatus` | `code_workflow_engine` | `SUCCESS \| FAILED \| DOD_NOT_MET` |
| `WorkflowResult` | `code_workflow_engine` | Pipeline result (status, output, dod_log) |

### Configuration Types

| Type | Module | Description |
|------|--------|-------------|
| `CodingStandardsConfig` | `coding_standards` | TDD/SOLID/DRY flags + coverage threshold |
| `WorkflowAutomationConfig` | `coding_standards` | Auto lint/format/test/commit/review |
| `AutonomousLoopConfig` | `coding_standards` | Max iterations, cost budget, approval |
| `TeamAgentsConfig` | `coding_standards` | Active roles + max parallel agents |
| `CodePipelineConfig` | `coding_standards` | Aggregate of all above configs |
