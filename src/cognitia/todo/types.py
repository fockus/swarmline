"""Типы для Todo capability.

TodoItem — элемент чеклиста (id, content, status).
TodoConfig — конфигурация todo (enabled, backend, лимиты).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True)
class TodoItem:
    """Элемент чеклиста.

    Статусы: pending, in_progress, completed, cancelled.
    """

    id: str
    content: str
    status: Literal["pending", "in_progress", "completed", "cancelled"]
    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict."""
        return {
            "id": self.id,
            "content": self.content,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True)
class TodoConfig:
    """Конфигурация todo capability.

    Включается/выключается независимо от sandbox и memory bank.
    """

    enabled: bool = False
    backend: Literal["memory", "filesystem", "database"] = "memory"
    root_path: Path | None = None
    max_todos: int = 100
    auto_cleanup_completed: bool = False
