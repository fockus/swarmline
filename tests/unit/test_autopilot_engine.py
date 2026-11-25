"""Tests for the engine facade: plan -> verify -> [approval] -> deploy -> gate.

TDD Task 7 of the autopilot-orchestrator spec (Epic G). Covers REQ-003
(hardcode mode skips planning), REQ-011/REQ-012 (optional plan-approval
gate), REQ-021 (phase events on an `EventBus`). Uses offline stub
planner/critic/scorer/judge/orchestrator + a REAL `ApprovalGate` and a REAL
`InMemoryEventBus` — no network calls.
"""

from __future__ import annotations

from typing import Any

from swarmline.eval.types import EvalCase, ScorerResult
from swarmline.hitl.gate import ApprovalGate
from swarmline.hitl.policies import AlwaysDenyPolicy
from swarmline.hitl.types import ApprovalRequest, ApprovalResponse
from swarmline.multi_agent.graph_governance import GraphGovernanceConfig
from swarmline.observability.event_bus import InMemoryEventBus
from swarmline.orchestration.autopilot.deploy_phase import DeployPhase
from swarmline.orchestration.autopilot.engine import OrchestratorEngine
from swarmline.orchestration.autopilot.gate import RoutingContractGate
from swarmline.orchestration.autopilot.types import (
    AcceptanceCriterion,
    BlueprintTask,
    CriticVerdict,
    OrchestrationBlueprint,
    OrchestratorConfig,
    OutputContract,
)
from swarmline.orchestration.autopilot.verify_phase import VerifyPhase


def _valid_graph() -> dict[str, Any]:
    """A small, well-formed 2-level graph: root -> one child."""
    return {
        "id": "planner",
        "name": "Planner",
        "role": "planner",
        "allowed_tools": [],
        "skills": [],
        "hooks": [],
        "children": [
            {
                "id": "worker",
                "name": "Worker",
                "role": "engineer",
                "allowed_tools": [],
                "skills": [],
                "hooks": [],
                "children": [],
            }
        ],
    }


def _valid_blueprint() -> OrchestrationBlueprint:
    """A valid 2-node blueprint with one deterministic acceptance criterion."""
    task = BlueprintTask(
        id="task-1",
        title="Build the feature",
        assignee_node_id="worker",
        goal="Implement the feature end to end.",
    )
    criterion = AcceptanceCriterion(
        id="crit-1",
        description="Output contains the deliverable",
        kind="deterministic",
        verifier="unit_scorer",
    )
    contract = OutputContract(
        deliverables=("src/feature.py",),
        criteria=(criterion,),
    )
    return OrchestrationBlueprint(
        graph=_valid_graph(), tasks=(task,), contract=contract
    )


class _StubPlanner:
    """Offline stub `Planner` — `plan`/`replan` both echo a fixed blueprint."""

    def __init__(self, blueprint: OrchestrationBlueprint) -> None:
        self._blueprint = blueprint
        self.plan_calls = 0
        self.replan_calls = 0

    async def plan(self, goal: str, context: str = "") -> OrchestrationBlueprint:
        self.plan_calls += 1
        return self._blueprint

    async def replan(
        self, blueprint: OrchestrationBlueprint, feedback: str
    ) -> OrchestrationBlueprint:
        self.replan_calls += 1
        return self._blueprint


class _StubCritic:
    """Offline stub `BlueprintCritic` returning a fixed verdict."""

    def __init__(self, verdict: CriticVerdict) -> None:
        self._verdict = verdict

    async def critique(self, blueprint: OrchestrationBlueprint) -> CriticVerdict:
        return self._verdict


class _StubOrchestrator:
    """Offline stub `GraphHandoffRunner` — canned results per task id."""

    def __init__(self, results: dict[str, str]) -> None:
        self._results = results
        self.delegated: list[Any] = []

    async def delegate(self, request: Any) -> None:
        self.delegated.append(request)

    async def wait_for_task(
        self, task_id: str, timeout: float | None = None
    ) -> str | None:
        return self._results.get(task_id)


