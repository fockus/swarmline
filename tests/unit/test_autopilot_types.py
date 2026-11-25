"""Tests for autopilot domain value types (Blueprint, Contract, Result, Config).

TDD Task 1 of the autopilot-orchestrator spec (Epic G).
All types are frozen dataclasses, stdlib-only.
"""

from __future__ import annotations

import dataclasses

import pytest

from swarmline.orchestration.autopilot.types import (
    AcceptanceCriterion,
    BlueprintTask,
    CriticVerdict,
    GateVerdict,
    OrchestrationBlueprint,
    OrchestrationPhase,
    OrchestrationResult,
    OrchestratorConfig,
    OutputContract,
)


def test_blueprint_is_frozen_and_carries_graph_tasks_contract() -> None:
    """Blueprint stores graph/tasks/contract and rejects attribute reassignment."""
    # Arrange
    graph = {"nodes": ["planner", "worker"], "edges": [("planner", "worker")]}
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

    # Act
    blueprint = OrchestrationBlueprint(graph=graph, tasks=(task,), contract=contract)

    # Assert
    assert blueprint.graph == graph
    assert blueprint.tasks == (task,)
    assert blueprint.contract == contract
    assert blueprint.rationale == ""
    with pytest.raises(dataclasses.FrozenInstanceError):
        blueprint.rationale = "mutated"  # type: ignore[misc]


@pytest.mark.parametrize("kind", ["deterministic", "subjective"])
def test_contract_criterion_kind_is_deterministic_or_subjective(kind: str) -> None:
    """AcceptanceCriterion accepts both kind values and round-trips the field."""
    # Arrange & Act
    criterion = AcceptanceCriterion(
        id="crit-1",
        description="Check something",
        kind=kind,  # type: ignore[arg-type]
        verifier="some_verifier",
    )

    # Assert
    assert criterion.kind == kind


def test_orchestrator_config_defaults() -> None:
    """OrchestratorConfig() yields the documented default budgets/flags."""
    # Arrange & Act
    config = OrchestratorConfig()

    # Assert
    assert config.max_plan_repair == 3
    assert config.max_gate_repair == 3
    assert config.require_plan_approval is False
    assert config.max_recursion_depth == 2
    assert config.verifiers == ()


def test_output_contract_defaults_are_empty_and_none() -> None:
    """OutputContract defaults constraints to empty tuple and output_schema to None."""
    # Arrange & Act
    contract = OutputContract(deliverables=(), criteria=())

    # Assert
    assert contract.constraints == ()
    assert contract.output_schema is None


def test_orchestration_phase_members_have_lowercase_values() -> None:
    """OrchestrationPhase enum members map to their lowercase name as value."""
    # Arrange & Act & Assert
    assert OrchestrationPhase.PLAN.value == "plan"
    assert OrchestrationPhase.VERIFY.value == "verify"
    assert OrchestrationPhase.APPROVAL.value == "approval"
    assert OrchestrationPhase.DEPLOY.value == "deploy"
    assert OrchestrationPhase.GATE.value == "gate"
    assert OrchestrationPhase.REPAIR.value == "repair"
    assert OrchestrationPhase.DONE.value == "done"


def test_gate_and_critic_verdicts_default_to_empty_failures() -> None:
    """GateVerdict and CriticVerdict default failures to an empty tuple."""
    # Arrange & Act
    gate_verdict = GateVerdict(passed=True)
    critic_verdict = CriticVerdict(passed=True)

    # Assert
    assert gate_verdict.failures == ()
    assert gate_verdict.log == ""
    assert critic_verdict.failures == ()
    assert critic_verdict.notes == ""


def test_orchestration_result_holds_optional_blueprint_contract_verdict() -> None:
    """OrchestrationResult accepts None for blueprint/contract/verdict and defaults phase_log."""
    # Arrange & Act
    result = OrchestrationResult(
        status="done",
        blueprint=None,
        contract=None,
        verdict=None,
    )

    # Assert
    assert result.status == "done"
    assert result.blueprint is None
    assert result.contract is None
    assert result.verdict is None
    assert result.phase_log == ()
    assert result.board_snapshot is None
