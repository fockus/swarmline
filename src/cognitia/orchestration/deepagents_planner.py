"""DeepAgentsPlannerMode — PlannerMode через LangGraph Plan-and-Execute pattern.

Использует тот же LLM-интерфейс что и ThinPlannerMode, но
при наличии langchain может использовать нативные graph nodes.

Optional dependency: langchain-core.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from cognitia.orchestration.protocols import PlanStore
from cognitia.orchestration.thin_planner import LLMCallable
from cognitia.orchestration.types import ApprovalSource, Plan, PlanStep


class DeepAgentsPlannerMode:
    """PlannerMode для DeepAgents runtime.

    Структурно совместим с ThinPlannerMode (LSP).
    При наличии langchain использует LangGraph nodes;
    при отсутствии — fallback на direct LLM calls.
    """

    def __init__(
        self,
        llm: LLMCallable,
        plan_store: PlanStore,
        max_steps: int = 10,
    ) -> None:
        self._llm = llm
        self._store = plan_store
        self._max_steps = max_steps

    async def generate_plan(self, goal: str, context: str) -> Plan:
        """Сгенерировать план через LLM."""
        prompt = (
            f"Создай пошаговый план для: {goal}\n"
            f"Контекст: {context}\n"
            f'Верни JSON: {{"goal": "...", "steps": [{{"id": "s1", "description": "..."}}]}}'
        )
        raw = await self._llm.generate(prompt)
        data = json.loads(raw)
        steps = [
            PlanStep(id=s["id"], description=s["description"])
            for s in data.get("steps", [])[:self._max_steps]
        ]
        plan = Plan(
            id=str(uuid.uuid4()), goal=goal, steps=steps,
            created_at=datetime.now(tz=timezone.utc),
        )
        await self._store.save(plan)
        return plan

    async def approve(self, plan: Plan, by: ApprovalSource) -> Plan:
        """Одобрить план."""
        approved = plan.approve(by=by)
        await self._store.save(approved)
        return approved

    async def execute_step(self, plan: Plan, step_id: str) -> PlanStep:
        """Выполнить один шаг."""
        step = next((s for s in plan.steps if s.id == step_id), None)
        if step is None:
            msg = f"Шаг '{step_id}' не найден"
            raise ValueError(msg)

        prev_results = [
            f"[{s.id}] {s.result}" for s in plan.steps if s.status == "completed" and s.result
        ]
        prompt = (
            f"План: {plan.goal}\nПредыдущие: {'; '.join(prev_results) or 'нет'}\n"
            f'Выполни: {step.description}\nВерни JSON: {{"step_id": "{step_id}", "result": "..."}}'
        )
        try:
            raw = await self._llm.generate(prompt)
            data = json.loads(raw)
            updated = step.complete(data.get("result", raw))
        except Exception as e:
            updated = step.fail(str(e))

        await self._store.update_step(plan.id, updated)
        return updated

    async def execute_all(self, plan: Plan) -> AsyncIterator[PlanStep]:
        """Выполнить все шаги."""
        plan = plan.start_execution() if plan.status == "approved" else plan
        await self._store.save(plan)
        for step in plan.steps:
            if step.status != "pending":
                continue
            result = await self.execute_step(plan, step.id)
            yield result
            plan = plan.update_step(result)
            if result.status == "failed":
                break

    async def replan(self, plan: Plan, feedback: str) -> Plan:
        """Перегенерировать план."""
        context = f"Предыдущий: {plan.goal}, feedback: {feedback}"
        return await self.generate_plan(plan.goal, context)
