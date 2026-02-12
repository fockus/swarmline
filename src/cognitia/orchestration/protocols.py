"""Протоколы для orchestration: PlanStore, PlannerMode.

ISP-совместимые интерфейсы для персистентности планов и управления режимом.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from cognitia.orchestration.types import ApprovalSource, Plan, PlanStep


@runtime_checkable
class PlanStore(Protocol):
    """Хранилище планов — ISP: ≤4 метода.

    Multi-tenant: user_id + topic_id в каждом вызове.
    """

    async def save(self, plan: Plan) -> None:
        """Сохранить или обновить план."""
        ...

    async def load(self, plan_id: str) -> Plan | None:
        """Загрузить план по id. None если не найден."""
        ...

    async def list_plans(self, user_id: str, topic_id: str) -> list[Plan]:
        """Список планов пользователя/топика."""
        ...

    async def update_step(self, plan_id: str, step: PlanStep) -> None:
        """Обновить статус шага в плане."""
        ...


class PlannerMode(Protocol):
    """Режим планирования — ISP: ≤5 методов.

    Реализации: ThinPlannerMode, DeepAgentsPlannerMode.
    """

    async def generate_plan(self, goal: str, context: str) -> Plan:
        """Сгенерировать план через LLM."""
        ...

    async def approve(self, plan: Plan, by: ApprovalSource) -> Plan:
        """Одобрить план (программно или через пользователя)."""
        ...

    async def execute_step(self, plan: Plan, step_id: str) -> PlanStep:
        """Выполнить один шаг плана."""
        ...

    def execute_all(self, plan: Plan) -> AsyncIterator[PlanStep]:
        """Выполнить все шаги последовательно, стримить результаты."""
        ...

    async def replan(self, plan: Plan, feedback: str) -> Plan:
        """Перегенерировать план с учётом feedback."""
        ...
