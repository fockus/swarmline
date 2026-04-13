# Code Verification Pipeline

## Overview

The Code Verification Pipeline is a structured system for enforcing code quality standards during agent-driven development. It answers the question: **"How do we ensure that code produced by an autonomous agent meets production-quality standards?"**

The pipeline provides:

- **Declarative configuration** — toggle TDD, SOLID, linting, coverage via frozen dataclasses
- **Pluggable verification** — `CodeVerifier` protocol with 5 ISP-compliant methods
- **Definition of Done enforcement** — `DoDStateMachine` runs verify → fix → re-verify loops
- **End-to-end workflow** — `CodeWorkflowEngine` orchestrates plan → execute → verify

All components are pure domain objects with zero framework dependencies.

## Quick Start

Get a verification pipeline running in 10 lines:

```python
from swarmline.orchestration.coding_standards import CodingStandardsConfig
from swarmline.orchestration.tdd_code_verifier import TddCodeVerifier
from swarmline.orchestration.dod_state_machine import DoDStateMachine
from swarmline.orchestration.code_workflow_engine import CodeWorkflowEngine

config = CodingStandardsConfig.strict()
verifier = TddCodeVerifier(config=config, runner=my_shell_runner)
dod = DoDStateMachine(max_loops=3)
engine = CodeWorkflowEngine(verifier=verifier, dod=dod, planner=my_planner)

result = await engine.run("Add user auth", dod_criteria=("tests", "linters", "coverage"))
print(result.status)  # WorkflowStatus.SUCCESS | FAILED | DOD_NOT_MET
```

### Architecture

```
┌─────────────────────────────────────────────────┐
│              CodePipelineConfig                  │
│  ┌─────────────────┐  ┌──────────────────────┐  │
│  │ CodingStandards │  │ WorkflowAutomation   │  │
│  │ Config          │  │ Config               │  │
│  └────────┬────────┘  └──────────────────────┘  │
│           │            ┌──────────────────────┐  │
│           │            │ AutonomousLoopConfig │  │
│           │            └──────────────────────┘  │
│           │            ┌──────────────────────┐  │
│           │            │ TeamAgentsConfig     │  │
│           │            └──────────────────────┘  │
└───────────┼─────────────────────────────────────┘
            │
            ▼
┌───────────────────────┐     ┌──────────────────┐
│ CodeVerifier Protocol │◄────│ TddCodeVerifier  │
│  (5 methods, ISP)     │     │  (implementation) │
└───────────┬───────────┘     └────────┬─────────┘
            │                          │
            │                          ▼
            │                 ┌──────────────────┐
            │                 │ CommandRunner     │
            │                 │ Protocol (shell)  │
            │                 └──────────────────┘
            ▼
┌───────────────────────┐
│  DoDStateMachine      │
│  (verify loop)        │
└───────────┬───────────┘
            │
            ▼
┌───────────────────────┐
│ CodeWorkflowEngine    │
│ plan → execute → DoD  │
└───────────────────────┘
```

---

## CodingStandardsConfig

Declarative configuration for code quality checks. All flags are **OFF by default** — opt-in, not opt-out.

```python
from swarmline.orchestration.coding_standards import CodingStandardsConfig
```

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `tdd_enabled` | `bool` | `False` | Require TDD (tests before code) |
| `solid_enabled` | `bool` | `False` | Enforce SOLID principles |
| `dry_enabled` | `bool` | `False` | Enforce DRY (no duplication) |
| `kiss_enabled` | `bool` | `False` | Enforce KISS (simplicity) |
| `clean_arch_enabled` | `bool` | `False` | Enforce Clean Architecture layers |
| `integration_tests_required` | `bool` | `False` | Require integration tests |
| `e2e_tests_required` | `bool` | `False` | Require end-to-end tests |
| `min_coverage_pct` | `int` | `0` | Minimum test coverage percentage |

### Factory Presets

```python
# Strict — all checks ON, 95% coverage
strict = CodingStandardsConfig.strict()
# tdd=True, solid=True, dry=True, kiss=True, clean_arch=True,
# integration_tests=True, e2e_tests=True, min_coverage=95

# Minimal — TDD + basic coverage only
minimal = CodingStandardsConfig.minimal()
# tdd=True, min_coverage=70 (everything else False/0)

# Off — exploratory mode, no checks
off = CodingStandardsConfig.off()
# all defaults (all False, min_coverage=0)
```

### Custom Configuration

```python
config = CodingStandardsConfig(
    tdd_enabled=True,
    solid_enabled=True,
    clean_arch_enabled=True,
    integration_tests_required=True,
    min_coverage_pct=85,
)
```

