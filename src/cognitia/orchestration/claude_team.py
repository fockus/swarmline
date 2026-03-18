"""ClaudeTeamOrchestrator — SDK-specific team orchestration with lead delegation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from cognitia.orchestration.base_team import BaseTeamOrchestrator
from cognitia.orchestration.message_bus import MessageBus
from cognitia.orchestration.subagent_protocol import SubagentOrchestrator
from cognitia.orchestration.team_types import (
    InternalTeamState,
    TeamConfig,
    compose_worker_task,
)


class ClaudeTeamOrchestrator(BaseTeamOrchestrator):
    """TeamOrchestrator for Claude SDK.

    Difference from DeepAgents:
    - lead_prompt really affects the worker task assignment;
    - the worker receives a personalized prompt for coordination.
    """

    def __init__(self, subagent_orchestrator: SubagentOrchestrator) -> None:
        super().__init__(subagent_orchestrator)

    async def start(self, config: TeamConfig, task: str) -> str:
        """Run the command and assign each worker their subtask."""
        team_id = str(uuid.uuid4())
        worker_ids: dict[str, str] = {}
        bus = MessageBus()

        for spec in config.worker_specs[: config.max_workers]:
            worker_task = compose_worker_task(
                config=config, worker_name=spec.name, task=task
            )
            agent_id = await self._sub_orch.spawn(spec, worker_task)
            worker_ids[spec.name] = agent_id

        self._teams[team_id] = InternalTeamState(
            config=config,
            worker_ids=worker_ids,
            started_at=datetime.now(tz=UTC),
            bus=bus,
            task=task,
        )
        return team_id
