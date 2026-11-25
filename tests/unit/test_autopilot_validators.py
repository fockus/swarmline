"""Tests for the deterministic validation layer (pre-deploy, layer 1).

TDD Task 2 of the autopilot-orchestrator spec (Epic G). Covers REQ-005, REQ-022.
Reuses the real `multi_agent.graph_governance` checks — no re-implementation.
"""

from __future__ import annotations

import copy
from typing import Any

from swarmline.multi_agent.graph_governance import GraphGovernanceConfig
from swarmline.orchestration.autopilot.types import (
    AcceptanceCriterion,
    BlueprintTask,
    OrchestrationBlueprint,
    OutputContract,
)
from swarmline.orchestration.autopilot.validators import validate_blueprint


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


def test_validator_flags_task_assigned_to_unknown_node() -> None:
    """A task whose assignee_node_id has no matching graph node is flagged."""
    # Arrange
    blueprint = _valid_blueprint()
    bad_task = BlueprintTask(
        id="task-2",
        title="Orphan task",
        assignee_node_id="ghost-node",
        goal="Do something.",
    )
    blueprint = OrchestrationBlueprint(
        graph=blueprint.graph,
        tasks=(*blueprint.tasks, bad_task),
        contract=blueprint.contract,
    )

    # Act
    problems = validate_blueprint(blueprint, governance=GraphGovernanceConfig())

    # Assert
    assert problems != ()
    assert any("ghost-node" in problem for problem in problems)


def test_validator_flags_capability_subset_violation() -> None:
    """A child node whose allowed_tools exceed its parent's is flagged."""
    # Arrange
    blueprint = _valid_blueprint()
    graph = copy.deepcopy(blueprint.graph)
    graph["children"][0]["allowed_tools"] = ["read", "write", "exec"]
    blueprint = OrchestrationBlueprint(
        graph=graph, tasks=blueprint.tasks, contract=blueprint.contract
    )

    # Act
    problems = validate_blueprint(blueprint, governance=GraphGovernanceConfig())

    # Assert
    assert problems != ()
    assert any("tools" in problem.lower() for problem in problems)


def test_validator_flags_criterion_without_verifier() -> None:
    """A contract criterion with an empty verifier is flagged by id."""
    # Arrange
    blueprint = _valid_blueprint()
    bad_criterion = AcceptanceCriterion(
        id="crit-2",
        description="No verifier here",
        kind="deterministic",
        verifier="",
    )
    contract = OutputContract(
        deliverables=blueprint.contract.deliverables,
        criteria=(*blueprint.contract.criteria, bad_criterion),
    )
    blueprint = OrchestrationBlueprint(
        graph=blueprint.graph, tasks=blueprint.tasks, contract=contract
    )

    # Act
    problems = validate_blueprint(blueprint, governance=GraphGovernanceConfig())

    # Assert
    assert problems != ()
    assert any("crit-2" in problem for problem in problems)


def test_validator_passes_well_formed_blueprint() -> None:
    """A fully valid blueprint yields an empty problems tuple."""
    # Arrange
    blueprint = _valid_blueprint()

    # Act
    problems = validate_blueprint(blueprint, governance=GraphGovernanceConfig())

    # Assert
    assert problems == ()


def test_validator_tolerates_null_capability_fields_without_crashing() -> None:
    """A malformed graph with null capability/tool fields never crashes.

    A deterministic validator must always return a problem tuple — a
    generated blueprint emitting ``"capabilities": null`` (etc.) must not
    raise AttributeError/TypeError before validation completes.
    """
    # Arrange
    graph = {
        "id": "root",
        "name": "Root",
        "role": "lead",
        "capabilities": None,
        "allowed_tools": None,
        "skills": None,
        "hooks": None,
        "children": [
            {
                "id": "c",
                "name": "C",
                "role": "eng",
                "capabilities": None,
                "allowed_tools": None,
                "children": [],
            }
        ],
    }
    blueprint = OrchestrationBlueprint(
        graph=graph, tasks=(), contract=OutputContract(deliverables=(), criteria=())
    )

    # Act — must not raise.
    problems = validate_blueprint(blueprint, governance=GraphGovernanceConfig())

    # Assert
    assert isinstance(problems, tuple)


def test_validator_counts_duplicate_nodes_toward_max_agents() -> None:
    """max_agents compares TOTAL node count, not the unique-id set size."""
    # Arrange — 3 node instances but only 2 unique ids ("root", "w").
    graph = {
        "id": "root",
        "name": "Root",
        "role": "lead",
        "children": [
            {"id": "w", "name": "W", "role": "eng", "children": []},
            {"id": "w", "name": "W2", "role": "eng", "children": []},
        ],
    }
    blueprint = OrchestrationBlueprint(
        graph=graph, tasks=(), contract=OutputContract(deliverables=(), criteria=())
    )

    # Act
    problems = validate_blueprint(
        blueprint, governance=GraphGovernanceConfig(max_agents=2)
    )

    # Assert — unique ids = 2 (not > 2), but 3 total nodes exceed max_agents.
    assert any("max_agents" in problem for problem in problems)
