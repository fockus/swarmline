"""Tests for the LLM planner (emits blueprint from goal + feedback).

TDD Task 3 of the autopilot-orchestrator spec (Epic G). Covers REQ-001,
REQ-002, REQ-006. Uses an offline stub LLM — no network calls.
"""

from __future__ import annotations

import json

from swarmline.orchestration.autopilot.planner import LLMPlanner, Planner
from swarmline.orchestration.autopilot.types import OrchestrationBlueprint

_BLUEPRINT_JSON = {
    "graph": {
        "id": "planner",
        "name": "Planner",
        "role": "planner",
        "allowed_tools": ["read", "write"],
        "children": [
            {
                "id": "worker",
                "name": "Worker",
                "role": "engineer",
                "allowed_tools": ["read"],
                "children": [],
            }
        ],
    },
    "tasks": [
        {
            "id": "task-1",
            "title": "Implement feature",
            "assignee_node_id": "worker",
            "goal": "Build the feature end to end.",
            "depends_on": [],
        }
    ],
    "contract": {
        "deliverables": ["src/feature.py"],
        "criteria": [
            {
                "id": "crit-1",
                "description": "Tests pass",
                "kind": "deterministic",
                "verifier": "pytest_scorer",
            }
        ],
        "output_schema": None,
        "constraints": [],
    },
    "rationale": "Two-node graph covers implementation and review.",
}


class _StubLLM:
    """Offline stub returning a fixed response, no network involved."""

    def __init__(self, response: str) -> None:
        self._r = response
        self.last_prompt: str = ""

    async def generate(self, prompt: str) -> str:
        self.last_prompt = prompt
        return self._r


async def test_llm_planner_parses_blueprint_from_stub_output() -> None:
    """LLMPlanner.plan parses the stub JSON into a valid OrchestrationBlueprint."""
    # Arrange
    stub = _StubLLM(json.dumps(_BLUEPRINT_JSON))
    planner = LLMPlanner(llm=stub)

    # Act
    blueprint = await planner.plan("Build a feature", context="repo: swarmline")

    # Assert
    assert isinstance(planner, Planner)
    assert isinstance(blueprint, OrchestrationBlueprint)
    assert blueprint.graph == _BLUEPRINT_JSON["graph"]

    assert len(blueprint.tasks) == 1
    task = blueprint.tasks[0]
    assert task.id == "task-1"
    assert task.title == "Implement feature"
    assert task.assignee_node_id == "worker"
    assert task.goal == "Build the feature end to end."
    assert task.depends_on == ()

    assert len(blueprint.contract.criteria) == 1
    criterion = blueprint.contract.criteria[0]
    assert criterion.id == "crit-1"
    assert criterion.description == "Tests pass"
    assert criterion.kind == "deterministic"
    assert criterion.verifier == "pytest_scorer"
    assert blueprint.contract.deliverables == ("src/feature.py",)
    assert blueprint.contract.constraints == ()
    assert blueprint.contract.output_schema is None

    assert isinstance(blueprint.tasks, tuple)
    assert isinstance(blueprint.contract.deliverables, tuple)
    assert isinstance(blueprint.contract.criteria, tuple)
    assert isinstance(blueprint.contract.constraints, tuple)
    assert isinstance(task.depends_on, tuple)


async def test_planner_replan_incorporates_feedback() -> None:
    """LLMPlanner.replan threads the feedback string into the LLM prompt."""
    # Arrange
    stub = _StubLLM(json.dumps(_BLUEPRINT_JSON))
    planner = LLMPlanner(llm=stub)
    original = await planner.plan("Build a feature")

    # Act
    revised = await planner.replan(original, "add a reviewer node")

    # Assert
    assert "add a reviewer node" in stub.last_prompt
    assert isinstance(revised, OrchestrationBlueprint)
    assert len(revised.tasks) == 1
