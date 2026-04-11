"""DDL export для Memory Bank — app-level миграции.

Dialect-agnostic: работает на PostgreSQL и SQLite.
Библиотека экспортирует DDL, приложение использует в своих alembic-миграциях.
"""

from __future__ import annotations

from typing import Literal


def get_memory_bank_ddl(dialect: Literal["postgres", "sqlite"] = "sqlite") -> list[str]:
    """DDL для таблицы memory_bank.

    Args:
        dialect: Диалект БД. Postgres использует SERIAL, SQLite — INTEGER AUTOINCREMENT.

    Returns:
        Список SQL DDL statements.
    """
    if dialect == "postgres":
        pk = "id SERIAL PRIMARY KEY"
        ts_default = "DEFAULT NOW()"
    else:
        pk = "id INTEGER PRIMARY KEY AUTOINCREMENT"
        ts_default = "DEFAULT CURRENT_TIMESTAMP"

    return [
        f"""
        CREATE TABLE IF NOT EXISTS memory_bank (
            {pk},
            user_id TEXT NOT NULL,
            topic_id TEXT NOT NULL,
            path TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP {ts_default},
            updated_at TIMESTAMP {ts_default},
            UNIQUE(user_id, topic_id, path)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_memory_bank_user_topic ON memory_bank(user_id, topic_id)",
    ]
