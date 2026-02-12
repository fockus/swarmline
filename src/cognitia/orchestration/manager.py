"""PlanManager — программное управление планами из app layer.

Orchestration: create, approve, execute, cancel, get, list.
DIP: зависит от PlannerMode Protocol и PlanStore Protocol.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from cognitia.orchestration.protocols import PlannerMode, PlanStore
from cognitia.orchestration.types import ApprovalSource, Plan, PlanStep


class PlanManager:
    """Управление планами — единая точка входа для приложения.

    SRP: orchestration only. LLM — в PlannerMode. Persistence — в PlanStore.
    """

    def __init__(self, planner: PlannerMode, plan_store: PlanStore) -> None:
        self._planner = planner
        self._store = plan_store

    async def create_plan(
        self,
        goal: str,
        user_id: str,
        topic_id: str,
        auto_approve: bool = False,
    ) -> Plan:
        """Создать план. Если auto_approve — сразу approve."""
        plan = await self._planner.generate_plan(goal, context=f"user={user_id}, topic={topic_id}")
        # Устанавливаем namespace для multi-tenant изоляции (если store поддерживает)
        if hasattr(self._store, "set_namespace"):
            self._store.set_namespace(user_id, topic_id)
        await self._store.save(plan)

        if auto_approve:
            plan = await self._planner.approve(plan, by="system")
            await self._store.save(plan)

        return plan

    async def approve_plan(self, plan_id: str, by: ApprovalSource = "system") -> Plan:
        """Программное одобрение плана."""
        plan = await self._store.load(plan_id)
        if plan is None:
            msg = f"План '{plan_id}' не найден"
            raise ValueError(msg)

        approved = await self._planner.approve(plan, by=by)
        await self._store.save(approved)
        return approved

    async def execute_plan(self, plan_id: str) -> AsyncIterator[PlanStep]:
        """Выполнить план: стримит результаты шагов."""
        plan = await self._store.load(plan_id)
        if plan is None:
            msg = f"План '{plan_id}' не найден"
            raise ValueError(msg)

        async for step in self._planner.execute_all(plan):
            yield step

    async def cancel_plan(self, plan_id: str) -> Plan:
        """Отменить план."""
        plan = await self._store.load(plan_id)
        if plan is None:
            msg = f"План '{plan_id}' не найден"
            raise ValueError(msg)

        cancelled = plan.cancel()
        await self._store.save(cancelled)
        return cancelled

    async def get_plan(self, plan_id: str) -> Plan | None:
        """Получить план по id."""
        return await self._store.load(plan_id)

    async def list_plans(self, user_id: str, topic_id: str) -> list[Plan]:
        """Список планов пользователя/топика."""
        return await self._store.list_plans(user_id, topic_id)
