"""LLM critic: layer-2 pre-deploy blueprint review (Epic G, Task 3).

Covers REQ-001, REQ-002, REQ-006. The critic asks the LLM to assess goal
coverage, role/tool adequacy and contract completeness, and parses the JSON
verdict into `CriticVerdict`. Complements the deterministic validator
(`validators.py`, layer 1) — this layer catches judgement calls a
structural check cannot.
"""

from __future__ import annotations

import json
from typing import Protocol, runtime_checkable

from swarmline.orchestration.autopilot.types import (
    CriticVerdict,
    OrchestrationBlueprint,
)
from swarmline.orchestration.thin_planner import LLMCallable


@runtime_checkable
class BlueprintCritic(Protocol):
    """Reviews a blueprint for goal coverage and contract completeness."""

    async def critique(self, blueprint: OrchestrationBlueprint) -> CriticVerdict: ...


def _extract_json(raw: str) -> str:
    """Strip a leading/trailing ```json ... ``` (or ``` ... ```) fence, if any."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.removesuffix("```").strip()
    return text


class LLMCritic:
    """Single LLM call in, one `CriticVerdict` out."""

    def __init__(self, llm: LLMCallable) -> None:
        self._llm = llm

    async def critique(self, blueprint: OrchestrationBlueprint) -> CriticVerdict:
        """Ask the LLM to judge whether `blueprint` is ready to deploy."""
        prompt = (
            "You are reviewing an orchestration blueprint before deployment. "
            "Assess three things: (1) does the graph's roles/tools cover the "
            "task goals, (2) are tools/skills adequate for each assigned role, "
            "(3) is the output contract complete (deliverables + acceptance "
            "criteria that can actually be verified).\n"
            f"Rationale: {blueprint.rationale}\n"
            f"Graph: {json.dumps(blueprint.graph)}\n"
            f"Tasks: {[(t.id, t.title, t.assignee_node_id, t.goal) for t in blueprint.tasks]}\n"
            f"Contract deliverables: {list(blueprint.contract.deliverables)}\n"
            f"Contract criteria: {[(c.id, c.description, c.kind, c.verifier) for c in blueprint.contract.criteria]}\n\n"
            'Return ONE JSON object: {"passed": bool, "failures": [strings], '
            '"notes": "..."}. Return JSON only, no commentary.'
        )
        raw = await self._llm.generate(prompt)
        data = json.loads(_extract_json(raw))
        return CriticVerdict(
            passed=bool(data.get("passed", False)),
            failures=tuple(data.get("failures", ())),
            notes=data.get("notes", ""),
        )