class _StubScorer:
    """Offline stub Scorer — returns one fixed passing result."""

    def __init__(self, name: str, result: ScorerResult) -> None:
        self._name = name
        self._result = result
        self.calls: list[EvalCase] = []

    @property
    def name(self) -> str:
        return self._name

    async def score(self, case: EvalCase, output: str) -> ScorerResult:
        self.calls.append(case)
        return self._result


class _StubJudge:
    """Offline stub SubjectiveJudge — unused (no subjective criteria in tests)."""

    async def judge(
        self, criterion: AcceptanceCriterion, artifacts: dict[str, str]
    ) -> tuple[bool, str]:
        raise NotImplementedError("no subjective criteria exercised by these tests")


class _StubApprovalCallback:
    """Records calls and returns a fixed decision — exercises a real ApprovalGate."""

    def __init__(self, *, approved: bool) -> None:
        self.calls: list[ApprovalRequest] = []
        self._approved = approved

    async def request_approval(self, request: ApprovalRequest) -> ApprovalResponse:
        self.calls.append(request)
        return ApprovalResponse(approved=self._approved, reason="stub")


def _make_engine(
    *,
    planner: _StubPlanner | None = None,
    orchestrator: _StubOrchestrator | None = None,
    approval_gate: ApprovalGate | None = None,
    event_bus: Any | None = None,
) -> tuple[OrchestratorEngine, _StubPlanner, _StubOrchestrator]:
    """Assemble a happy-path engine from all-passing stubs.

    Each test tweaks exactly one axis (planner spy, deploy results,
    engine-level approval gate, or event bus) and leaves the rest at their
    all-passing defaults.
    """
    planner = planner or _StubPlanner(_valid_blueprint())
    critic = _StubCritic(CriticVerdict(passed=True))
    verify_phase = VerifyPhase(
        planner=planner,
        critic=critic,
        approval_gate=ApprovalGate(
            policy=AlwaysDenyPolicy(), callback=_StubApprovalCallback(approved=False)
        ),
        governance=GraphGovernanceConfig(),
    )

    orchestrator = orchestrator or _StubOrchestrator(
        results={"task-1": "artifact body containing the deliverable"}
    )
    deploy_phase = DeployPhase(orchestrator)

    scorer = _StubScorer("unit_scorer", ScorerResult(score=1.0, reason="ok"))
    gate = RoutingContractGate(
        scorers={"unit_scorer": scorer},
        subjective_judge=_StubJudge(),
        approval_gate=ApprovalGate(
            policy=AlwaysDenyPolicy(), callback=_StubApprovalCallback(approved=False)
        ),
    )

    engine = OrchestratorEngine(
        planner,
        verify_phase,
        deploy_phase,
        gate,
        approval_gate=approval_gate,
        event_bus=event_bus,
    )
    return engine, planner, orchestrator


async def test_dynamic_run_end_to_end_offline() -> None:
    """Dynamic mode plans, verifies, deploys, and gates a passing run."""
    # Arrange
    engine, planner, _orchestrator = _make_engine()

    # Act
    result = await engine.run("Build a widget", mode="dynamic")

    # Assert
    assert result.status == "done"
    assert result.verdict is not None
    assert result.verdict.passed is True
    assert result.blueprint is not None
    assert planner.plan_calls == 1


async def test_hardcode_mode_skips_planning() -> None:
    """Hardcode mode never calls the planner's `plan` and still completes."""
    # Arrange
    engine, planner, _orchestrator = _make_engine()
    blueprint = _valid_blueprint()

    # Act
    result = await engine.run(mode="hardcode", blueprint=blueprint)

    # Assert
    assert planner.plan_calls == 0
    assert result.status == "done"


