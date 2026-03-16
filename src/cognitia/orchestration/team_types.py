"""Типы для team orchestration — multi-agent команды.

TeamConfig, TeamStatus, TeamMessage, InternalTeamState, compose_worker_task.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from cognitia.orchestration.subagent_types import SubagentSpec, SubagentStatus

if TYPE_CHECKING:
    from cognitia.orchestration.message_bus import MessageBus

TeamState = Literal["idle", "running", "completed", "failed"]


@dataclass(frozen=True)
class TeamConfig:
    """Конфигурация команды агентов."""

    lead_prompt: str
    worker_specs: list[SubagentSpec]
    max_workers: int = 4
    communication: Literal["message_passing", "shared_state"] = "message_passing"


@dataclass(frozen=True)
class TeamMessage:
    """Сообщение между агентами в команде."""

    from_agent: str
    to_agent: str
    content: str
    timestamp: datetime


@dataclass(frozen=True)
class TeamStatus:
    """Текущий статус команды."""

    team_id: str
    state: TeamState = "idle"
    workers: dict[str, SubagentStatus] = field(default_factory=dict)
    messages_exchanged: int = 0


class InternalTeamState:
    """Внутреннее состояние команды (shared across all team orchestrators)."""

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


def compose_worker_task(*, config: TeamConfig, worker_name: str, task: str) -> str:
    """Сформировать worker task из lead_prompt и общей задачи."""
    return (
        f"{config.lead_prompt}\n\n"
        f"Ты worker '{worker_name}'.\n"
        f"Выполни подзадачу в контексте общей цели:\n{task}"
    )
