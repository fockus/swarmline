"""Graph communication types — channels and messages."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ChannelType(str, Enum):
    """Type of communication channel."""

    DIRECT = "direct"
    BROADCAST = "broadcast"
    ESCALATION = "escalation"


@dataclass(frozen=True)
class GraphMessage:
    """A message between agents in the graph."""

    id: str
    from_agent_id: str
    to_agent_id: str | None = None  # None for broadcast
    channel: ChannelType = ChannelType.DIRECT
    content: str = ""
    task_id: str | None = None
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
