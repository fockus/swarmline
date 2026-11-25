"""Tests for the pre-deploy verify-loop + repair budget + HITL escalation.

TDD Task 4 of the autopilot-orchestrator spec (Epic G). Covers REQ-007,
REQ-008, REQ-010. Uses offline stub planner/critic + a REAL ApprovalGate
wired to `AlwaysDenyPolicy` and a stub callback — no network calls.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from swarmline.hitl.gate import ApprovalGate
from swarmline.hitl.policies import AlwaysDenyPolicy
from swarmline.hitl.types import ApprovalRequest, ApprovalResponse
from swarmline.multi_agent.graph_governance import GraphGovernanceConfig
from swarmline.orchestration.autopilot.types import (
    AcceptanceCriterion,
    BlueprintTask,
    CriticVerdict,
    OrchestrationBlueprint,
    OutputContract,
)
from swarmline.orchestration.autopilot.verify_phase import VerifyPhase
from swarmline.orchestration.dod_state_machine import DoDStatus


def _valid_graph() -> dict[str, Any]:
    """A small, well-formed 2-level graph: root -> one child."""
    return {
        "id": "planner",
        "name": "Planner",
        "role": "planner",
        "allowed_tools": ["read", "write"],
        "skills": ["planning"],
        "hooks": [],
        "children": [
            {
                "id": "worker",
                "name": "Worker",
                "role": "engineer",
                "allowed_tools": ["read"],
                "skills": [],
                "hooks": [],
                "children": [],
            }
        ],
    }


def _valid_blueprint() -> OrchestrationBlueprint:
    graph = _valid_graph()
    task = BlueprintTask(
        id="task-1",
        title="Implement feature",
        assignee_node_id="worker",
        goal="Build the feature end to end.",
    )
    criterion = AcceptanceCriterion(
        id="crit-1",
        description="Tests pass",
        kind="deterministic",
        verifier="pytest_scorer",
    )
    contract = OutputContract(
        deliverables=("src/feature.py",),
        criteria=(criterion,),
    )
    return OrchestrationBlueprint(graph=graph, tasks=(task,), contract=contract)


def _invalid_blueprint() -> OrchestrationBlueprint:
    """A blueprint with a task assigned to a non-existent node id."""
    blueprint = _valid_blueprint()
    bad_task = BlueprintTask(
        id="task-2",
        title="Orphan task",
        assignee_node_id="ghost-node",
        goal="Do something.",
    )
    return OrchestrationBlueprint(
        graph=blueprint.graph,
        tasks=(bad_task,),
        contract=blueprint.contract,
    )


class _StubPlanner:
    """Offline stub `Planner` — `replan` returns queued blueprints in order."""

    def __init__(self, replan_queue: list[OrchestrationBlueprint]) -> None:
        self._queue = list(replan_queue)
        self.replan_calls = 0

    async def plan(self, goal: str, context: str = "") -> OrchestrationBlueprint:
        raise NotImplementedError("not exercised by verify_phase tests")

    async def replan(
        self, blueprint: OrchestrationBlueprint, feedback: str
    ) -> OrchestrationBlueprint:
        self.replan_calls += 1
        if self._queue:
            return self._queue.pop(0)
        return copy.deepcopy(blueprint)


class _StubCritic:
    """Offline stub `BlueprintCritic` returning a fixed verdict."""

    def __init__(self, verdict: CriticVerdict) -> None:
        self._verdict = verdict
        self.critique_calls = 0

    async def critique(self, blueprint: OrchestrationBlueprint) -> CriticVerdict:
        self.critique_calls += 1
        return self._verdict


class _StubApprovalCallback:
    """Records calls and always denies — exercises the real ApprovalGate."""

    def __init__(self) -> None:
        self.calls: list[ApprovalRequest] = []

    async def request_approval(self, request: ApprovalRequest) -> ApprovalResponse:
        self.calls.append(request)
        return ApprovalResponse(approved=False, reason="human declined")


async def test_verify_passes_on_clean_blueprint_first_try() -> None:
    """A valid blueprint + a passing critic verdict passes on iteration 1."""
    # Arrange
    blueprint = _valid_blueprint()
    planner = _StubPlanner(replan_queue=[])
    critic = _StubCritic(CriticVerdict(passed=True))
    callback = _StubApprovalCallback()
    gate = ApprovalGate(policy=AlwaysDenyPolicy(), callback=callback)
    phase = VerifyPhase(
        planner=planner,
        critic=critic,
        approval_gate=gate,
        governance=GraphGovernanceConfig(),
    )

    # Act
    outcome = await phase.run(blueprint, max_plan_repair=3)

    # Assert
    assert outcome.status == DoDStatus.PASSED
    assert outcome.iterations == 1
    assert outcome.escalated is False
    assert outcome.blueprint == blueprint
    assert planner.replan_calls == 0
    assert callback.calls == []


async def test_verify_repairs_then_passes_within_budget() -> None:
    """An invalid blueprint gets repaired once by the planner, then passes."""
    # Arrange
    bad_blueprint = _invalid_blueprint()
    good_blueprint = _valid_blueprint()
    planner = _StubPlanner(replan_queue=[good_blueprint])
    critic = _StubCritic(CriticVerdict(passed=True))
    callback = _StubApprovalCallback()
    gate = ApprovalGate(policy=AlwaysDenyPolicy(), callback=callback)
    phase = VerifyPhase(
        planner=planner,
        critic=critic,
        approval_gate=gate,
        governance=GraphGovernanceConfig(),
    )

    # Act
    outcome = await phase.run(bad_blueprint, max_plan_repair=3)

    # Assert
    assert outcome.status == DoDStatus.PASSED
    assert outcome.iterations == 2
    assert outcome.escalated is False
    assert outcome.blueprint == good_blueprint
    assert planner.replan_calls == 1
    assert callback.calls == []


async def test_verify_exhausts_budget_then_escalates_hitl() -> None:
    """Repair never succeeds -> budget exhausted -> HITL escalation fires once."""
    # Arrange
    bad_blueprint = _invalid_blueprint()
    planner = _StubPlanner(replan_queue=[])  # replan always echoes back invalid
    critic = _StubCritic(CriticVerdict(passed=False, failures=("weak contract",)))
    callback = _StubApprovalCallback()
    gate = ApprovalGate(policy=AlwaysDenyPolicy(), callback=callback)
    phase = VerifyPhase(
        planner=planner,
        critic=critic,
        approval_gate=gate,
        governance=GraphGovernanceConfig(),
    )

    # Act
    outcome = await phase.run(bad_blueprint, max_plan_repair=3)

    # Assert
    assert outcome.status == DoDStatus.MAX_LOOPS_EXCEEDED
    # 4 verification rounds: the initial + one recheck after each of the 3 replans.
    assert outcome.iterations == 4
    assert outcome.escalated is True
    assert outcome.approved is False
    assert len(callback.calls) == 1
    assert outcome.problems != ()


async def test_verify_rejects_non_positive_repair_budget() -> None:
    """A max_plan_repair < 1 fails fast (mirrors DoDStateMachine's contract)."""
    # Arrange
    planner = _StubPlanner(replan_queue=[])
    critic = _StubCritic(CriticVerdict(passed=True))
    gate = ApprovalGate(policy=AlwaysDenyPolicy(), callback=_StubApprovalCallback())
    phase = VerifyPhase(
        planner=planner,
        critic=critic,
        approval_gate=gate,
        governance=GraphGovernanceConfig(),
    )

    # Act / Assert
    with pytest.raises(ValueError, match="max_plan_repair"):
        await phase.run(_valid_blueprint(), max_plan_repair=0)


async def test_verify_repair_on_final_attempt_is_rechecked_not_escalated() -> None:
    """A within-budget replan on the LAST attempt is re-verified, not escalated.

    Regression: with ``max_plan_repair=1`` the single replan's blueprint must
    be re-verified; the off-by-one bug replanned then escalated without
    checking the fixed plan.
    """
    # Arrange
    bad_blueprint = _invalid_blueprint()
    good_blueprint = _valid_blueprint()
    planner = _StubPlanner(replan_queue=[good_blueprint])
    critic = _StubCritic(CriticVerdict(passed=True))
    callback = _StubApprovalCallback()
    gate = ApprovalGate(policy=AlwaysDenyPolicy(), callback=callback)
    phase = VerifyPhase(
        planner=planner,
        critic=critic,
        approval_gate=gate,
        governance=GraphGovernanceConfig(),
    )

    # Act — only ONE replan allowed; it fixes the plan.
    outcome = await phase.run(bad_blueprint, max_plan_repair=1)

    # Assert — the repaired plan was re-verified and passed; no escalation.
    assert outcome.status == DoDStatus.PASSED
    assert outcome.iterations == 2
    assert outcome.escalated is False
    assert planner.replan_calls == 1
    assert callback.calls == []
