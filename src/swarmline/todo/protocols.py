"""TodoProvider protocol - ISP-compliant interface (2 methods).

Bulk write API is compatible with Claude Code TodoRead/TodoWrite.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from swarmline.todo.types import TodoItem


@runtime_checkable
class TodoProvider(Protocol):
    """Todo list storage provider.

    ISP: 2 methods - read_todos and write_todos (bulk replace).
    Multi-tenant: isolation by user_id + topic_id.
    """

    async def read_todos(self) -> list[TodoItem]:
        """Read all todos.

        Returns:
            A list of TodoItem objects sorted by created_at.
        """
        ...

    async def write_todos(self, todos: list[TodoItem]) -> None:
        """Write todos (bulk replace - full list replacement).

        Args:
            todos: New list of todos.

        Raises:
            ValueError: max_todos limit exceeded.
        """
        ...
