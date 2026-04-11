"""DatabaseTodoProvider - persistent todos via SQLAlchemy (Postgres + SQLite).

Dialect-agnostic SQL. Multi-tenant: user_id + topic_id.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from swarmline.todo.types import TodoItem


class DatabaseTodoProvider:
    """TodoProvider via SQLAlchemy async (Postgres/SQLite).

    SQL is isolated within the class. LSP: replaces InMemory and FS.
    """

    def __init__(
        self, session_factory: Any, user_id: str, topic_id: str, max_todos: int = 100
    ) -> None:
        self._session_factory = session_factory
        self._user_id = user_id
        self._topic_id = topic_id
        self._max_todos = max_todos

    async def _get_session(self) -> AsyncSession:
        session: AsyncSession = self._session_factory()
        return session

    async def read_todos(self) -> list[TodoItem]:
        """Read all todos for the user/topic."""
        async with await self._get_session() as session:
            result = await session.execute(
                text(
                    "SELECT id, content, status, created_at, updated_at FROM todos WHERE user_id = :u AND topic_id = :t ORDER BY created_at"
                ),
                {"u": self._user_id, "t": self._topic_id},
            )
            rows = result.fetchall()
            return [
                TodoItem(
                    id=row[0],
                    content=row[1],
                    status=row[2],
                    created_at=row[3] if isinstance(row[3], datetime) else datetime.now(tz=UTC),
                    updated_at=row[4] if isinstance(row[4], datetime) else datetime.now(tz=UTC),
                )
                for row in rows
            ]

    async def write_todos(self, todos: list[TodoItem]) -> None:
        """Write todos (bulk replace): deletes all and inserts new ones."""
        if len(todos) > self._max_todos:
            msg = f"Превышен лимит max_todos ({self._max_todos})"
            raise ValueError(msg)

        async with await self._get_session() as session:
            # Delete all current todos
            await session.execute(
                text("DELETE FROM todos WHERE user_id = :u AND topic_id = :t"),
                {"u": self._user_id, "t": self._topic_id},
            )
            # Insert new ones
            for item in todos:
                await session.execute(
                    text(
                        """
                        INSERT INTO todos (id, user_id, topic_id, content, status, created_at, updated_at)
                        VALUES (:id, :u, :t, :content, :status, :created, :updated)
                    """
                    ),
                    {
                        "id": item.id,
                        "u": self._user_id,
                        "t": self._topic_id,
                        "content": item.content,
                        "status": item.status,
                        "created": (
                            item.created_at.isoformat()
                            if isinstance(item.created_at, datetime)
                            else str(item.created_at)
                        ),
                        "updated": (
                            item.updated_at.isoformat()
                            if isinstance(item.updated_at, datetime)
                            else str(item.updated_at)
                        ),
                    },
                )
            await session.commit()
