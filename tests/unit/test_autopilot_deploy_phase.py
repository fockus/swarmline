"""Tests for the deploy phase: materialize graph + seed board + execute via handoff.

TDD Task 5A of the autopilot-orchestrator spec (Epic G). Covers REQ-013
(materialize graph via `GraphBuilder.from_dict` + seed `InMemoryGraphTaskBoard`
with one `GraphTaskItem` per `BlueprintTask`) and REQ-014 (execute each task
through the H6 `handoff()` seam against an injected `GraphHandoffRunner`).
Uses an offline stub orchestrator — no network calls.

REQ-015 (per-node distinct runtime/provider dispatch) is Epic-F4-gated and
deliberately NOT covered here — see `deploy_phase.py` module docstring.
"""

from __future__ import annotations

from typing import Any

from swarmline.orchestration.autopilot.deploy_phase import DeployPhase
from swarmline.orchestration.autopilot.types import (
    AcceptanceCriterion,
    BlueprintTask,
    OrchestrationBlueprint,
    OutputContract,
)


def _valid_graph() -> dict[str, Any]:
    """A small, well-formed 2-level graph: root -> one child."""
    return {
        "id": "root",
        "name": "Root",
        "role": "lead",
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


def _blueprint() -> OrchestrationBlueprint:
    graph = _valid_graph()
    tasks = (
        BlueprintTask(
            id="task-root",
            title="Lead the effort",
            assignee_node_id="root",
            goal="Coordinate the build.",
        ),
        BlueprintTask(
            id="task-worker",
            title="Build the feature",
            assignee_node_id="worker",
            goal="Implement the feature end to end.",
        ),
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
    return OrchestrationBlueprint(graph=graph, tasks=tasks, contract=contract)


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


async def test_deploy_materializes_graph_and_seeds_board_with_goals() -> None:
    """`deploy` builds a 2-node graph snapshot and seeds one board task per
    `BlueprintTask`, carrying the task's assignee and goal across."""
    # Arrange
    blueprint = _blueprint()
    orchestrator = _StubOrchestrator(results={})
    phase = DeployPhase(orchestrator)

    # Act
    result = await phase.deploy(blueprint)

    # Assert
    assert {node.id for node in result.snapshot.nodes} == {"root", "worker"}
    assert len(result.board_snapshot) == 2
    by_id = {item.id: item for item in result.board_snapshot}
    assert by_id["task-root"].assignee_agent_id == "root"
    assert by_id["task-root"].description == "Coordinate the build."
    assert by_id["task-worker"].assignee_agent_id == "worker"
    assert by_id["task-worker"].description == "Implement the feature end to end."


async def test_deploy_executes_via_handoff_over_graph_orchestrator() -> None:
    """`deploy` hands each `BlueprintTask` off through `handoff()` against
    the injected orchestrator, and collects its result string into artifacts."""
    # Arrange
    blueprint = _blueprint()
    orchestrator = _StubOrchestrator(
        results={
            "task-root": "root done",
            "task-worker": "worker done",
        }
    )
    phase = DeployPhase(orchestrator)

    # Act
    result = await phase.deploy(blueprint)

    # Assert
    assert len(orchestrator.delegated) == 2
    assert {req.task_id for req in orchestrator.delegated} == {
        "task-root",
        "task-worker",
    }
    assert result.artifacts == {
        "task-root": "root done",
        "task-worker": "worker done",
    }