### Related Configs

#### WorkflowAutomationConfig

Controls which pipeline steps run automatically without user intervention.

```python
from swarmline.orchestration.coding_standards import WorkflowAutomationConfig

# Fields: auto_lint, auto_format, auto_test, auto_commit, auto_review (all bool, default False)

full = WorkflowAutomationConfig.full()    # all True
light = WorkflowAutomationConfig.light()  # lint + format + test only
off = WorkflowAutomationConfig.off()      # all False
```

#### AutonomousLoopConfig

Controls the agent's autonomous execution loop boundaries.

```python
from swarmline.orchestration.coding_standards import AutonomousLoopConfig

# Fields:
#   max_iterations: int = 10        — max loop iterations
#   max_cost_credits: int = 0       — credit budget (0 = unlimited)
#   stop_on_failure: bool = True    — halt on first failure
#   require_approval: bool = True   — require human approval

strict = AutonomousLoopConfig.strict()  # max_iterations=5, stop_on_failure=True, require_approval=True
light = AutonomousLoopConfig.light()    # max_iterations=20, stop_on_failure=False, require_approval=False
```

#### TeamAgentsConfig

Defines which agent roles are active in a team.

```python
from swarmline.orchestration.coding_standards import TeamAgentsConfig

team = TeamAgentsConfig(
    use_architect=True,
    use_developer=True,
    use_tester=True,
    use_reviewer=True,
    max_parallel_agents=3,
)
```

#### CodePipelineConfig (Aggregate)

Combines all four configs into a single pipeline configuration object.

```python
from swarmline.orchestration.coding_standards import CodePipelineConfig

# Production: strict standards, full automation, conservative loop
prod = CodePipelineConfig.production()

# Development: minimal standards, light automation, relaxed loop
dev = CodePipelineConfig.development()

# Custom
pipeline = CodePipelineConfig(
    standards=CodingStandardsConfig.strict(),
    workflow=WorkflowAutomationConfig.full(),
    loop=AutonomousLoopConfig.strict(),
    team=TeamAgentsConfig(max_parallel_agents=4),
)

# Access nested configs
print(pipeline.standards.tdd_enabled)    # True
print(pipeline.workflow.auto_test)       # True
print(pipeline.loop.max_iterations)      # 5
```

---

## CodeVerifier Protocol

The `CodeVerifier` protocol defines 5 verification methods — one per quality dimension. It follows ISP (Interface Segregation Principle): exactly 5 methods, each with a single responsibility.

```python
from swarmline.orchestration.code_verifier import CodeVerifier, CommandRunner, CommandResult
```

### Protocol Definition

```python
class CodeVerifier(Protocol):
    async def verify_contracts(self) -> VerificationResult:
        """Run contract tests (pytest -m contract)."""
        ...

    async def verify_tests_substantive(self) -> VerificationResult:
        """Verify tests exist and are substantive (not trivial)."""
        ...

    async def verify_tests_before_code(self) -> VerificationResult:
        """Heuristic: were tests written before implementation?"""
        ...

    async def verify_linters(self) -> VerificationResult:
        """Run linters and type checks (ruff, ty, etc.)."""
        ...

    async def verify_coverage(self, min_pct: int = 85) -> VerificationResult:
        """Run tests with coverage, enforce minimum threshold."""
        ...
```

### CommandRunner Protocol

Shell execution abstraction — allows swapping real shell for sandbox or mock:

```python
class CommandRunner(Protocol):
    async def run(self, command: str) -> CommandResult: ...

@dataclass(frozen=True, slots=True)
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str
```

### Implementing a Custom Verifier

```python
from swarmline.orchestration.code_verifier import CodeVerifier
from swarmline.orchestration.verification_types import (
    VerificationResult, VerificationStatus, CheckDetail,
)

class MyProjectVerifier:
    """Custom verifier for a specific project."""

    def __init__(self, runner: CommandRunner) -> None:
        self._runner = runner

    async def verify_contracts(self) -> VerificationResult:
        result = await self._runner.run("pytest -m contract -q")
        status = VerificationStatus.PASS if result.exit_code == 0 else VerificationStatus.FAIL
        return VerificationResult(
            status=status,
            checks=(CheckDetail(name="contracts", status=status, message=result.stdout),),
            summary=f"Contract tests: {status}",
        )

    async def verify_tests_substantive(self) -> VerificationResult:
        # ... similar pattern
        ...

    async def verify_tests_before_code(self) -> VerificationResult:
        # ... similar pattern
        ...

    async def verify_linters(self) -> VerificationResult:
        result = await self._runner.run("ruff check . && ty check src/swarmline")
        # ...

    async def verify_coverage(self, min_pct: int = 85) -> VerificationResult:
        result = await self._runner.run(f"pytest --cov --cov-fail-under={min_pct}")
        # ...
```

