"""InMemoryTodoProvider - session-scoped todo storage.

Data lives in process memory. Multi-tenant: each instance
is created for a specific user_id + topic_id.
"""

from __future__ import annotations

from swarmline.todo.types import TodoItem


class InMemoryTodoProvider:
    """In-memory todo storage (session-scoped).

    Each instance is a separate namespace (user_id + topic_id).
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
            msg = f"Превышен лимит max_todos ({self._max_todos}), передано {len(todos)}"
            raise ValueError(msg)
        self._todos = list(todos)
