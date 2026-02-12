"""Типы для team orchestration — multi-agent команды.

TeamConfig, TeamStatus, TeamMessage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from cognitia.orchestration.subagent_types import SubagentSpec, SubagentStatus

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
