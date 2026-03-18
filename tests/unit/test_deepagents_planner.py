"""Tests DeepAgentsPlannerMode - TDD with mocknutym LangChain. Optional dependency: if langchain not ustanovlen -> error.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock


def _plan_json(goal: str = "test") -> str:
    return json.dumps(
        {
            "goal": goal,
            "steps": [
                {"id": "s1", "description": "step 1"},
                {"id": "s2", "description": "step 2"},
            ],
        }
    )


class TestDeepAgentsPlannerGenerate:
    """generate_plan with mocknutym LLM."""

    async def test_generate_plan(self) -> None:
        from cognitia.orchestration.deepagents_planner import DeepAgentsPlannerMode
        from cognitia.orchestration.plan_store import InMemoryPlanStore

        store = InMemoryPlanStore()
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = _plan_json("Подобрать вклад")

        planner = DeepAgentsPlannerMode(llm=mock_llm, plan_store=store)
        plan = await planner.generate_plan("Подобрать вклад", "контекст")

        assert plan.goal == "Подобрать вклад"
        assert plan.status == "draft"
        assert len(plan.steps) == 2

    async def test_approve(self) -> None:
        from cognitia.orchestration.deepagents_planner import DeepAgentsPlannerMode
        from cognitia.orchestration.plan_store import InMemoryPlanStore

        store = InMemoryPlanStore()
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = _plan_json()

        planner = DeepAgentsPlannerMode(llm=mock_llm, plan_store=store)
        plan = await planner.generate_plan("g", "c")
        approved = await planner.approve(plan, by="system")
        assert approved.status == "approved"

    async def test_execute_step(self) -> None:
        from cognitia.orchestration.deepagents_planner import DeepAgentsPlannerMode
        from cognitia.orchestration.plan_store import InMemoryPlanStore

        store = InMemoryPlanStore()
        mock_llm = AsyncMock()
        mock_llm.generate.side_effect = [
            _plan_json(),
            json.dumps({"step_id": "s1", "result": "done"}),
        ]

        planner = DeepAgentsPlannerMode(llm=mock_llm, plan_store=store)
        plan = await planner.generate_plan("g", "c")
        plan = await planner.approve(plan, by="system")
        step = await planner.execute_step(plan, "s1")

        assert step.status == "completed"
        assert step.result == "done"

    async def test_execute_all_marks_plan_completed(self) -> None:
        from cognitia.orchestration.deepagents_planner import DeepAgentsPlannerMode
        from cognitia.orchestration.plan_store import InMemoryPlanStore

        store = InMemoryPlanStore()
        mock_llm = AsyncMock()
        mock_llm.generate.side_effect = [
            _plan_json(),
            json.dumps({"step_id": "s1", "result": "done-1"}),
            json.dumps({"step_id": "s2", "result": "done-2"}),
        ]

        planner = DeepAgentsPlannerMode(llm=mock_llm, plan_store=store)
        plan = await planner.generate_plan("g", "c")
        plan = await planner.approve(plan, by="system")

        results = []
        async for step in planner.execute_all(plan):
            results.append(step)

        loaded = await store.load(plan.id)
        assert len(results) == 2
        assert loaded is not None
        assert loaded.status == "completed"

    async def test_replan(self) -> None:
        from cognitia.orchestration.deepagents_planner import DeepAgentsPlannerMode
        from cognitia.orchestration.plan_store import InMemoryPlanStore

        store = InMemoryPlanStore()
        mock_llm = AsyncMock()
        mock_llm.generate.side_effect = [_plan_json("v1"), _plan_json("v2")]

        planner = DeepAgentsPlannerMode(llm=mock_llm, plan_store=store)
        plan = await planner.generate_plan("v1", "c")
        new_plan = await planner.replan(plan, "feedback")

        assert new_plan.id != plan.id
        assert new_plan.status == "draft"

    def test_has_all_protocol_methods(self) -> None:
        """DeepAgentsPlannerMode imeet vse metody PlannerMode."""
        from cognitia.orchestration.deepagents_planner import DeepAgentsPlannerMode

        assert hasattr(DeepAgentsPlannerMode, "generate_plan")
        assert hasattr(DeepAgentsPlannerMode, "approve")
        assert hasattr(DeepAgentsPlannerMode, "execute_step")
        assert hasattr(DeepAgentsPlannerMode, "execute_all")
        assert hasattr(DeepAgentsPlannerMode, "replan")