async def test_plan_approval_blocks_deploy_until_go() -> None:
    """A denying plan-approval gate aborts before deploy runs."""
    # Arrange
    approval_gate = ApprovalGate(
        policy=AlwaysDenyPolicy(), callback=_StubApprovalCallback(approved=False)
    )
    engine, _planner, orchestrator = _make_engine(approval_gate=approval_gate)
    config = OrchestratorConfig(require_plan_approval=True)

    # Act
    result = await engine.run("Build a widget", mode="dynamic", config=config)

    # Assert
    assert result.status == "aborted"
    assert orchestrator.delegated == []
    assert result.verdict is None


async def test_approval_off_auto_deploys() -> None:
    """With plan approval disabled, deploy runs automatically."""
    # Arrange
    engine, _planner, orchestrator = _make_engine()
    config = OrchestratorConfig(require_plan_approval=False)

    # Act
    result = await engine.run("Build a widget", mode="dynamic", config=config)

    # Assert
    assert orchestrator.delegated != []
    assert result.status == "done"


async def test_engine_emits_phase_events_in_order() -> None:
    """Phase events fire on the event bus in pipeline order, matching phase_log."""
    # Arrange
    bus = InMemoryEventBus()
    recorded: list[dict[str, Any]] = []
    bus.subscribe("autopilot.phase", lambda data: recorded.append(data))
    engine, _planner, _orchestrator = _make_engine(event_bus=bus)

    # Act
    result = await engine.run("Build a widget", mode="dynamic")

    # Assert
    assert [event["phase"] for event in recorded] == [
        "plan",
        "verify",
        "deploy",
        "gate",
        "done",
    ]
    assert result.phase_log == ("plan", "verify", "deploy", "gate", "done")


async def test_verify_escalation_blocks_deploy() -> None:
    """When pre-deploy verification escalates, the engine returns without deploying."""
    # Arrange — a task targeting a non-existent node fails validation every round,
    # so the verify loop exhausts its budget and escalates to HITL.
    invalid_task = BlueprintTask(
        id="task-x",
        title="Orphan",
        assignee_node_id="ghost-node",
        goal="do it",
    )
    criterion = AcceptanceCriterion(
        id="crit-1", description="d", kind="deterministic", verifier="unit_scorer"
    )
    invalid_blueprint = OrchestrationBlueprint(
        graph=_valid_graph(),
        tasks=(invalid_task,),
        contract=OutputContract(deliverables=("d",), criteria=(criterion,)),
    )
    planner = _StubPlanner(invalid_blueprint)  # plan + replan echo the invalid plan
    verify_callback = _StubApprovalCallback(approved=False)
    verify_phase = VerifyPhase(
        planner=planner,
        critic=_StubCritic(CriticVerdict(passed=True)),
        approval_gate=ApprovalGate(policy=AlwaysDenyPolicy(), callback=verify_callback),
        governance=GraphGovernanceConfig(),
    )
    orchestrator = _StubOrchestrator(results={})
    scorer = _StubScorer("unit_scorer", ScorerResult(score=1.0, reason="ok"))
    gate = RoutingContractGate(
        scorers={"unit_scorer": scorer},
        subjective_judge=_StubJudge(),
        approval_gate=ApprovalGate(
            policy=AlwaysDenyPolicy(), callback=_StubApprovalCallback(approved=False)
        ),
    )
    engine = OrchestratorEngine(planner, verify_phase, DeployPhase(orchestrator), gate)

    # Act
    result = await engine.run("Build a widget", mode="dynamic")

    # Assert — verification escalated, deploy never ran, no verdict.
    assert result.status == "verify_escalated"
    assert result.verdict is None
    assert orchestrator.delegated == []
    assert len(verify_callback.calls) == 1
    assert result.phase_log == ("plan", "verify")


