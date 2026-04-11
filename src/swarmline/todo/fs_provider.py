"""FilesystemTodoProvider - persistent todos via the filesystem.

Stores todos in {root}/{user_id}/{topic_id}/todos.json.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from swarmline.path_safety import build_isolated_path, validate_namespace_segment
from swarmline.todo.types import TodoItem


def _parse_dt(value: str | datetime) -> datetime:
    """Parse a datetime from JSON (ISO string) or pass through."""
    if isinstance(value, datetime):
        return value
    if not value:
        return datetime.now(tz=UTC)
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return datetime.now(tz=UTC)


class FilesystemTodoProvider:
    """TodoProvider via a JSON file."""

    def __init__(self, root_path: Path, user_id: str, topic_id: str, max_todos: int = 100) -> None:
        validate_namespace_segment(user_id, "user_id")
        validate_namespace_segment(topic_id, "topic_id")
        self._max_todos = max_todos
        self._file = build_isolated_path(root_path, user_id, topic_id, "todos.json")

    async def read_todos(self) -> list[TodoItem]:
        """Read todos from the file."""
        if not self._file.exists():
            return []
        raw = json.loads(self._file.read_text(encoding="utf-8"))
        return [
            TodoItem(
                id=t["id"],
                content=t["content"],
                status=t["status"],
                created_at=_parse_dt(t.get("created_at", "")),
                updated_at=_parse_dt(t.get("updated_at", "")),
            )
            for t in raw
        ]

    async def write_todos(self, todos: list[TodoItem]) -> None:
        """Write todos to the file (bulk replace)."""
        if len(todos) > self._max_todos:
            msg = f"Превышен лимит max_todos ({self._max_todos})"
            raise ValueError(msg)
        self._file.parent.mkdir(parents=True, exist_ok=True)
        data = [t.to_dict() for t in todos]
        tmp = self._file.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(str(tmp), str(self._file))
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
