"""LLM planner: emits an OrchestrationBlueprint from a goal (Epic G, Task 3).

Covers REQ-001, REQ-002, REQ-006. The planner asks the LLM for ONE JSON object
holding a GraphBuilder-schema graph dict, tasks, an output contract and a
rationale, then parses it verbatim into the frozen domain types — no
translation layer sits between the LLM output and `GraphBuilder.from_dict`.
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

from swarmline.orchestration.autopilot.types import (
    AcceptanceCriterion,
    BlueprintTask,
    OrchestrationBlueprint,
    OutputContract,
)
from swarmline.orchestration.thin_planner import LLMCallable


@runtime_checkable
class Planner(Protocol):
    """Generates and revises orchestration blueprints from a goal."""

    async def plan(self, goal: str, context: str = "") -> OrchestrationBlueprint: ...

    async def replan(
        self, blueprint: OrchestrationBlueprint, feedback: str
    ) -> OrchestrationBlueprint: ...


def _extract_json(raw: str) -> str:
    """Strip a leading/trailing ```json ... ``` (or ``` ... ```) fence, if any."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.removesuffix("```").strip()
    return text


class LLMPlanner:
    """ThinPlanner-style planner: one LLM call in, one blueprint out.

    SRP: delegates all reasoning to the injected `LLMCallable`; this class
    only builds prompts and parses the resulting JSON into domain types.
    """

    def __init__(self, llm: LLMCallable) -> None:
        self._llm = llm

    async def plan(self, goal: str, context: str = "") -> OrchestrationBlueprint:
        """Generate a fresh blueprint for `goal` through the LLM."""
        prompt = (
            "You are an orchestration planner. Design a multi-agent graph and "
            "task plan to achieve the goal below.\n"
            f"Goal: {goal}\n"
            f"Context: {context}\n\n"
            "Return ONE JSON object with exactly these keys:\n"
            '  "graph": a nested node dict — each node has "id", "name", "role", '
            'optional "system_prompt", "allowed_tools" (list), "skills" (list), '
            '"hooks" (list), "capabilities" (dict), "runtime", and "children" '
            "(list of nodes, same shape, recursively).\n"
            '  "tasks": a list of {"id", "title", "assignee_node_id", "goal", '
            '"depends_on"} (assignee_node_id must reference a node id in "graph").\n'
            '  "contract": {"deliverables": [...], "criteria": '
            '[{"id","description","kind":"deterministic"|"subjective","verifier"}], '
            '"output_schema": {...} or null, "constraints": [...]}.\n'
            '  "rationale": a short string explaining the design.\n'
            "Return JSON only, no commentary."
        )
        return await self._generate_blueprint(prompt)

    async def replan(
        self, blueprint: OrchestrationBlueprint, feedback: str
    ) -> OrchestrationBlueprint:
        """Regenerate the blueprint, folding `feedback` into the prompt."""
        prior = {
            "graph": blueprint.graph,
            "tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "assignee_node_id": t.assignee_node_id,
                    "goal": t.goal,
                    "depends_on": list(t.depends_on),
                }
                for t in blueprint.tasks
            ],
            "contract": {
                "deliverables": list(blueprint.contract.deliverables),
                "criteria": [
                    {
                        "id": c.id,
                        "description": c.description,
                        "kind": c.kind,
                        "verifier": c.verifier,
                    }
                    for c in blueprint.contract.criteria
                ],
                "output_schema": blueprint.contract.output_schema,
                "constraints": list(blueprint.contract.constraints),
            },
        }
        prompt = (
            "You are revising a previous orchestration blueprint based on "
            "feedback.\n"
            f"Previous rationale: {blueprint.rationale}\n"
            f"Previous blueprint: {json.dumps(prior)}\n"
            f"Feedback: {feedback}\n\n"
            "Return ONE revised JSON object with the same shape as the previous "
            'blueprint — keys "graph", "tasks", "contract", "rationale" — that '
            "addresses the feedback. Return JSON only, no commentary."
        )
        return await self._generate_blueprint(prompt)

    async def _generate_blueprint(self, prompt: str) -> OrchestrationBlueprint:
        """Call the LLM, parse its JSON reply, and build a blueprint."""
        raw = await self._llm.generate(prompt)
        data = json.loads(_extract_json(raw))

        tasks = tuple(
            BlueprintTask(
                id=t["id"],
                title=t["title"],
                assignee_node_id=t["assignee_node_id"],
                goal=t["goal"],
                depends_on=tuple(t.get("depends_on", ())),
            )
            for t in data.get("tasks", [])
        )

        contract_data: dict[str, Any] = data.get("contract", {})
        criteria = tuple(
            AcceptanceCriterion(
                id=c["id"],
                description=c["description"],
                kind=c["kind"],
                verifier=c["verifier"],
            )
            for c in contract_data.get("criteria", [])
        )
        contract = OutputContract(
            deliverables=tuple(contract_data.get("deliverables", ())),
            criteria=criteria,
            output_schema=contract_data.get("output_schema"),
            constraints=tuple(contract_data.get("constraints", ())),
        )

        return OrchestrationBlueprint(
            graph=data["graph"],
            tasks=tasks,
            contract=contract,
            rationale=data.get("rationale", ""),
        )
