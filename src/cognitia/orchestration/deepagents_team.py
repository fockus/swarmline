"""DeepAgentsTeamOrchestrator — team mode с MessageBus для коммуникации.

Lead + workers через SubagentOrchestrator.
Сообщения доставляются через MessageBus (inbox/outbox).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from cognitia.orchestration.base_team import BaseTeamOrchestrator
from cognitia.orchestration.message_bus import MessageBus
from cognitia.orchestration.subagent_protocol import SubagentOrchestrator
from cognitia.orchestration.team_types import InternalTeamState, TeamConfig


class DeepAgentsTeamOrchestrator(BaseTeamOrchestrator):
    """TeamOrchestrator для DeepAgents — supervisor pattern + MessageBus."""

    def __init__(self, subagent_orchestrator: SubagentOrchestrator) -> None:
        super().__init__(subagent_orchestrator)

    async def start(self, config: TeamConfig, task: str) -> str:
        """Запустить команду: spawn workers + создать MessageBus."""
        team_id = str(uuid.uuid4())
        worker_ids: dict[str, str] = {}
        bus = MessageBus()

        for spec in config.worker_specs[: config.max_workers]:
            agent_id = await self._sub_orch.spawn(spec, task)
            worker_ids[spec.name] = agent_id

        self._teams[team_id] = InternalTeamState(
            config=config,
            worker_ids=worker_ids,
            started_at=datetime.now(tz=UTC),
            bus=bus,
            task=task,
        )
        return team_id

    def _build_resume_task(self, state: InternalTeamState, worker_name: str) -> str:
        """DeepAgents resume: spawn с голым task (без compose)."""
        return state.task
