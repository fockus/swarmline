"""ActivityLog domain types — structured audit trail entries and filters."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActorType(str, Enum):
    """Type of actor that performed an action."""

    AGENT = "agent"
    USER = "user"
    SYSTEM = "system"


@dataclass(frozen=True)
class ActivityEntry:
    """Single audit trail entry — who did what to which entity."""

    id: str
    actor_type: ActorType
    actor_id: str
    action: str
    entity_type: str
    entity_id: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ActivityFilter:
    """Query filter for activity log entries. None fields are ignored."""

    actor_type: ActorType | None = None
    actor_id: str | None = None
    action: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    since: float | None = None
    until: float | None = None
