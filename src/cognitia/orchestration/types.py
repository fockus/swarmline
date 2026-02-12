"""Типы для orchestration: Plan, PlanStep, PlanApproval.

State machine: draft → approved → executing → completed/cancelled.
Все dataclass frozen — immutable, методы возвращают новые экземпляры.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

PlanStepStatus = Literal["pending", "in_progress", "completed", "failed", "skipped"]
PlanStatus = Literal["draft", "approved", "executing", "completed", "cancelled"]
ApprovalSource = Literal["user", "system", "agent"]


@dataclass(frozen=True)
class PlanStep:
    """Шаг плана — immutable, методы возвращают новые экземпляры."""

    id: str
    description: str
    status: PlanStepStatus = "pending"
    result: str | None = None
    substeps: list[PlanStep] = field(default_factory=list)

    def start(self) -> PlanStep:
        """pending → in_progress."""
        return PlanStep(
            id=self.id, description=self.description,
            status="in_progress", result=self.result, substeps=self.substeps,
        )

    def complete(self, result: str) -> PlanStep:
        """* → completed с результатом."""
        return PlanStep(
            id=self.id, description=self.description,
            status="completed", result=result, substeps=self.substeps,
        )

    def fail(self, reason: str) -> PlanStep:
        """* → failed с причиной."""
        return PlanStep(
            id=self.id, description=self.description,
            status="failed", result=reason, substeps=self.substeps,
        )

    def skip(self, reason: str) -> PlanStep:
        """* → skipped с причиной."""
        return PlanStep(
            id=self.id, description=self.description,
            status="skipped", result=reason, substeps=self.substeps,
        )


@dataclass(frozen=True)
class PlanApproval:
    """Запись об одобрении плана."""

    plan_id: str
    approved_by: ApprovalSource
    approved_at: datetime
    modifications: list[str] | None = None


@dataclass(frozen=True)
class Plan:
    """План выполнения — immutable state machine.

    State machine: draft → approved → executing → completed/cancelled.
    cancel() доступен из любого состояния.
    """

    id: str
    goal: str
    steps: list[PlanStep]
    created_at: datetime
    status: PlanStatus = "draft"
    approved_by: ApprovalSource | None = None

    def approve(self, by: ApprovalSource) -> Plan:
        """draft → approved.

        Raises:
            ValueError: Если план не в статусе draft.
        """
        if self.status != "draft":
            msg = f"Одобрение возможно только из статуса 'draft', текущий: '{self.status}'"
            raise ValueError(msg)
        return Plan(
            id=self.id, goal=self.goal, steps=self.steps,
            created_at=self.created_at, status="approved", approved_by=by,
        )

    def start_execution(self) -> Plan:
        """approved → executing.

        Raises:
            ValueError: Если план не в статусе approved.
        """
        if self.status != "approved":
            msg = f"Запуск возможен только из статуса 'approved', текущий: '{self.status}'"
            raise ValueError(msg)
        return Plan(
            id=self.id, goal=self.goal, steps=self.steps,
            created_at=self.created_at, status="executing", approved_by=self.approved_by,
        )

    def mark_completed(self) -> Plan:
        """executing → completed.

        Raises:
            ValueError: Если план не в статусе executing.
        """
        if self.status != "executing":
            msg = f"Завершение возможно только из статуса 'executing', текущий: '{self.status}'"
            raise ValueError(msg)
        return Plan(
            id=self.id, goal=self.goal, steps=self.steps,
            created_at=self.created_at, status="completed", approved_by=self.approved_by,
        )

    def cancel(self) -> Plan:
        """Любой статус → cancelled."""
        return Plan(
            id=self.id, goal=self.goal, steps=self.steps,
            created_at=self.created_at, status="cancelled", approved_by=self.approved_by,
        )

    def update_step(self, updated_step: PlanStep) -> Plan:
        """Обновить шаг по id, вернуть новый Plan.

        Raises:
            ValueError: Шаг с указанным id не найден.
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
            id=self.id, goal=self.goal, steps=new_steps,
            created_at=self.created_at, status=self.status, approved_by=self.approved_by,
        )