---

## TddCodeVerifier

The built-in implementation of `CodeVerifier`. It respects `CodingStandardsConfig` — **disabled checks automatically return `SKIP`**, not `FAIL`.

```python
from swarmline.orchestration.tdd_code_verifier import TddCodeVerifier
```

### Construction

```python
verifier = TddCodeVerifier(
    config=CodingStandardsConfig.strict(),
    runner=my_command_runner,
)
```

### Method Behavior

| Method | Config Gate | Command | When Disabled |
|--------|------------|---------|---------------|
| `verify_contracts()` | `solid_enabled` | `pytest -m contract -q` | `SKIP` |
| `verify_tests_substantive()` | `tdd_enabled` | `pytest -q` | `SKIP` |
| `verify_tests_before_code()` | `tdd_enabled` | `git log --oneline -5` | `SKIP` |
| `verify_linters()` | *(always runs)* | `ruff check .` | N/A |
| `verify_coverage(min_pct)` | `tdd_enabled` | `pytest --cov --cov-fail-under=N` | `SKIP` |

Key details:

- `verify_linters()` **always runs** regardless of config — linting is non-negotiable
- `verify_coverage()` uses the **maximum** of `min_pct` argument and `config.min_coverage_pct`
- `verify_tests_before_code()` uses a git log heuristic — checks if test files appear before implementation files in recent commits

### Example: Disabled Checks

```python
off_verifier = TddCodeVerifier(
    config=CodingStandardsConfig.off(),
    runner=my_runner,
)

contracts = await off_verifier.verify_contracts()
assert contracts.status == VerificationStatus.SKIP  # solid_enabled=False → SKIP

linters = await off_verifier.verify_linters()
assert linters.status in (VerificationStatus.PASS, VerificationStatus.FAIL)  # always runs
```

---

## Verification Types

```python
from swarmline.orchestration.verification_types import (
    VerificationStatus,
    CheckDetail,
    VerificationResult,
)
```

### VerificationStatus

```python
class VerificationStatus(StrEnum):
    PASS = "pass"    # check succeeded
    FAIL = "fail"    # check failed
    SKIP = "skip"    # check disabled by config
```

### CheckDetail

A single check result within a verification:

```python
@dataclass(frozen=True, slots=True)
class CheckDetail:
    name: str                    # e.g. "contracts", "linters"
    status: VerificationStatus
    message: str = ""            # stdout, error details, etc.
```

### VerificationResult

Aggregated result of a verification method:

```python
@dataclass(frozen=True, slots=True)
class VerificationResult:
    status: VerificationStatus
    checks: tuple[CheckDetail, ...] = ()
    summary: str = ""

    @property
    def passed(self) -> bool:
        return self.status == VerificationStatus.PASS
```

### Inspecting Results

```python
result = await verifier.verify_linters()

if result.passed:
    print("Linters clean!")
else:
    for check in result.checks:
        if check.status == VerificationStatus.FAIL:
            print(f"  FAIL: {check.name} — {check.message}")
```

---

## DoDStateMachine

The Definition of Done state machine runs a **verify → fix → re-verify loop** until all criteria pass or the maximum number of loops is exceeded.

```python
from swarmline.orchestration.dod_state_machine import DoDStateMachine, DoDStatus, DoDResult
```

### State Diagram

```
                    ┌──────────────────────────────────┐
                    │          all criteria pass        │
                    ▼                                   │
PENDING ──→ VERIFYING ──→ PASSED                       │
                │                                      │
                │ some criteria fail                    │
                │                                      │
                ├── loop_count < max_loops ─────────────┘
                │        (retry)
                │
                └── loop_count >= max_loops ──→ MAX_LOOPS_EXCEEDED
```

### DoDStatus

```python
class DoDStatus(StrEnum):
    PENDING = "pending"                    # not started
    VERIFYING = "verifying"               # running checks
    PASSED = "passed"                     # all criteria met
    FAILED = "failed"                     # explicit failure
    MAX_LOOPS_EXCEEDED = "max_loops_exceeded"  # gave up after N attempts
```

### DoDResult

```python
@dataclass(frozen=True, slots=True)
class DoDResult:
    status: DoDStatus
    loop_count: int          # number of verification attempts
    verification_log: str    # detailed log of all checks
```

### Usage

