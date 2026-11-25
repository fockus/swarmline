# Autopilot Orchestrator

`swarmline.orchestration.autopilot` (Epic G) is a **generative meta-loop**
layered on top of the closed H6 supervisor. It composes existing swarmline
seams — the graph builder, the task board, `handoff()`, `eval.scorers`,
`ApprovalGate` — into one repeatable cycle: **plan → verify → [approval] →
deploy → gate**. It never re-implements any of those seams.

## The two-level model

- **Level B — the H6 supervisor** is the closed, deterministic graph
  execution engine: a fixed graph of agents, task delegation via `handoff()`,
  retries, and a finalize verify-before-done gate. It is the substrate.
- **Level C — autopilot** sits *above* level B and is generative: it
  produces (or accepts) a *blueprint* — a graph + a task list + an output
  contract — verifies it before committing resources, deploys it onto the
  level-B supervisor, then gates the deployed artifacts against the
  contract. It never bypasses level B's own retry/finalize behavior; it
  drives it once per run.

## Two modes

- **`dynamic`** — an `LLMPlanner` generates the blueprint from a natural
  language goal (one LLM call in, one `OrchestrationBlueprint` out).
- **`hardcode`** — the caller supplies a pre-built `blueprint` (and,
  optionally, a `contract` override); the *initial* planning call
  (`Planner.plan`) is skipped. The verify phase still runs — the critic, and a
  `Planner.replan` if the blueprint fails validation — so a hardcode run is
  fully offline and deterministic only when its injected verify components are
  offline too, or (the common case) when the supplied blueprint verifies
  cleanly with no repair. Ideal for tests, CI, or any run whose
  graph/tasks/contract are already known.

## The phase pipeline

1. **plan** — resolve the starting blueprint (`Planner.plan` in `dynamic`
   mode, or the caller-supplied blueprint in `hardcode` mode).
2. **verify** (`VerifyPhase`) — two layers, re-run every round: deterministic
   `validate_blueprint` (graph schema, governance limits, capability-subset
   delegation, assignee existence, contract well-formedness) and the LLM
   `BlueprintCritic` (goal coverage, role/tool adequacy, contract
   completeness). On any failure `Planner.replan` revises the blueprint from
   the combined feedback, bounded by `max_plan_repair` rounds; exhausting the
   budget without a clean pass escalates to a human via an injected
   `ApprovalGate` — never fails silently.
3. **approval** (optional, `OrchestratorConfig.require_plan_approval`) — a
   GO/ABORT gate on the verified blueprint before anything is deployed.
4. **deploy** (`DeployPhase`) — materializes the blueprint's graph dict into
   a real `GraphSnapshot` (`GraphBuilder.from_dict`), seeds an
   `InMemoryGraphTaskBoard` with one task per `BlueprintTask`, and executes
   every task through the **existing H6 `handoff()` seam** — no parallel
   execution loop is reinvented here.
5. **gate** (`RoutingContractGate`) — routes every `AcceptanceCriterion` to
   its verifier: `"deterministic"` criteria go to a pre-configured
   `eval.scorers.Scorer` looked up by `criterion.verifier`; `"subjective"`
   criteria go to an injected `SubjectiveJudge` (reviewer/judge rubric). The
   pass/fail decision reuses the SAME coverage rule the H6 finalize gate
   uses (`verification.coverage.unmet_criteria`) — passes only when every
   criterion is covered and none failed. On failure an injected `repair`
   callable revises the artifacts, bounded by `max_gate_repair`; exhausting
   the budget (or having no `repair` at all) escalates to a human via
   `ApprovalGate`, never fails silently.

Every phase transition is recorded in `OrchestrationResult.phase_log` and,
if an `EventBus` is wired into the engine, emitted as an `"autopilot.phase"`
event — phase telemetry is observability signal, orthogonal to whatever
message bus a deployed graph's agents use internally.

## Output contract

