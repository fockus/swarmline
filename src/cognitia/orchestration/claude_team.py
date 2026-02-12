"""ClaudeTeamOrchestrator — SDK-specific team orchestration с lead delegation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from cognitia.orchestration.message_bus import MessageBus
from cognitia.orchestration.subagent_protocol import SubagentOrchestrator
from cognitia.orchestration.subagent_types import SubagentStatus
from cognitia.orchestration.team_types import TeamConfig, TeamMessage, TeamState, TeamStatus


class ClaudeTeamOrchestrator:
    """TeamOrchestrator для Claude SDK.

    Отличие от DeepAgents:
    - lead_prompt реально влияет на worker task assignment;
    - worker получает персонализированный prompt для координации.
    """

    def __init__(self, subagent_orchestrator: SubagentOrchestrator) -> None:
        self._sub_orch = subagent_orchestrator
        self._teams: dict[str, _TeamState] = {}

    async def start(self, config: TeamConfig, task: str) -> str:
        """Запустить команду и назначить каждому worker его подзадачу."""
        team_id = str(uuid.uuid4())
        worker_ids: dict[str, str] = {}
        bus = MessageBus()

        for spec in config.worker_specs[: config.max_workers]:
            worker_task = self._compose_worker_task(config=config, worker_name=spec.name, task=task)
            agent_id = await self._sub_orch.spawn(spec, worker_task)
            worker_ids[spec.name] = agent_id

        self._teams[team_id] = _TeamState(
            config=config,
            worker_ids=worker_ids,
            started_at=datetime.now(tz=timezone.utc),
            bus=bus,
            task=task,
        )
        return team_id

    async def stop(self, team_id: str) -> None:
        """Остановить всех worker-ов команды."""
        state = self._teams.get(team_id)
        if not state:
            return
        for agent_id in state.worker_ids.values():
            await self._sub_orch.cancel(agent_id)

    async def get_team_status(self, team_id: str) -> TeamStatus:
        """Получить агрегированный статус команды."""
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
            team_id=team_id,
            state=team_state,
            workers=workers,
            messages_exchanged=len(history),
        )

    async def send_message(self, team_id: str, message: TeamMessage) -> None:
        """Отправить сообщение в общий MessageBus команды."""
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
        """Возобновить worker'а после pause."""
        state = self._teams.get(team_id)
        if not state:
            return
        worker_name = next((name for name, cur_id in state.worker_ids.items() if cur_id == agent_id), None)
        if worker_name is None or worker_name not in state.paused_workers:
            return

        spec = next((s for s in state.config.worker_specs if s.name == worker_name), None)
        if spec is None:
            return

        worker_task = self._compose_worker_task(
            config=state.config,
            worker_name=worker_name,
            task=state.task,
        )
        new_agent_id = await self._sub_orch.spawn(spec, worker_task)
        state.worker_ids[worker_name] = new_agent_id
        state.paused_workers.discard(worker_name)

    def get_message_bus(self, team_id: str) -> MessageBus | None:
        """Получить message bus команды."""
        state = self._teams.get(team_id)
        return state.bus if state else None

    @staticmethod
    def _compose_worker_task(*, config: TeamConfig, worker_name: str, task: str) -> str:
        """Сформировать worker task из lead_prompt и общей задачи."""
        return (
            f"{config.lead_prompt}\n\n"
            f"Ты worker '{worker_name}'.\n"
            f"Выполни подзадачу в контексте общей цели:\n{task}"
        )


class _TeamState:
    """Внутреннее состояние команды."""

    def __init__(
        self,
        *,
        config: TeamConfig,
        worker_ids: dict[str, str],
        started_at: datetime,
        bus: MessageBus,
        task: str,
    ) -> None:
        self.config = config
        self.worker_ids = worker_ids
        self.started_at = started_at
        self.bus = bus
        self.task = task
        self.paused_workers: set[str] = set()