```python
dod = DoDStateMachine(max_loops=3)

result = await dod.verify_dod(
    criteria=("contracts", "tests", "linters", "coverage"),
    verifier=verifier,
)

match result.status:
    case DoDStatus.PASSED:
        print(f"All criteria met in {result.loop_count} loop(s)")
    case DoDStatus.MAX_LOOPS_EXCEEDED:
        print(f"Failed after {result.loop_count} attempts")
        print(result.verification_log)
```

### Supported Criteria

| Criterion Name | Maps To |
|---------------|---------|
| `"contracts"` | `verifier.verify_contracts()` |
| `"tests"` | `verifier.verify_tests_substantive()` |
| `"tdd"` | `verifier.verify_tests_before_code()` |
| `"linters"` | `verifier.verify_linters()` |
| `"coverage"` | `verifier.verify_coverage()` |

### Edge Cases

- **Empty criteria** `()` — returns immediately with `PASSED` (nothing to check)
- **All SKIP** — skipped criteria are treated as passing (not blocking)
- **Single failure** — the entire loop retries all criteria

---

## CodeWorkflowEngine

The top-level orchestrator that runs the full pipeline: **plan → execute → verify DoD**.

```python
from swarmline.orchestration.code_workflow_engine import (
    CodeWorkflowEngine, WorkflowStatus, WorkflowResult,
)
```

### Pipeline Diagram

```
engine.run(goal, dod_criteria)
    │
    ▼
┌──────────────────┐
│ planner          │
│ .create_plan()   │──→ plan string
└────────┬─────────┘
         ▼
┌──────────────────┐
│ planner          │
│ .execute_plan()  │──→ output string
└────────┬─────────┘
         ▼
    dod_criteria empty? ──yes──→ return SUCCESS(output)
         │ no
         ▼
┌──────────────────┐
│ DoDStateMachine  │
│ .verify_dod()    │──→ loops up to max_loops
└────────┬─────────┘
         │
    ┌────┴────┐
    ▼         ▼
 PASSED    MAX_LOOPS
    │         │
    ▼         ▼
 SUCCESS   DOD_NOT_MET
```

### Error Handling

- If `create_plan()` or `execute_plan()` raises an exception → `WorkflowStatus.FAILED`
- If DoD verification encounters transient errors → retried within `max_loops`
- `WorkflowResult.output` always contains the execution output (even on `DOD_NOT_MET`)
- `WorkflowResult.dod_log` contains the detailed verification log from all loops

### WorkflowStatus

```python
class WorkflowStatus(StrEnum):
    SUCCESS = "success"        # plan executed and DoD passed
    FAILED = "failed"          # plan execution failed
    DOD_NOT_MET = "dod_not_met"  # executed but DoD not met after max loops
```

### WorkflowResult

```python
@dataclass(frozen=True, slots=True)
class WorkflowResult:
    status: WorkflowStatus
    output: str = ""       # execution output
    dod_log: str = ""      # DoD verification log
    loop_count: int = 0    # DoD verification attempts
```

### Construction

```python
engine = CodeWorkflowEngine(
    verifier=verifier,           # CodeVerifier implementation
    dod=DoDStateMachine(max_loops=3),
    planner=planner_mode,        # PlannerMode with create_plan/execute_plan
)
```

### Execution Flow

```python
result = await engine.run(
    goal="Implement user authentication",
    dod_criteria=("contracts", "tests", "linters", "coverage"),
)
```

**Internal steps:**

1. `planner.create_plan(goal)` — generate execution plan
2. `planner.execute_plan(plan)` — execute the plan
3. If `dod_criteria` is empty → return `SUCCESS` immediately
4. If `dod_criteria` provided → `dod.verify_dod(criteria, verifier)`
5. If DoD passed → `SUCCESS`
6. If DoD max loops exceeded → `DOD_NOT_MET`

### Without DoD

```python
# Skip verification — just plan and execute
result = await engine.run(goal="Quick prototype", dod_criteria=())
assert result.status == WorkflowStatus.SUCCESS
```

---

## WorkflowPipeline Protocol

A generic 5-stage pipeline contract for building custom workflow implementations.

```python
from swarmline.orchestration.workflow_pipeline import WorkflowPipeline
```

```python
class WorkflowPipeline(Protocol):
    async def research(self, goal: str) -> str:
        """Phase 1: Gather information and context."""
        ...

    async def plan(self, research: str) -> Plan:
        """Phase 2: Create execution plan from research."""
        ...

    async def execute(self, plan: Plan) -> str:
        """Phase 3: Implement the plan."""
        ...

    async def review(self, result: str) -> str:
        """Phase 4: Review execution results."""
        ...

    async def verify(self, result: str) -> VerificationResult:
        """Phase 5: Verify quality of results."""
        ...
```

