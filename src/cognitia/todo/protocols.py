"""Протокол TodoProvider — ISP-совместимый интерфейс (2 метода).

Bulk write API совместим с Claude Code TodoRead/TodoWrite.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cognitia.todo.types import TodoItem


@runtime_checkable
class TodoProvider(Protocol):
    """Провайдер хранения todo-списка.

    ISP: 2 метода — read_todos и write_todos (bulk replace).
    Multi-tenant: изоляция по user_id + topic_id.
    """

    async def read_todos(self) -> list[TodoItem]:
        """Прочитать все todos.

        Returns:
            Список TodoItem, отсортированный по created_at.
        """
        ...

    async def write_todos(self, todos: list[TodoItem]) -> None:
        """Записать todos (bulk replace — полная замена списка).

        Args:
            todos: Новый список todos.

        Raises:
            ValueError: Превышен лимит max_todos.
        """
        ...
