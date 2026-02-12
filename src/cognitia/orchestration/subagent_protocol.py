"""SubagentOrchestrator Protocol — ISP ≤5 методов.

Управление lifecycle subagent'ов: spawn, status, cancel, wait, list.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cognitia.orchestration.subagent_types import SubagentResult, SubagentSpec, SubagentStatus


@runtime_checkable
class SubagentOrchestrator(Protocol):
    """Оркестратор subagent'ов — ISP: ≤5 методов."""

    async def spawn(self, spec: SubagentSpec, task: str) -> str:
        """Запустить subagent. Возвращает agent_id."""
        ...

    async def get_status(self, agent_id: str) -> SubagentStatus:
        """Получить статус subagent'а."""
        ...

    async def cancel(self, agent_id: str) -> None:
        """Отменить subagent."""
        ...

    async def wait(self, agent_id: str) -> SubagentResult:
        """Дождаться завершения subagent'а."""
        ...

    async def list_active(self) -> list[str]:
        """Список активных subagent id'ов."""
        ...
