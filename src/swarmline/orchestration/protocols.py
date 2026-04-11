"""Protocols for orchestration: PlanStore, PlannerMode.

ISP-joint interfaces for persistence and planoin and managed mode.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from swarmline.orchestration.types import ApprovalSource, Plan, PlanStep


@runtime_checkable
class PlanStore(Protocol):
    """Store planoin - ISP: <=4 methods.

  Multi-tenant: user_id + topic_id in each other.
  """

    async def save(self, plan: Plan) -> None:
        """Save or update plan."""
        ...

    async def load(self, plan_id: str) -> Plan | None:
        """Load."""
        ...

    async def list_plans(self, user_id: str, topic_id: str) -> list[Plan]:
        """List plans."""
        ...

    async def update_step(self, plan_id: str, step: PlanStep) -> None:
        """Update step."""
        ...


class PlannerMode(Protocol):
    """Planner Mode protocol."""

    async def generate_plan(self, goal: str, context: str) -> Plan:
        """Generate plan via LLM."""
        ...

    async def approve(self, plan: Plan, by: ApprovalSource) -> Plan:
        """Approve plan (programmatically or via user)."""
        ...

    async def execute_step(self, plan: Plan, step_id: str) -> PlanStep:
        """Execute step."""
        ...

    def execute_all(self, plan: Plan) -> AsyncIterator[PlanStep]:
        """Execute everything step and by, therefore, the results."""
        ...

    async def replan(self, plan: Plan, feedback: str) -> Plan:
        """Regenerate plan taking into account feedback."""
        ...
