"""Types for the Todo capability.

TodoItem - checklist item (id, content, status).
TodoConfig - todo configuration (enabled, backend, limits).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True)
class TodoItem:
    """Checklist item.

    Statuses: pending, in_progress, completed, cancelled.
    """

    id: str
    content: str
    status: Literal["pending", "in_progress", "completed", "cancelled"]
    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict."""
        return {
            "id": self.id,
            "content": self.content,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True)
class TodoConfig:
    """Todo capability configuration.

    Can be enabled or disabled independently of sandbox and memory bank.
    """

    enabled: bool = False
    backend: Literal["memory", "filesystem", "database"] = "memory"
    root_path: Path | None = None
    max_todos: int = 100
    auto_cleanup_completed: bool = False
