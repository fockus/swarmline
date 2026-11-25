"""Tests for the LLM critic (layer 2, pre-deploy blueprint review).

TDD Task 3 of the autopilot-orchestrator spec (Epic G). Covers REQ-001,
REQ-002, REQ-006. Uses an offline stub LLM — no network calls.
"""

from __future__ import annotations

import json

from swarmline.orchestration.autopilot.critic import BlueprintCritic, LLMCritic
from swarmline.orchestration.autopilot.types import (
    BlueprintTask,
    OrchestrationBlueprint,
    OutputContract,
)


class _StubLLM:
    """Offline stub returning a fixed response, no network involved."""

    def __init__(self, response: str) -> None:
        self._r = response

    async def generate(self, prompt: str) -> str:
        return self._r


def _incomplete_blueprint() -> OrchestrationBlueprint:
    graph = {"id": "root", "name": "Root", "role": "planner", "children": []}
    task = BlueprintTask(
        id="task-1",
        title="Do the thing",
        assignee_node_id="root",
        goal="Do the thing.",
    )
    contract = OutputContract(deliverables=(), criteria=())
    return OrchestrationBlueprint(graph=graph, tasks=(task,), contract=contract)


async def test_critic_returns_failures_for_incomplete_contract() -> None:
    """LLMCritic.critique surfaces LLM-reported failures for a weak contract."""
    # Arrange
    response = json.dumps(
        {
            "passed": False,
            "failures": ["contract missing acceptance criteria"],
            "notes": "Add at least one acceptance criterion before deploy.",
        }
    )
    stub = _StubLLM(response)
    critic = LLMCritic(llm=stub)
    blueprint = _incomplete_blueprint()

    # Act
    verdict = await critic.critique(blueprint)

    # Assert
    assert isinstance(critic, BlueprintCritic)
    assert verdict.passed is False
    assert verdict.failures != ()
    assert any(
        "contract missing acceptance criteria" in failure
        for failure in verdict.failures
    )
    assert isinstance(verdict.failures, tuple)
