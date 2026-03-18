"""TeamOrchestrator protocol - ISP with 5 or fewer methods.

Multi-agent team orchestration: lead + workers.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cognitia.orchestration.team_types import TeamConfig, TeamMessage, TeamStatus


@runtime_checkable
class TeamOrchestrator(Protocol):
    """Team agent orchestrator - ISP with 5 or fewer methods."""

    async def start(self, config: TeamConfig, task: str) -> str:
        """Start the team and return its `team_id`."""
        ...

    async def stop(self, team_id: str) -> None:
        """Stop the team."""
        ...

    async def get_team_status(self, team_id: str) -> TeamStatus:
        """Get status teams."""
        ...

    async def send_message(self, team_id: str, message: TeamMessage) -> None:
        """Send a message to an agent inside the team."""
        ...

    async def pause_agent(self, team_id: str, agent_id: str) -> None:
        """Pause a specific worker."""
        ...


@runtime_checkable
class ResumableTeamOrchestrator(TeamOrchestrator, Protocol):
    """Extension of `TeamOrchestrator` with resume lifecycle support."""

    async def resume_agent(self, team_id: str, agent_id: str) -> None:
        """Resume a previously paused worker."""
        ...
