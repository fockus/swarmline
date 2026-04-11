"""Types for orchestration: Plan, PlanStep, and PlanApproval.

State machine: draft -> approved -> executing -> completed/cancelled.
All dataclasses are frozen and return new instances from state transitions.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Literal

PlanStepStatus = Literal["pending", "in_progress", "completed", "failed", "skipped"]
PlanStatus = Literal["draft", "approved", "executing", "completed", "cancelled"]
ApprovalSource = Literal["user", "system", "agent"]


@dataclass(frozen=True)
class PlanStep:
    """Immutable plan step with state-transition helpers."""

    id: str
    description: str
    status: PlanStepStatus = "pending"
    result: str | None = None
    substeps: list[PlanStep] = field(default_factory=list)
    dod_criteria: tuple[str, ...] = ()
    dod_verified: bool = False
    verification_log: str | None = None

    def start(self) -> PlanStep:
        """pending -> in_progress."""
        return replace(self, status="in_progress")

    def complete(self, result: str) -> PlanStep:
        """* -> completed with result."""
        return replace(self, status="completed", result=result)

    def fail(self, reason: str) -> PlanStep:
        """Transition to failed with the provided reason."""
        return replace(self, status="failed", result=reason)

    def skip(self, reason: str) -> PlanStep:
        """Transition to skipped with the provided reason."""
        return replace(self, status="skipped", result=reason)


@dataclass(frozen=True)
class PlanApproval:
    """Approval record for a plan."""

    plan_id: str
    approved_by: ApprovalSource
    approved_at: datetime
    modifications: list[str] | None = None


@dataclass(frozen=True)
class Plan:
    """Plan execution - immutable state machine.

    State machine: draft -> approved -> executing -> completed/cancelled.
    `cancel()` is available from any state.
    """

    id: str
    goal: str
    steps: list[PlanStep]
    created_at: datetime
    status: PlanStatus = "draft"
    approved_by: ApprovalSource | None = None

    def approve(self, by: ApprovalSource) -> Plan:
        """draft -> approved.

        Raises:
          ValueError: if the plan is not in draft status.
        """
        if self.status != "draft":
            msg = f"Одобрение возможно только из статуса 'draft', текущий: '{self.status}'"
            raise ValueError(msg)
        return Plan(
            id=self.id,
            goal=self.goal,
            steps=self.steps,
            created_at=self.created_at,
            status="approved",
            approved_by=by,
        )

    def start_execution(self) -> Plan:
        """approved -> executing.

        Raises:
          ValueError: if the plan is not in approved status.
        """
        if self.status != "approved":
            msg = f"Запуск возможен только из статуса 'approved', текущий: '{self.status}'"
            raise ValueError(msg)
        return Plan(
            id=self.id,
            goal=self.goal,
            steps=self.steps,
            created_at=self.created_at,
            status="executing",
            approved_by=self.approved_by,
        )

    def mark_completed(self) -> Plan:
        """executing -> completed.

        Raises:
          ValueError: if the plan is not in executing status.
        """
        if self.status != "executing":
            msg = f"Завершение возможно только из статуса 'executing', текущий: '{self.status}'"
            raise ValueError(msg)
        return Plan(
            id=self.id,
            goal=self.goal,
            steps=self.steps,
            created_at=self.created_at,
            status="completed",
            approved_by=self.approved_by,
        )

    def cancel(self) -> Plan:
        """Any status -> cancelled."""
        return Plan(
            id=self.id,
            goal=self.goal,
            steps=self.steps,
            created_at=self.created_at,
            status="cancelled",
            approved_by=self.approved_by,
        )

    def update_step(self, updated_step: PlanStep) -> Plan:
        """Update a step by id and return a new plan.

        Raises:
          ValueError: if the step id is not found.
        """
        new_steps: list[PlanStep] = []
        found = False
        for step in self.steps:
            if step.id == updated_step.id:
                new_steps.append(updated_step)
                found = True
            else:
                new_steps.append(step)
        if not found:
            msg = f"Шаг '{updated_step.id}' не найден в плане '{self.id}'"
            raise ValueError(msg)
        return Plan(
            id=self.id,
            goal=self.goal,
            steps=new_steps,
            created_at=self.created_at,
            status=self.status,
            approved_by=self.approved_by,
        )
