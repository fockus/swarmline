"""BaseTeamOrchestrator — общая логика stop/status/send/pause/resume.

Все team orchestrator'ы наследуют этот класс, переопределяя start().
"""

from __future__ import annotations

import abc

from cognitia.orchestration.message_bus import MessageBus
from cognitia.orchestration.subagent_protocol import SubagentOrchestrator
from cognitia.orchestration.subagent_types import SubagentStatus
from cognitia.orchestration.team_types import (
    InternalTeamState,
    TeamConfig,
    TeamMessage,
    TeamState,
    TeamStatus,
    compose_worker_task,
)


class BaseTeamOrchestrator(abc.ABC):
    """Базовый класс team orchestrator — общие stop/status/send/pause/resume.

    Подклассы реализуют start() с runtime-специфичной логикой spawn'а workers.
    """

    def __init__(self, sub_orch: SubagentOrchestrator) -> None:
        self._sub_orch = sub_orch
        self._teams: dict[str, InternalTeamState] = {}

    @abc.abstractmethod
    async def start(self, config: TeamConfig, task: str) -> str:
        """Запустить команду. Возвращает team_id."""

    async def stop(self, team_id: str) -> None:
        """Остановить всех workers."""
        state = self._teams.get(team_id)
        if not state:
            return
        for agent_id in state.worker_ids.values():
            await self._sub_orch.cancel(agent_id)

    async def get_team_status(self, team_id: str) -> TeamStatus:
        """Агрегированный статус команды."""
        state = self._teams.get(team_id)
        if not state:
            return TeamStatus(team_id=team_id)

        workers: dict[str, SubagentStatus] = {}
        for name, agent_id in state.worker_ids.items():
            workers[name] = await self._sub_orch.get_status(agent_id)

        all_done = all(
            w.state in ("completed", "failed", "cancelled") for w in workers.values()
        )
        team_state: TeamState = "completed" if all_done and workers else "running"
        history = await state.bus.get_history()
        return TeamStatus(
            team_id=team_id,
            state=team_state,
            workers=workers,
            messages_exchanged=len(history),
        )

    async def send_message(self, team_id: str, message: TeamMessage) -> None:
        """Отправить сообщение в MessageBus команды."""
        state = self._teams.get(team_id)
        if state:
            await state.bus.send(message)

    async def pause_agent(self, team_id: str, agent_id: str) -> None:
        """Приостановить worker'а (cancel + mark paused)."""
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
        """Возобновить worker'а после pause (через повторный spawn)."""
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
        """Построить task для respawn'а worker'а. Подклассы могут переопределить."""
        return compose_worker_task(
            config=state.config, worker_name=worker_name, task=state.task
        )

    def get_message_bus(self, team_id: str) -> MessageBus | None:
        """Получить MessageBus команды."""
        state = self._teams.get(team_id)
        return state.bus if state else None
