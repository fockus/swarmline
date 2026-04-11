"""BaseTeamOrchestrator — General logic stop/status/send/pause/resume.

All team orchestrators inherit this class by redefining start().
"""

from __future__ import annotations

import abc

from swarmline.orchestration.message_bus import MessageBus
from swarmline.orchestration.subagent_protocol import SubagentOrchestrator
from swarmline.orchestration.subagent_types import SubagentStatus
from swarmline.orchestration.team_types import (
    InternalTeamState,
    TeamConfig,
    TeamMessage,
    TeamState,
    TeamStatus,
    compose_worker_task,
)


class BaseTeamOrchestrator(abc.ABC):
    """The base class of the team orchestrator is general stop/status/send/pause/resume.

    Subclasses implement start() with runtime-specific spawn workers logic.
    """

    def __init__(self, sub_orch: SubagentOrchestrator) -> None:
        self._sub_orch = sub_orch
        self._teams: dict[str, InternalTeamState] = {}

    @abc.abstractmethod
    async def start(self, config: TeamConfig, task: str) -> str:
        """Run command. Returns team_id."""

    async def stop(self, team_id: str) -> None:
        """Stop all workers."""
        state = self._teams.get(team_id)
        if not state:
            return
        for agent_id in state.worker_ids.values():
            await self._sub_orch.cancel(agent_id)

    async def get_team_status(self, team_id: str) -> TeamStatus:
        """Aggregated status of the team."""
        state = self._teams.get(team_id)
        if not state:
            return TeamStatus(team_id=team_id)

        workers: dict[str, SubagentStatus] = {}
        for name, agent_id in state.worker_ids.items():
            workers[name] = await self._sub_orch.get_status(agent_id)

        all_terminal = all(
            w.state in ("completed", "failed", "cancelled") for w in workers.values()
        )
        all_completed = all(w.state == "completed" for w in workers.values())
        team_state: TeamState
        if workers and all_completed:
            team_state = "completed"
        elif workers and all_terminal:
            team_state = "failed"
        else:
            team_state = "running"
        history = await state.bus.get_history()
        return TeamStatus(
            team_id=team_id,
            state=team_state,
            workers=workers,
            messages_exchanged=len(history),
        )

    async def send_message(self, team_id: str, message: TeamMessage) -> None:
        """Send a message to the MessageBus command."""
        state = self._teams.get(team_id)
        if state:
            await state.bus.send(message)

    async def pause_agent(self, team_id: str, agent_id: str) -> None:
        """Pause the worker (cancel + mark paused)."""
        state = self._teams.get(team_id)
        if not state:
            return
        worker_name = next(
            (name for name, cur_id in state.worker_ids.items() if cur_id == agent_id),
            None,
        )
        if worker_name is None:
            return
        await self._sub_orch.cancel(agent_id)
        state.paused_workers.add(worker_name)

    async def resume_agent(self, team_id: str, agent_id: str) -> None:
        """Resume worker after pause (through repeated spawn)."""
        state = self._teams.get(team_id)
        if not state:
            return
        worker_name = next(
            (name for name, cur_id in state.worker_ids.items() if cur_id == agent_id),
            None,
        )
        if worker_name is None or worker_name not in state.paused_workers:
            return

        spec = next(
            (s for s in state.config.worker_specs if s.name == worker_name), None
        )
        if spec is None:
            return

        new_task = self._build_resume_task(state, worker_name)
        new_agent_id = await self._sub_orch.spawn(spec, new_task)
        state.worker_ids[worker_name] = new_agent_id
        state.paused_workers.discard(worker_name)

    def _build_resume_task(self, state: InternalTeamState, worker_name: str) -> str:
        """Build a task for the respawn worker. Subclasses may override."""
        return compose_worker_task(
            config=state.config, worker_name=worker_name, task=state.task
        )

    def get_message_bus(self, team_id: str) -> MessageBus | None:
        """Get the MessageBus command."""
        state = self._teams.get(team_id)
        return state.bus if state else None
