"""InMemoryTodoProvider - session-scoped todo storage.

Data lives in process memory. Multi-tenant: each instance
is created for a specific user_id + topic_id.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from swarmline.todo.ops import TodoEditResult, apply_todo_ops
from swarmline.todo.types import TodoItem


def new_todo_id() -> str:
    """A short item id the model can quote back (collisions are retried by the caller)."""
    return uuid4().hex[:8]


class InMemoryTodoProvider:
    """In-memory todo storage (session-scoped).

    Each instance is a separate namespace (user_id + topic_id). Implements both
    ``TodoProvider`` and ``TodoEditProvider``.
    """

    def __init__(
        self,
        user_id: str,
        topic_id: str,
        max_todos: int = 100,
    ) -> None:
        self._user_id = user_id
        self._topic_id = topic_id
        self._max_todos = max_todos
        self._todos: list[TodoItem] = []

    async def read_todos(self) -> list[TodoItem]:
        """Read all todos."""
        return list(self._todos)

    async def write_todos(self, todos: list[TodoItem]) -> None:
        """Write todos (bulk replace)."""
        if len(todos) > self._max_todos:
            msg = f"max_todos limit ({self._max_todos}) exceeded: got {len(todos)}"
            raise ValueError(msg)
        self._todos = list(todos)

    async def apply_edit(self, ops: list[dict[str, Any]]) -> TodoEditResult:
        """Apply an atomic batch of point edits (``apply_todo_ops``)."""
        result = apply_todo_ops(
            self._todos,
            ops,
            now=datetime.now(tz=UTC),
            new_id=new_todo_id,
            max_todos=self._max_todos,
        )
        self._todos = list(result.items)
        return result