An `OutputContract` names the run's `deliverables` (file paths, artifact
names — whatever the domain calls them) plus a tuple of
`AcceptanceCriterion`, each bound to a verifier: a scorer name
(deterministic) or a reviewer/judge rubric (subjective). It may also carry
an `output_schema` (arbitrary dict, unenforced by autopilot itself) and
free-form `constraints`. A deliverable with no criterion bound to it is a
contract-authoring defect — the gate only checks criteria, so an unbound
deliverable is never independently verified.

## Repair budgets and HITL escalation

`OrchestratorConfig` carries the run's bounds: `max_plan_repair` (default
`3`, pre-deploy verify/replan rounds), `max_gate_repair` (default `3`,
post-deploy contract-gate repair rounds), and `max_recursion_depth` (default
`2`, the `orchestrate` tool's ceiling). Every budget is a
**fail-loud, not fail-silent** boundary: exhausting it always escalates to a
human through an `ApprovalGate` (`result.status == "verify_escalated"`, or a
failing `GateVerdict`) — never a false "done".

## The `orchestrate` tool and recursion

`create_orchestrate_tool` binds an `OrchestratorEngine` (or any narrower
`SubEngine`) plus the *current* recursion depth into a tool an agent can
call to launch a bounded sub-orchestration (`plan → verify → deploy → gate`
for a sub-goal). Each nested sub-orchestration would wire its own
`orchestrate` tool at `depth + 1`; a call issued at or past
`max_recursion_depth` is refused rather than executed.

## Current F-gating (honest status)

Two halves of the original design are **not yet active**, both gated on
future Epic F work rather than anything in this package:

- **Per-node distinct runtime/provider adapters** (REQ-015) — deferred to
  Epic F4. `multi_agent/agent_adapter.py` and an `AdapterRegistry` do not
  exist in this tree, so `DeployPhase` executes every task through one
  injected `GraphHandoffRunner` — there is no per-node dispatch.
- **Budget-gas recursion ceiling** — deferred to Epic F3. A
  `GraphBudgetTracker` does not exist yet, so the `orchestrate` tool's only
  recursion guard today is the numeric `max_recursion_depth` check.

Everything else above — both modes, the full phase pipeline, repair
budgets, HITL escalation, and the `orchestrate` tool's depth guard — is live
and exercised by the test suite (`tests/unit/test_autopilot_*.py`,
`tests/integration/test_autopilot_e2e.py`).

## Minimal example (`hardcode` mode)

```python
from swarmline.orchestration.autopilot import (
    AcceptanceCriterion, BlueprintTask, DeployPhase, OrchestrationBlueprint,
    OrchestratorEngine, OutputContract, RoutingContractGate, VerifyPhase,
)

blueprint = OrchestrationBlueprint(
    graph={
        "id": "root", "name": "Root", "role": "planner",
        "children": [{"id": "child", "name": "Child", "role": "engineer", "children": []}],
    },
    tasks=(
        BlueprintTask(id="t1", title="Build it", assignee_node_id="child", goal="Build the widget."),
    ),
    contract=OutputContract(
        deliverables=("widget",),
        criteria=(
            AcceptanceCriterion(id="c1", description="widget ready", kind="deterministic", verifier="contains"),
        ),
    ),
)

engine = OrchestratorEngine(
    planner,        # a Planner — unused in "hardcode" mode
    verify_phase,   # VerifyPhase(planner, critic, approval_gate, governance=...)
    deploy_phase,   # DeployPhase(orchestrator)  — orchestrator: a GraphHandoffRunner
    gate,           # RoutingContractGate(scorers, subjective_judge, approval_gate)
)

result = await engine.run(mode="hardcode", blueprint=blueprint)
assert result.status == "done"
```

See `docs/harness.md` for the composition layer `DeployPhase` deploys onto,
and the forthcoming Epic F `agent-graph` runtime doc for the per-node
adapter and budget-gas work referenced above.
