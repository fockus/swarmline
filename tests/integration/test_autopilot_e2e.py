"""Offline end-to-end tests for the public `swarmline.orchestration.autopilot` API.

TDD Task 9 of the autopilot-orchestrator spec (Epic G). Covers REQ-001,
REQ-016, REQ-021, REQ-022. Wires the REAL phase components (`LLMPlanner`,
`LLMCritic`, `VerifyPhase`, `DeployPhase`, `RoutingContractGate`,
`OrchestratorEngine`) end to end through the public package `__init__`.
Only the `LLMCallable` (planner/critic input) and the graph-execution
orchestrator (`GraphHandoffRunner`) are stubbed — everything else,
including a REAL `ContainsScorer` and a REAL `ApprovalGate`, is exercised
for real, offline.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import swarmline.orchestration.autopilot as ap
from swarmline.eval.scorers import ContainsScorer
from swarmline.hitl.gate import ApprovalGate
from swarmline.hitl.policies import AlwaysDenyPolicy
from swarmline.hitl.types import ApprovalRequest, ApprovalResponse
from swarmline.multi_agent.graph_governance import GraphGovernanceConfig

DELIVERABLE_TOKEN = "WIDGET_BUILT_OK"


def _graph_dict() -> dict[str, Any]:
    """A minimal well-formed 2-node graph: root -> one child."""
    return {
        "id": "root",
        "name": "Root",
        "role": "planner",
        "allowed_tools": [],
        "skills": [],
        "hooks": [],
        "children": [
            {
                "id": "child",
                "name": "Child",
                "role": "engineer",
                "allowed_tools": [],
                "skills": [],
                "hooks": [],
                "children": [],
            }
        ],
    }


def _valid_blueprint_json() -> str:
    """A well-formed blueprint: task assigned to the real 'child' node."""
    return json.dumps(
        {
            "graph": _graph_dict(),
            "tasks": [
                {
                    "id": "t1",
                    "title": "Build the widget",
                    "assignee_node_id": "child",
                    "goal": "Build the widget end to end.",
                    "depends_on": [],
                }
            ],
            "contract": {
                "deliverables": ["widget"],
                "criteria": [
                    {
                        "id": "c1",
                        "description": DELIVERABLE_TOKEN,
                        "kind": "deterministic",
                        "verifier": "contains",
                    }
                ],
                "output_schema": None,
                "constraints": [],
            },
            "rationale": "Single child builds the widget.",
        }
    )


def _invalid_blueprint_json() -> str:
    """A blueprint whose task targets a NON-EXISTENT graph node."""
    return json.dumps(
        {
            "graph": _graph_dict(),
            "tasks": [
                {
                    "id": "t1",
                    "title": "Build the widget",
                    "assignee_node_id": "ghost-node",
                    "goal": "Build the widget end to end.",
                    "depends_on": [],
                }
            ],
            "contract": {
                "deliverables": ["widget"],
                "criteria": [
                    {
                        "id": "c1",
                        "description": DELIVERABLE_TOKEN,
                        "kind": "deterministic",
                        "verifier": "contains",
                    }
                ],
                "output_schema": None,
                "constraints": [],
            },
            "rationale": "Broken: assignee does not exist.",
        }
    )


class _StubLLM:
    """Offline stub `LLMCallable` — always returns the same canned JSON reply."""

    def __init__(self, reply: str) -> None:
        self._reply = reply
        self.calls = 0

    async def generate(self, prompt: str) -> str:
        self.calls += 1
        return self._reply


class _StubGraphHandoffRunner:
    """Offline stub `GraphHandoffRunner` — canned artifact string per task id."""

    def __init__(self, results: dict[str, str]) -> None:
        self._results = results
        self.delegated: list[Any] = []

    async def delegate(self, request: Any) -> None:
        self.delegated.append(request)

    async def wait_for_task(
        self, task_id: str, timeout: float | None = None
    ) -> str | None:
        return self._results.get(task_id)


class _StubJudge:
    """Offline stub `SubjectiveJudge` — unused (no subjective criteria here)."""

    async def judge(
        self, criterion: ap.AcceptanceCriterion, artifacts: dict[str, str]
    ) -> tuple[bool, str]:
        raise NotImplementedError("no subjective criteria exercised by these tests")


class _StubApprovalCallback:
    """Records calls and returns a fixed decision — exercises a REAL ApprovalGate."""

    def __init__(self, *, approved: bool) -> None:
        self.calls: list[ApprovalRequest] = []
        self._approved = approved

    async def request_approval(self, request: ApprovalRequest) -> ApprovalResponse:
        self.calls.append(request)
        return ApprovalResponse(approved=self._approved, reason="stub")


def _make_verify_phase(
    planner: ap.Planner, *, critic_passes: bool = True
) -> ap.VerifyPhase:
    critic = ap.LLMCritic(
        _StubLLM(json.dumps({"passed": critic_passes, "failures": [], "notes": "ok"}))
    )
    approval_gate = ApprovalGate(
        policy=AlwaysDenyPolicy(), callback=_StubApprovalCallback(approved=False)
    )
    return ap.VerifyPhase(
        planner,
        critic,
        approval_gate,
        governance=GraphGovernanceConfig(),
    )


def _make_gate() -> ap.RoutingContractGate:
    return ap.RoutingContractGate(
        scorers={"contains": ContainsScorer()},
        subjective_judge=_StubJudge(),
        approval_gate=ApprovalGate(
            policy=AlwaysDenyPolicy(), callback=_StubApprovalCallback(approved=False)
        ),
    )


async def test_public_exports_importable() -> None:
    """Every name in `ap.__all__` resolves to a real attribute of the package."""
    # Arrange / Act
    missing = [name for name in ap.__all__ if not hasattr(ap, name)]

    # Assert
    assert missing == []
    assert ap.OrchestratorEngine is not None
    assert ap.OrchestratorConfig is not None
    assert ap.OrchestrationBlueprint is not None
    assert ap.OutputContract is not None
    assert ap.create_orchestrate_tool is not None


async def test_autopilot_dynamic_e2e_offline() -> None:
    """A fully-wired engine run: real planner/critic/verify/deploy/gate, dynamic mode."""
    # Arrange
    planner_llm = _StubLLM(_valid_blueprint_json())
    planner = ap.LLMPlanner(planner_llm)
    verify_phase = _make_verify_phase(planner)
    orchestrator = _StubGraphHandoffRunner(
        results={"t1": f"artifact body: {DELIVERABLE_TOKEN}"}
    )
    deploy_phase = ap.DeployPhase(orchestrator)
    gate = _make_gate()
    engine = ap.OrchestratorEngine(planner, verify_phase, deploy_phase, gate)

    # Act
    result = await engine.run("Build a widget", mode="dynamic")

    # Assert
    assert result.status == "done"
    assert result.verdict is not None
    assert result.verdict.passed is True
    assert result.blueprint is not None
    assert result.phase_log == ("plan", "verify", "deploy", "gate", "done")


async def test_autopilot_repair_then_hitl_escalation_e2e() -> None:
    """Assignee-to-a-non-existent-node keeps failing verification through every
    repair, exhausting the plan-repair budget and escalating to a REAL HITL
    `ApprovalGate` — deploy never runs and no gate verdict is produced.
    """
    # Arrange — plan() AND replan() both echo the same invalid blueprint json
    # (the stub LLM always returns the same canned reply), so the verify loop
    # never clears and exhausts `max_plan_repair`.
    planner_llm = _StubLLM(_invalid_blueprint_json())
    planner = ap.LLMPlanner(planner_llm)
    verify_phase = _make_verify_phase(planner, critic_passes=True)
    orchestrator = _StubGraphHandoffRunner(results={})
    deploy_phase = ap.DeployPhase(orchestrator)
    gate = _make_gate()
    engine = ap.OrchestratorEngine(planner, verify_phase, deploy_phase, gate)

    # Act
    result = await engine.run("Build a widget", mode="dynamic")

    # Assert
    assert result.status == "verify_escalated"
    assert orchestrator.delegated == []
    assert result.verdict is None


def test_importing_autopilot_does_not_pull_supervisor() -> None:
    """Import-light proof for the supervisor-opt-in exception (deploy_phase).

    `deploy_phase.py` is a sanctioned outside caller of the opt-in
    `orchestration/supervisor` package, but its `handoff()` import stays LAZY
    (inside `deploy()`; the `GraphHandoffRunner` annotation is TYPE_CHECKING
    only). So merely importing the public `swarmline.orchestration.autopilot`
    package must NOT drag the supervisor package into `sys.modules`. Run in a
    fresh subprocess so an unrelated in-process import cannot mask a leak.
    """
    repo_root = Path(__file__).resolve().parents[2]
    code = (
        "import swarmline.orchestration.autopilot\n"
        "import sys\n"
        "leaked = [m for m in sys.modules if 'orchestration.supervisor' in m]\n"
        "assert not leaked, leaked\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
