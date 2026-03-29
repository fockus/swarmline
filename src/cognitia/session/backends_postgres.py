"""Postgres-backed session backend."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

POSTGRES_SESSION_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    key TEXT PRIMARY KEY,
    state JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class PostgresSessionBackend:
    """Postgres session backend — persistent, async, JSONB storage."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @asynccontextmanager
    async def _session(self, *, commit: bool = False) -> AsyncIterator[AsyncSession]:
        async with self._sf() as session:
            yield session
            if commit:
                await session.commit()

    async def save(self, key: str, state: dict[str, Any]) -> None:
        async with self._session(commit=True) as session:
            await session.execute(
                text(
                    "INSERT INTO sessions (key, state) "
                    "VALUES (:key, CAST(:state AS jsonb)) "
                    "ON CONFLICT (key) DO UPDATE SET "
                    "state = EXCLUDED.state, updated_at = now()"
                ),
                {"key": key, "state": json.dumps(state)},
            )

    async def load(self, key: str) -> dict[str, Any] | None:
        async with self._session() as session:
            row = (await session.execute(
                text("SELECT state FROM sessions WHERE key = :key"),
                {"key": key},
            )).fetchone()
            return row[0] if row else None

    async def delete(self, key: str) -> bool:
        async with self._session(commit=True) as session:
            result = await session.execute(
                text("DELETE FROM sessions WHERE key = :key"),
                {"key": key},
            )
            return result.rowcount > 0

    async def list_keys(self) -> list[str]:
        async with self._session() as session:
            rows = (await session.execute(text("SELECT key FROM sessions"))).fetchall()
            return [r[0] for r in rows]
