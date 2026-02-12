"""DeepAgentsTeamOrchestrator — team mode с MessageBus для коммуникации.

Lead + workers через SubagentOrchestrator.
Сообщения доставляются через MessageBus (inbox/outbox).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from cognitia.orchestration.message_bus import MessageBus
from cognitia.orchestration.subagent_protocol import SubagentOrchestrator
from cognitia.orchestration.subagent_types import SubagentStatus
from cognitia.orchestration.team_types import TeamConfig, TeamMessage, TeamState, TeamStatus


class DeepAgentsTeamOrchestrator:
    """TeamOrchestrator для DeepAgents — supervisor pattern + MessageBus."""

    def __init__(self, subagent_orchestrator: SubagentOrchestrator) -> None:
        self._sub_orch = subagent_orchestrator
        self._teams: dict[str, _TeamState] = {}

    async def start(self, config: TeamConfig, task: str) -> str:
        """Запустить команду: spawn workers + создать MessageBus."""
        team_id = str(uuid.uuid4())
        worker_ids: dict[str, str] = {}
        bus = MessageBus()

        for spec in config.worker_specs[: config.max_workers]:
            agent_id = await self._sub_orch.spawn(spec, task)
            worker_ids[spec.name] = agent_id

        self._teams[team_id] = _TeamState(
            config=config, worker_ids=worker_ids,
            started_at=datetime.now(tz=timezone.utc), bus=bus, task=task,
        )
        return team_id

    async def stop(self, team_id: str) -> None:
        """Остановить всех workers."""
        state = self._teams.get(team_id)
        if not state:
            return
        for agent_id in state.worker_ids.values():
            await self._sub_orch.cancel(agent_id)

    async def get_team_status(self, team_id: str) -> TeamStatus:
        """Получить статус команды."""
        state = self._teams.get(team_id)
        if not state:
            return TeamStatus(team_id=team_id)

        workers: dict[str, SubagentStatus] = {}
        for name, agent_id in state.worker_ids.items():
            workers[name] = await self._sub_orch.get_status(agent_id)

        all_done = all(w.state in ("completed", "failed", "cancelled") for w in workers.values())
        team_state: TeamState = "completed" if all_done and workers else "running"
        history = await state.bus.get_history()

        return TeamStatus(
            team_id=team_id, state=team_state,
            workers=workers, messages_exchanged=len(history),
        )

    async def send_message(self, team_id: str, message: TeamMessage) -> None:
        """Отправить сообщение через MessageBus."""
        state = self._teams.get(team_id)
        if state:
            await state.bus.send(message)

    async def pause_agent(self, team_id: str, agent_id: str) -> None:
        """Приостановить worker'а."""
        state = self._teams.get(team_id)
        if not state:
            return
        worker_name = next((name for name, cur_id in state.worker_ids.items() if cur_id == agent_id), None)
        if worker_name is None:
            return
        await self._sub_orch.cancel(agent_id)
        state.paused_workers.add(worker_name)

    async def resume_agent(self, team_id: str, agent_id: str) -> None:
        """Возобновить worker'а после pause (через повторный spawn)."""
        state = self._teams.get(team_id)
        if not state:
            return

        worker_name = next((name for name, cur_id in state.worker_ids.items() if cur_id == agent_id), None)
        if worker_name is None or worker_name not in state.paused_workers:
            return

        spec = next((s for s in state.config.worker_specs if s.name == worker_name), None)
        if spec is None:
            return

        new_agent_id = await self._sub_orch.spawn(spec, state.task)
        state.worker_ids[worker_name] = new_agent_id
        state.paused_workers.discard(worker_name)

    def get_message_bus(self, team_id: str) -> MessageBus | None:
        """Получить MessageBus команды (для чтения inbox/outbox)."""
        state = self._teams.get(team_id)
        return state.bus if state else None


class _TeamState:
    """Внутреннее состояние команды."""

    def __init__(
        self, config: TeamConfig, worker_ids: dict[str, str],
        started_at: datetime, bus: MessageBus, task: str,
    ) -> None:
        self.config = config
        self.worker_ids = worker_ids
        self.started_at = started_at
        self.bus = bus
        self.task = task
        self.paused_workers: set[str] = set()
