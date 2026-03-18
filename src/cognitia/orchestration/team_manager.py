"""Team Manager module."""

from __future__ import annotations

from cognitia.orchestration.team_protocol import ResumableTeamOrchestrator, TeamOrchestrator
from cognitia.orchestration.team_types import TeamConfig, TeamMessage, TeamStatus


class TeamManager:
    """Managing a team of agents - the single point of entry for orders."""

    def __init__(self, orchestrator: TeamOrchestrator) -> None:
        self._orch = orchestrator
        self._resumable_orch: ResumableTeamOrchestrator | None = None
        if isinstance(orchestrator, ResumableTeamOrchestrator):
            self._resumable_orch = orchestrator
        self._teams: dict[str, TeamConfig] = {}
        self._paused: set[tuple[str, str]] = set()  # (team_id, agent_id)

    async def start_team(self, config: TeamConfig, task: str) -> str:
        """Run tomandu."""
        team_id = await self._orch.start(config, task)
        self._teams[team_id] = config
        return team_id

    async def stop_team(self, team_id: str) -> None:
        """Stop toomand."""
        await self._orch.stop(team_id)
        self._teams.pop(team_id, None)

    async def get_status(self, team_id: str) -> TeamStatus:
        """Get status teams."""
        return await self._orch.get_team_status(team_id)

    async def list_teams(self) -> list[str]:
        """List teams."""
        return list(self._teams.keys())

    async def send_to_agent(self, team_id: str, message: TeamMessage) -> None:
        """Send to agent."""
        await self._orch.send_message(team_id, message)

    async def pause_agent(self, team_id: str, agent_id: str) -> None:
        """Prandstop worker."""
        await self._orch.pause_agent(team_id, agent_id)
        self._paused.add((team_id, agent_id))

    async def resume_agent(self, team_id: str, agent_id: str) -> None:
        """Resume the suspended worker via typesafe contract."""
        if self._resumable_orch is None:
            return
        await self._resumable_orch.resume_agent(team_id, agent_id)
        self._paused.discard((team_id, agent_id))
