"""Todo tools - todo_read and todo_write for agents.

Compatible with Claude Code TodoRead/TodoWrite.
Standalone: works without sandbox and memory bank.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from cognitia.runtime.types import ToolSpec
from cognitia.todo.protocols import TodoProvider
from cognitia.todo.types import TodoItem

_TODO_READ_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status_filter": {
            "type": "string",
            "enum": ["pending", "in_progress", "completed", "cancelled"],
            "description": "Фильтр по статусу (опционально)",
        },
    },
}

_TODO_WRITE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "todos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "content": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed", "cancelled"],
                    },
                },
                "required": ["id", "content", "status"],
            },
            "description": "Массив задач (bulk replace)",
        },
    },
    "required": ["todos"],
}


def create_todo_tools(
    provider: TodoProvider,
) -> tuple[dict[str, ToolSpec], dict[str, Callable]]:
    """Create todo_read and todo_write tools.

    Args:
        provider: TodoProvider (InMemory, FS, DB).

    Returns:
        Tuple: (specs dict, executors dict).
    """

    async def todo_read_executor(args: dict) -> str:
        """Read todos with an optional status filter."""
        try:
            todos = await provider.read_todos()
            status_filter = args.get("status_filter")
            if status_filter:
                todos = [t for t in todos if t.status == status_filter]
            return json.dumps(
                {
                    "todos": [t.to_dict() for t in todos],
                }
            )
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    async def todo_write_executor(args: dict) -> str:
        """Write todos (bulk replace)."""
        raw_todos = args.get("todos", [])
        if not isinstance(raw_todos, list):
            return json.dumps({"status": "error", "message": "todos должен быть массивом"})
        try:
            now = datetime.now(tz=UTC)
            items = [
                TodoItem(
                    id=t.get("id", ""),
                    content=t.get("content", ""),
                    status=t.get("status", "pending"),
                    created_at=now,
                    updated_at=now,
                )
                for t in raw_todos
            ]
            await provider.write_todos(items)
            return json.dumps({"status": "ok", "count": len(items)})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    specs = {
        "todo_read": ToolSpec(
            name="todo_read",
            description="Прочитать список задач/чеклист с фильтром по статусу",
            parameters=_TODO_READ_SCHEMA,
        ),
        "todo_write": ToolSpec(
            name="todo_write",
            description="Записать/обновить список задач (bulk replace)",
            parameters=_TODO_WRITE_SCHEMA,
        ),
    }

    executors: dict[str, Callable] = {
        "todo_read": todo_read_executor,
        "todo_write": todo_write_executor,
    }

    return specs, executors
