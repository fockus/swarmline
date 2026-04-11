"""ThinPlannerMode - PlannerMode implementation for ThinRuntime.

Plan generation -> persistence -> step-by-step execution through the LLM.
Each step is a separate LLM call. The plan persists between calls.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Protocol

from cognitia.orchestration.protocols import PlanStore
from cognitia.orchestration.types import ApprovalSource, Plan, PlanStep


class LLMCallable(Protocol):
    """Minimal LLM interface for the planner."""

    async def generate(self, prompt: str) -> str: ...


class ThinPlannerMode:
    """PlannerMode for ThinRuntime - lightweight multi-turn planner.

  SRP: delegates LLM calls to the LLM and persistence to `plan_store`.
  Bounded: max_steps=10.
  """

    def __init__(
        self,
        llm: LLMCallable,
        plan_store: PlanStore,
        max_steps: int = 10,
        max_retries_per_step: int = 2,
    ) -> None:
        self._llm = llm
        self._store = plan_store
        self._max_steps = max_steps
        self._max_retries = max_retries_per_step

    async def generate_plan(self, goal: str, context: str) -> Plan:
        """Generate a plan through the LLM."""
        prompt = (
            f"Создай пошаговый план для цели: {goal}\n"
            f"Контекст: {context}\n"
            f'Верни JSON: {{"goal": "...", "steps": [{{"id": "s1", "description": "..."}}]}}\n'
            f"Максимум {self._max_steps} шагов."
        )
        raw = await self._llm.generate(prompt)
        data = json.loads(raw)

        steps = [
            PlanStep(id=s["id"], description=s["description"])
            for s in data.get("steps", [])[: self._max_steps]
        ]

        plan = Plan(
            id=str(uuid.uuid4()),
            goal=goal,
            steps=steps,
            created_at=datetime.now(tz=UTC),
        )
        await self._store.save(plan)
        return plan

    async def approve(self, plan: Plan, by: ApprovalSource) -> Plan:
        """Approve plan."""
        approved = plan.approve(by=by)
        await self._store.save(approved)
        return approved

    async def execute_step(self, plan: Plan, step_id: str) -> PlanStep:
        """Execute a single plan step through the LLM."""
        step = next((s for s in plan.steps if s.id == step_id), None)
        if step is None:
            msg = f"Шаг '{step_id}' не найден"
            raise ValueError(msg)

        # Collect context from previous steps.
        prev_results = [
            f"[{s.id}] {s.description}: {s.result}"
            for s in plan.steps
            if s.status == "completed" and s.result
        ]
        context = "\n".join(prev_results) if prev_results else "Нет предыдущих результатов"

        prompt = (
            f"План: {plan.goal}\n"
            f"Предыдущие результаты:\n{context}\n"
            f"Выполни шаг: {step.description}\n"
            f'Верни JSON: {{"step_id": "{step_id}", "result": "..."}}'
        )

        try:
            raw = await self._llm.generate(prompt)
            data = json.loads(raw)
            result = data.get("result", raw)
            updated = step.complete(result)
        except Exception as e:
            updated = step.fail(str(e))

        await self._store.update_step(plan.id, updated)
        return updated

    async def execute_all(self, plan: Plan) -> AsyncIterator[PlanStep]:
        """Execute all steps sequentially and stop on failure."""
        if plan.status != "approved":
            msg = "Plan must be approved before execution"
            raise ValueError(msg)

        plan = plan.start_execution()
        await self._store.save(plan)
        execution_failed = False

        for step in plan.steps:
            if step.status != "pending":
                continue
            result = await self.execute_step(plan, step.id)
            yield result
            # Update the local plan copy.
            plan = plan.update_step(result)
            if result.status == "failed":
                execution_failed = True
                break

        if not execution_failed and all(step.status == "completed" for step in plan.steps):
            plan = plan.mark_completed()
            await self._store.save(plan)

    async def replan(self, plan: Plan, feedback: str) -> Plan:
        """Regenerate the plan with feedback."""
        context = (
            f"Предыдущий план: {plan.goal}\n"
            f"Шаги: {json.dumps([{'id': s.id, 'desc': s.description, 'status': s.status} for s in plan.steps])}\n"
            f"Обратная связь: {feedback}"
        )
        return await self.generate_plan(plan.goal, context)
