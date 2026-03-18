"""Plan Store module."""

from __future__ import annotations

from cognitia.orchestration.types import Plan, PlanStep


class InMemoryPlanStore:
    """In-memory is real from the PlanStore with multi-tenant from the area.

  Namespace is set oninlanded via set_namespace(user_id, topic_id).
  save() aintomatandchestoandprandinyazyinaplan to the current namespace.
  list_plans() filters by namespace.
  """

    def __init__(self) -> None:
        self._plans: dict[str, Plan] = {}
        self._ownership: dict[str, tuple[str, str]] = {}  # plan_id → (user_id, topic_id)
        self._ns_user: str = ""
        self._ns_topic: str = ""

    def set_namespace(self, user_id: str, topic_id: str) -> None:
        """Set up the namespace for save/list."""
        self._ns_user = user_id
        self._ns_topic = topic_id

    async def save(self, plan: Plan) -> None:
        """Save or update plan. Prandin speaks to the current namespace."""
        self._plans[plan.id] = plan
        if self._ns_user or self._ns_topic:
            self._ownership[plan.id] = (self._ns_user, self._ns_topic)

    async def load(self, plan_id: str) -> Plan | None:
        """Load."""
        return self._plans.get(plan_id)

    async def list_plans(self, user_id: str, topic_id: str) -> list[Plan]:
        """List plans."""
        if not user_id and not topic_id:
            return list(self._plans.values())
        result: list[Plan] = []
        for plan_id, plan in self._plans.items():
            owner = self._ownership.get(plan_id, ("", ""))
            if (not user_id or owner[0] == user_id) and (not topic_id or owner[1] == topic_id):
                result.append(plan)
        return result

    async def update_step(self, plan_id: str, step: PlanStep) -> None:
        """Update step."""
        plan = self._plans.get(plan_id)
        if plan is None:
            return
        try:
            updated = plan.update_step(step)
            self._plans[plan_id] = updated
        except ValueError:
            pass