This protocol is more granular than `CodeWorkflowEngine` — it separates research and review as explicit phases. Use it when you need a full 5-stage pipeline with custom logic at each stage.

---

## Configuration Presets

### `CodePipelineConfig.production()` vs `CodePipelineConfig.development()`

| Setting | `production()` | `development()` |
|---------|----------------|------------------|
| **Standards** | `.strict()` | `.minimal()` |
| TDD | ON | ON |
| SOLID | ON | OFF |
| DRY / KISS | ON | OFF |
| Clean Architecture | ON | OFF |
| Integration tests | Required | Not required |
| E2E tests | Required | Not required |
| Min coverage | 95% | 70% |
| **Workflow** | `.full()` | `.light()` |
| Auto lint | ON | ON |
| Auto format | ON | ON |
| Auto test | ON | ON |
| Auto commit | ON | OFF |
| Auto review | ON | OFF |
| **Loop** | `.strict()` | `.light()` |
| Max iterations | 5 | 20 |
| Stop on failure | Yes | No |
| Require approval | Yes | No |
| **Team** | default | default |
| Roles | All 4 active | All 4 active |
| Max parallel | 3 | 3 |

### When to Use Which

| Scenario | Recommended Preset |
|----------|-------------------|
| Production feature development | `CodePipelineConfig.production()` |
| Prototyping / spike | `CodePipelineConfig.development()` |
| CI/CD pipeline gate | `CodingStandardsConfig.strict()` + custom `WorkflowAutomationConfig` |
| Exploratory coding | `CodingStandardsConfig.off()` (linters still run) |
| Code review bot | Custom: `tdd_enabled=False`, `solid_enabled=True`, linters only |

---

## Full Example

End-to-end: configure standards → build verifier → create DoD machine → run engine.

```python
import asyncio
from dataclasses import dataclass

from swarmline.orchestration.coding_standards import (
    CodingStandardsConfig,
    CodePipelineConfig,
)
from swarmline.orchestration.code_verifier import CommandRunner, CommandResult
from swarmline.orchestration.tdd_code_verifier import TddCodeVerifier
from swarmline.orchestration.dod_state_machine import DoDStateMachine, DoDStatus
from swarmline.orchestration.code_workflow_engine import (
    CodeWorkflowEngine,
    WorkflowStatus,
)


# 1. Implement CommandRunner for your environment
class ShellRunner:
    async def run(self, command: str) -> CommandResult:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return CommandResult(
            exit_code=proc.returncode or 0,
            stdout=stdout.decode(),
            stderr=stderr.decode(),
        )


# 2. Choose pipeline configuration
config = CodePipelineConfig.production()
# Or custom:
# config = CodePipelineConfig(
#     standards=CodingStandardsConfig(
#         tdd_enabled=True,
#         solid_enabled=True,
#         min_coverage_pct=90,
#     ),
# )

# 3. Build verification stack
runner = ShellRunner()
verifier = TddCodeVerifier(config=config.standards, runner=runner)
dod = DoDStateMachine(max_loops=3)

# 4. Create workflow engine
engine = CodeWorkflowEngine(
    verifier=verifier,
    dod=dod,
    planner=my_planner,  # any object with create_plan/execute_plan
)

# 5. Run the pipeline
async def main() -> None:
    result = await engine.run(
        goal="Add billing webhook handler with retry logic",
        dod_criteria=("contracts", "tests", "tdd", "linters", "coverage"),
    )

    match result.status:
        case WorkflowStatus.SUCCESS:
            print(f"Done! DoD passed in {result.loop_count} loop(s)")
            print(result.output)
        case WorkflowStatus.DOD_NOT_MET:
            print(f"DoD not met after {result.loop_count} attempts")
            print("Verification log:")
            print(result.dod_log)
        case WorkflowStatus.FAILED:
            print("Workflow failed during execution")
            print(result.output)

asyncio.run(main())
```

### Running Individual Checks

You can also use the verifier directly without the engine:

```python
# Run specific checks
contracts = await verifier.verify_contracts()
linters = await verifier.verify_linters()
coverage = await verifier.verify_coverage(min_pct=90)

# Inspect results
for result in [contracts, linters, coverage]:
    print(f"{result.summary}: {'PASS' if result.passed else result.status}")
    for check in result.checks:
        print(f"  {check.name}: {check.status} — {check.message[:80]}")
```

### Using DoDStateMachine Standalone

```python
dod = DoDStateMachine(max_loops=5)

# Only check linters and coverage
result = await dod.verify_dod(
    criteria=("linters", "coverage"),
    verifier=verifier,
)

if result.status == DoDStatus.PASSED:
    print("Ready to merge")
```
