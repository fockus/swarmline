"""Domain types for coding task runtime — status enum and snapshot dataclass.

All types are frozen dataclasses or str enums.
Zero external dependencies — stdlib only.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any


class CodingTaskStatus(str, Enum):
    """Status of a coding task in the runtime.

    Maps to TaskStatus via a status mapping layer:
        PENDING   -> TODO
        ACTIVE    -> IN_PROGRESS
        COMPLETED -> DONE
        BLOCKED   -> BLOCKED
        CANCELLED -> CANCELLED
    """

    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


# Status mapping: CodingTaskStatus <-> TaskStatus (string values).
# Kept as module-level dicts so both ports and implementations can reference them.
_CODING_TO_TASK: dict[str, str] = {
    CodingTaskStatus.PENDING.value: "todo",
    CodingTaskStatus.ACTIVE.value: "in_progress",
    CodingTaskStatus.COMPLETED.value: "done",
    CodingTaskStatus.BLOCKED.value: "blocked",
    CodingTaskStatus.CANCELLED.value: "cancelled",
}

_TASK_TO_CODING: dict[str, str] = {v: k for k, v in _CODING_TO_TASK.items()}


@dataclass(frozen=True)
class CodingTaskSnapshot:
    """Typed snapshot capturing everything needed to resume a coding task.

    Persisted to TaskSessionStore on every status transition.
    Roundtrips cleanly via to_dict / from_dict.
    """

    task_id: str
    status: CodingTaskStatus
    session_id: str
    title: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for TaskSessionStore persistence."""
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "session_id": self.session_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CodingTaskSnapshot:
        """Reconstruct from a dict loaded from TaskSessionStore."""
        return cls(
            task_id=data["task_id"],
            status=CodingTaskStatus(data["status"]),
            session_id=data["session_id"],
            title=data["title"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            metadata=MappingProxyType(data.get("metadata", {})),
        )
