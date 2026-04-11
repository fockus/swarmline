"""PlanManager - programmatic plan management from the application layer.

Orchestration: create, approve, execute, cancel, get, list.
DIP: depends on the `PlannerMode` and `PlanStore` protocols.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from swarmline.orchestration.protocols import PlannerMode, PlanStore
from swarmline.orchestration.types import ApprovalSource, Plan, PlanStep


class PlanManager:
    """Plan management - a single entry point for the application.

  SRP: orchestration only. The LLM lives in `PlannerMode`.
  Persistence lives in `PlanStore`.
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
        """Create a plan and auto-approve it when requested."""
        plan = await self._planner.generate_plan(goal, context=f"user={user_id}, topic={topic_id}")
        # Set the namespace for multi-tenant isolation when the store supports it.
        if hasattr(self._store, "set_namespace"):
            self._store.set_namespace(user_id, topic_id)
        await self._store.save(plan)

        if auto_approve:
            plan = await self._planner.approve(plan, by="system")
            await self._store.save(plan)

        return plan

    async def approve_plan(self, plan_id: str, by: ApprovalSource = "system") -> Plan:
        """Approve a plan programmatically."""
        plan = await self._store.load(plan_id)
        if plan is None:
            msg = f"План '{plan_id}' не найден"
            raise ValueError(msg)

        approved = await self._planner.approve(plan, by=by)
        await self._store.save(approved)
        return approved

    async def execute_plan(self, plan_id: str) -> AsyncIterator[PlanStep]:
        """Execute a plan and stream step results."""
        plan = await self._store.load(plan_id)
        if plan is None:
            msg = f"План '{plan_id}' не найден"
            raise ValueError(msg)

        async for step in self._planner.execute_all(plan):
            yield step

    async def cancel_plan(self, plan_id: str) -> Plan:
        """Cancel plan."""
        plan = await self._store.load(plan_id)
        if plan is None:
            msg = f"План '{plan_id}' не найден"
            raise ValueError(msg)

        cancelled = plan.cancel()
        await self._store.save(cancelled)
        return cancelled

    async def get_plan(self, plan_id: str) -> Plan | None:
        """Get plan by id."""
        return await self._store.load(plan_id)

    async def list_plans(self, user_id: str, topic_id: str) -> list[Plan]:
        """List plans for a user/topic pair."""
        return await self._store.list_plans(user_id, topic_id)