async def test_repaired_blueprint_contract_flows_to_gate_and_result() -> None:
    """After a verify-repair, the REPAIRED blueprint's contract drives gate + result.

    Regression: the engine resolved the contract before verify, so a repair
    that regenerated the contract left gate/result bound to the stale one.
    """

    # Arrange — initial (invalid: ghost node) carries contract A; the replan
    # returns a valid blueprint carrying a DIFFERENT contract B. Both criteria
    # use the same passing scorer, so only the contract identity differs.
    def _crit() -> AcceptanceCriterion:
        return AcceptanceCriterion(
            id="c", description="d", kind="deterministic", verifier="unit_scorer"
        )

    invalid = OrchestrationBlueprint(
        graph=_valid_graph(),
        tasks=(BlueprintTask(id="t", title="T", assignee_node_id="ghost", goal="g"),),
        contract=OutputContract(deliverables=("A",), criteria=(_crit(),)),
    )
    repaired = OrchestrationBlueprint(
        graph=_valid_graph(),
        tasks=(
            BlueprintTask(id="task-1", title="T", assignee_node_id="worker", goal="g"),
        ),
        contract=OutputContract(deliverables=("B",), criteria=(_crit(),)),
    )

    class _RepairPlanner:
        def __init__(self) -> None:
            self.plan_calls = 0

        async def plan(self, goal: str, context: str = "") -> OrchestrationBlueprint:
            self.plan_calls += 1
            return invalid

        async def replan(
            self, blueprint: OrchestrationBlueprint, feedback: str
        ) -> OrchestrationBlueprint:
            return repaired

    planner = _RepairPlanner()
    verify_phase = VerifyPhase(
        planner=planner,
        critic=_StubCritic(CriticVerdict(passed=True)),
        approval_gate=ApprovalGate(
            policy=AlwaysDenyPolicy(), callback=_StubApprovalCallback(approved=False)
        ),
        governance=GraphGovernanceConfig(),
    )
    orchestrator = _StubOrchestrator(results={"task-1": "artifact body"})
    scorer = _StubScorer("unit_scorer", ScorerResult(score=1.0, reason="ok"))
    gate = RoutingContractGate(
        scorers={"unit_scorer": scorer},
        subjective_judge=_StubJudge(),
        approval_gate=ApprovalGate(
            policy=AlwaysDenyPolicy(), callback=_StubApprovalCallback(approved=False)
        ),
    )
    engine = OrchestratorEngine(planner, verify_phase, DeployPhase(orchestrator), gate)

    # Act
    result = await engine.run("Build a widget", mode="dynamic")

    # Assert — the repaired contract (deliverables "B"), not the initial ("A").
    assert result.status == "done"
    assert result.contract is not None
    assert result.contract.deliverables == ("B",)
    assert result.blueprint is repaired


async def test_gate_failure_yields_gate_failed_status() -> None:
    """A contract gate that cannot pass yields status 'gate_failed' with a verdict."""
    # Arrange — a failing scorer and no repair budget so the gate escalates + fails.
    planner = _StubPlanner(_valid_blueprint())
    verify_phase = VerifyPhase(
        planner=planner,
        critic=_StubCritic(CriticVerdict(passed=True)),
        approval_gate=ApprovalGate(
            policy=AlwaysDenyPolicy(), callback=_StubApprovalCallback(approved=False)
        ),
        governance=GraphGovernanceConfig(),
    )
    orchestrator = _StubOrchestrator(results={"task-1": "artifact body"})
    failing_scorer = _StubScorer(
        "unit_scorer", ScorerResult(score=0.0, reason="missing")
    )
    gate = RoutingContractGate(
        scorers={"unit_scorer": failing_scorer},
        subjective_judge=_StubJudge(),
        approval_gate=ApprovalGate(
            policy=AlwaysDenyPolicy(), callback=_StubApprovalCallback(approved=False)
        ),
        repair=None,
    )
    engine = OrchestratorEngine(planner, verify_phase, DeployPhase(orchestrator), gate)

    # Act
    result = await engine.run("Build a widget", mode="dynamic")

    # Assert
    assert result.status == "gate_failed"
    assert result.verdict is not None
    assert result.verdict.passed is False
