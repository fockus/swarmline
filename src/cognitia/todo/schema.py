"""DDL export для Todos — app-level миграции."""

from __future__ import annotations


def get_todo_ddl() -> list[str]:
    """Dialect-agnostic DDL для таблицы todos."""
    return [
        """
        CREATE TABLE IF NOT EXISTS todos (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            topic_id TEXT NOT NULL,
            content TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_todos_user_topic ON todos(user_id, topic_id)",
    ]
