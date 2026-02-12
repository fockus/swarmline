"""TeamManager — app-level API для управления team mode.

DIP: зависит от TeamOrchestrator Protocol.
"""

from __future__ import annotations

from cognitia.orchestration.team_protocol import ResumableTeamOrchestrator, TeamOrchestrator
from cognitia.orchestration.team_types import TeamConfig, TeamMessage, TeamStatus


class TeamManager:
    """Управление командами агентов — единая точка входа для приложения."""

    def __init__(self, orchestrator: TeamOrchestrator) -> None:
        self._orch = orchestrator
        self._resumable_orch: ResumableTeamOrchestrator | None = None
        if isinstance(orchestrator, ResumableTeamOrchestrator):
            self._resumable_orch = orchestrator
        self._teams: dict[str, TeamConfig] = {}
        self._paused: set[tuple[str, str]] = set()  # (team_id, agent_id)

    async def start_team(self, config: TeamConfig, task: str) -> str:
        """Запустить команду."""
        team_id = await self._orch.start(config, task)
        self._teams[team_id] = config
        return team_id

    async def stop_team(self, team_id: str) -> None:
        """Остановить команду."""
        await self._orch.stop(team_id)
        self._teams.pop(team_id, None)

    async def get_status(self, team_id: str) -> TeamStatus:
        """Получить статус команды."""
        return await self._orch.get_team_status(team_id)

    async def list_teams(self) -> list[str]:
        """Список активных team id'ов."""
        return list(self._teams.keys())

    async def send_to_agent(self, team_id: str, message: TeamMessage) -> None:
        """Отправить сообщение агенту."""
        await self._orch.send_message(team_id, message)

    async def pause_agent(self, team_id: str, agent_id: str) -> None:
        """Приостановить worker'а."""
        await self._orch.pause_agent(team_id, agent_id)
        self._paused.add((team_id, agent_id))

    async def resume_agent(self, team_id: str, agent_id: str) -> None:
        """Возобновить приостановленного worker'а через типобезопасный контракт."""
        if self._resumable_orch is None:
            return
        await self._resumable_orch.resume_agent(team_id, agent_id)
        self._paused.discard((team_id, agent_id))
