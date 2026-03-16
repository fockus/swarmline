"""ThinTeamOrchestrator — team orchestration через ThinRuntime workers.

Lead delegation + workers + MessageBus координация.
Реализует TeamOrchestrator + ResumableTeamOrchestrator protocols.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from cognitia.orchestration.base_team import BaseTeamOrchestrator
from cognitia.orchestration.message_bus import MessageBus
from cognitia.orchestration.message_tools import create_send_message_tool
from cognitia.orchestration.team_types import (
    InternalTeamState,
    TeamConfig,
    compose_worker_task,
)
from cognitia.orchestration.thin_subagent import ThinSubagentOrchestrator
from cognitia.runtime.types import RuntimeConfig


async def _default_llm_call(
    messages: list[dict[str, Any]], system_prompt: str, **kwargs: Any
) -> str:
    """No-op LLM call -- возвращает минимальный final ответ с небольшой задержкой.

    Задержка нужна чтобы workers не завершались мгновенно до вызова
    pause/resume в тестах и production code.
    """
    await asyncio.sleep(0.1)
    return json.dumps({"type": "final", "final_message": "done"})


class ThinTeamOrchestrator(BaseTeamOrchestrator):
    """TeamOrchestrator для ThinRuntime workers.

    SRP: координация команды (lead delegation, worker dispatch, messaging).
    Execution делегируется ThinSubagentOrchestrator.

    Если llm_call не передан, используется no-op реализация (для тестов/протоколов).
    """

    def __init__(
        self,
        *,
        llm_call: Callable[..., Any] | None = None,
        local_tools: dict[str, Callable[..., Any]] | None = None,
        mcp_servers: dict[str, Any] | None = None,
        runtime_config: RuntimeConfig | None = None,
        max_concurrent: int = 8,
        sub_orchestrator: ThinSubagentOrchestrator | None = None,
    ) -> None:
        if sub_orchestrator is not None:
            sub_orch = sub_orchestrator
        else:
            effective_llm_call = llm_call if llm_call is not None else _default_llm_call
            sub_orch = ThinSubagentOrchestrator(
                max_concurrent=max_concurrent,
                llm_call=effective_llm_call,
                local_tools=local_tools,
                mcp_servers=mcp_servers,
                runtime_config=runtime_config,
            )
        super().__init__(sub_orch)

    async def start(self, config: TeamConfig, task: str) -> str:
        """Запустить команду — spawn workers с lead-composed tasks.

        Каждый worker автоматически получает send_message tool
        для обмена сообщениями через MessageBus.
        """
        team_id = str(uuid.uuid4())
        worker_ids: dict[str, str] = {}
        bus = MessageBus()

        worker_names = [s.name for s in config.worker_specs[: config.max_workers]]

        # Регистрируем send_message tool — один executor для всех workers
        # executor принимает args dict с from_agent (опционально, fallback на sender)
        assert isinstance(self._sub_orch, ThinSubagentOrchestrator)
        self._sub_orch.register_tool(
            "send_message",
            create_send_message_tool(bus, sender_agent_id="team", team_members=worker_names),
        )

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

    def _resolve_worker(
        self, state: InternalTeamState, agent_id: str
    ) -> tuple[str, str] | None:
        """Resolve agent_id to (worker_name, actual_agent_uuid).

        Accepts both worker name (from status.workers keys) and UUID (internal).
        Returns None if not found.
        """
        # Try as UUID first
        by_uuid = next(
            (name for name, cur_id in state.worker_ids.items() if cur_id == agent_id),
            None,
        )
        if by_uuid is not None:
            return by_uuid, agent_id

        # Try as worker name
        if agent_id in state.worker_ids:
            return agent_id, state.worker_ids[agent_id]

        return None

    async def pause_agent(self, team_id: str, agent_id: str) -> None:
        """Приостановить worker'а (cancel + mark paused).

        agent_id может быть UUID (внутренний) или worker name (из status.workers).
        """
        state = self._teams.get(team_id)
        if not state:
            return
        resolved = self._resolve_worker(state, agent_id)
        if resolved is None:
            return
        worker_name, actual_uuid = resolved
        await self._sub_orch.cancel(actual_uuid)
        state.paused_workers.add(worker_name)

    async def resume_agent(self, team_id: str, agent_id: str) -> None:
        """Возобновить paused worker'а (re-spawn).

        agent_id может быть UUID (внутренний) или worker name (из status.workers).
        """
        state = self._teams.get(team_id)
        if not state:
            return
        resolved = self._resolve_worker(state, agent_id)
        if resolved is None:
            return
        worker_name, _actual_uuid = resolved
        if worker_name not in state.paused_workers:
            return

        spec = next((s for s in state.config.worker_specs if s.name == worker_name), None)
        if spec is None:
            return

        worker_task = compose_worker_task(
            config=state.config,
            worker_name=worker_name,
            task=state.task,
        )
        new_agent_id = await self._sub_orch.spawn(spec, worker_task)
        state.worker_ids[worker_name] = new_agent_id
        state.paused_workers.discard(worker_name)
