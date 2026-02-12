"""TeamOrchestrator Protocol — ISP ≤5 методов.

Multi-agent team orchestration: lead + workers.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cognitia.orchestration.team_types import TeamConfig, TeamMessage, TeamStatus


@runtime_checkable
class TeamOrchestrator(Protocol):
    """Оркестратор команды агентов — ISP: ≤5 методов."""

    async def start(self, config: TeamConfig, task: str) -> str:
        """Запустить команду. Возвращает team_id."""
        ...

    async def stop(self, team_id: str) -> None:
        """Остановить команду."""
        ...

    async def get_team_status(self, team_id: str) -> TeamStatus:
        """Получить статус команды."""
        ...

    async def send_message(self, team_id: str, message: TeamMessage) -> None:
        """Отправить сообщение агенту в команде."""
        ...

    async def pause_agent(self, team_id: str, agent_id: str) -> None:
        """Приостановить конкретного worker'а."""
        ...


@runtime_checkable
class ResumableTeamOrchestrator(TeamOrchestrator, Protocol):
    """Расширение TeamOrchestrator с поддержкой resume lifecycle."""

    async def resume_agent(self, team_id: str, agent_id: str) -> None:
        """Возобновить ранее приостановленного worker'а."""
        ...
