"""DatabaseMemoryBankProvider — банк памяти в БД (Postgres + SQLite).

Dialect-agnostic через SQLAlchemy text().
Агент работает с file-like API, провайдер транслирует в SQL.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from swarmline.memory_bank.types import MemoryBankViolation, validate_memory_path


class DatabaseMemoryBankProvider:
    """MemoryBankProvider через SQLAlchemy async (Postgres/SQLite).

    SQL изолирован внутри класса. LSP: заменяет FS provider прозрачно.
    """

    def __init__(
        self, session_factory: Any, user_id: str, topic_id: str, max_depth: int = 2
    ) -> None:
        self._session_factory = session_factory
        self._user_id = user_id
        self._topic_id = topic_id
        self._max_depth = max_depth

    async def _get_session(self) -> AsyncSession:
        session: AsyncSession = self._session_factory()
        return session

    async def read_file(self, path: str) -> str | None:
        """Прочитать файл из БД."""
        validate_memory_path(path, max_depth=self._max_depth)
        async with await self._get_session() as session:
            result = await session.execute(
                text(
                    "SELECT content FROM memory_bank WHERE user_id = :u AND topic_id = :t AND path = :p"
                ),
                {"u": self._user_id, "t": self._topic_id, "p": path},
            )
            row = result.fetchone()
            return row[0] if row else None

    async def write_file(self, path: str, content: str) -> None:
        """Записать файл в БД (upsert)."""
        validate_memory_path(path, max_depth=self._max_depth)
        async with await self._get_session() as session:
            # SQLite: INSERT OR REPLACE. Postgres: ON CONFLICT DO UPDATE.
            # Используем INSERT OR REPLACE (работает на обоих через SQLite-совместимый синтаксис)
            await session.execute(
                text(
                    """
                    INSERT INTO memory_bank (user_id, topic_id, path, content, updated_at)
                    VALUES (:u, :t, :p, :c, CURRENT_TIMESTAMP)
                    ON CONFLICT (user_id, topic_id, path)
                    DO UPDATE SET content = :c, updated_at = CURRENT_TIMESTAMP
                """
                ),
                {"u": self._user_id, "t": self._topic_id, "p": path, "c": content},
            )
            await session.commit()

    async def append_to_file(self, path: str, content: str) -> None:
        """Дописать в файл (read + concat + upsert)."""
        existing = await self.read_file(path)
        new_content = f"{existing}\n{content}" if existing else content
        await self.write_file(path, new_content)

    async def list_files(self, prefix: str = "") -> list[str]:
        """Список файлов."""
        async with await self._get_session() as session:
            if prefix:
                result = await session.execute(
                    text(
                        "SELECT path FROM memory_bank WHERE user_id = :u AND topic_id = :t AND path LIKE :prefix ORDER BY path"
                    ),
                    {"u": self._user_id, "t": self._topic_id, "prefix": f"{prefix}%"},
                )
            else:
                result = await session.execute(
                    text(
                        "SELECT path FROM memory_bank WHERE user_id = :u AND topic_id = :t ORDER BY path"
                    ),
                    {"u": self._user_id, "t": self._topic_id},
                )
            return [row[0] for row in result.fetchall()]

    async def delete_file(self, path: str) -> None:
        """Удалить файл из БД."""
        try:
            validate_memory_path(path, max_depth=self._max_depth)
        except MemoryBankViolation:
            return
        async with await self._get_session() as session:
            await session.execute(
                text("DELETE FROM memory_bank WHERE user_id = :u AND topic_id = :t AND path = :p"),
                {"u": self._user_id, "t": self._topic_id, "p": path},
            )
            await session.commit()
