"""Deepagents Team module."""

from __future__ import annotations

import inspect
import uuid
from dataclasses import replace
from datetime import UTC, datetime

from cognitia.orchestration.base_team import BaseTeamOrchestrator
from cognitia.orchestration.message_bus import MessageBus
from cognitia.orchestration.message_tools import (
    SEND_MESSAGE_TOOL_SPEC,
    create_send_message_tool,
)
from cognitia.orchestration.subagent_protocol import SubagentOrchestrator
from cognitia.orchestration.team_types import (
    InternalTeamState,
    TeamConfig,
    compose_worker_task,
)


class DeepAgentsTeamOrchestrator(BaseTeamOrchestrator):
    """TeamOrchestrator for DeepAgents - supervisor pattern + MessageBus."""

    def __init__(self, subagent_orchestrator: SubagentOrchestrator) -> None:
        super().__init__(subagent_orchestrator)

    async def start(self, config: TeamConfig, task: str) -> str:
        """Start."""
        team_id = str(uuid.uuid4())
        worker_ids: dict[str, str] = {}
        bus = MessageBus()
        send_message_name = SEND_MESSAGE_TOOL_SPEC.name
        worker_specs = [
            replace(
                spec,
                tools=(
                    spec.tools
                    if any(tool.name == send_message_name for tool in spec.tools)
                    else [*spec.tools, SEND_MESSAGE_TOOL_SPEC]
                ),
            )
            for spec in config.worker_specs[: config.max_workers]
        ]
        worker_names = [spec.name for spec in worker_specs]

        register_tool = getattr(self._sub_orch, "register_tool", None)
        if callable(register_tool) and not inspect.iscoroutinefunction(register_tool):
            register_tool(
                "send_message",
                create_send_message_tool(
                    bus,
                    sender_agent_id="team",
                    team_members=worker_names,
                ),
            )

        for spec in worker_specs:
            worker_task = compose_worker_task(
                config=config,
                worker_name=spec.name,
                task=task,
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

    def _build_resume_task(self, state: InternalTeamState, worker_name: str) -> str:
        """Build resume task."""
        return compose_worker_task(
            config=state.config,
            worker_name=worker_name,
            task=state.task,
        )
