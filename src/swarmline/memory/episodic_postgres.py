"""Postgres-backed episodic memory — full-text search via tsvector."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from swarmline.memory.episodic_types import Episode

POSTGRES_EPISODIC_SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    outcome TEXT NOT NULL DEFAULT 'unknown',
    session_id TEXT NOT NULL DEFAULT '',
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    data JSONB NOT NULL,
    search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector('english', summary)
    ) STORED
);
CREATE INDEX IF NOT EXISTS idx_episodes_timestamp ON episodes(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_episodes_search ON episodes USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS idx_episodes_tags ON episodes USING GIN((data->'tags'));
"""


class PostgresEpisodicMemory:
    """Postgres episodic memory with full-text search via tsvector."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @asynccontextmanager
    async def _session(self, *, commit: bool = False) -> AsyncIterator[AsyncSession]:
        async with self._sf() as session:
            yield session
            if commit:
                await session.commit()

    @staticmethod
    def _serialize(ep: Episode) -> dict[str, Any]:
        return {
            "id": ep.id,
            "summary": ep.summary,
            "key_decisions": list(ep.key_decisions),
            "tools_used": list(ep.tools_used),
            "outcome": ep.outcome,
            "session_id": ep.session_id,
            "timestamp": ep.timestamp.isoformat(),
            "tags": list(ep.tags),
            "metadata": ep.metadata,
        }

    @staticmethod
    def _deserialize(data: dict[str, Any]) -> Episode:
        ts = data.get("timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        elif not isinstance(ts, datetime):
            ts = datetime.now(UTC)
        return Episode(
            id=data["id"],
            summary=data["summary"],
            key_decisions=tuple(data.get("key_decisions", ())),
            tools_used=tuple(data.get("tools_used", ())),
            outcome=data.get("outcome", "unknown"),
            session_id=data.get("session_id", ""),
            timestamp=ts,
            tags=tuple(data.get("tags", ())),
            metadata=data.get("metadata", {}),
        )

    async def store(self, episode: Episode) -> None:
        async with self._session(commit=True) as session:
            await session.execute(
                text(
                    "INSERT INTO episodes (id, summary, outcome, session_id, timestamp, data) "
                    "VALUES (:id, :summary, :outcome, :session_id, :ts, CAST(:data AS jsonb))"
                ),
                {
                    "id": episode.id,
                    "summary": episode.summary,
                    "outcome": episode.outcome,
                    "session_id": episode.session_id,
                    "ts": episode.timestamp,
                    "data": json.dumps(self._serialize(episode)),
                },
            )

    async def recall(self, query: str, *, top_k: int = 5) -> list[Episode]:
        async with self._session() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT data, ts_rank(search_vector, plainto_tsquery('english', :query)) AS rank "
                        "FROM episodes "
                        "WHERE search_vector @@ plainto_tsquery('english', :query) "
                        "ORDER BY rank DESC LIMIT :limit"
                    ),
                    {"query": query, "limit": top_k},
                )
            ).fetchall()
            return [self._deserialize(r[0]) for r in rows]

    async def recall_recent(self, n: int = 10) -> list[Episode]:
        async with self._session() as session:
            rows = (
                await session.execute(
                    text("SELECT data FROM episodes ORDER BY timestamp DESC LIMIT :n"),
                    {"n": n},
                )
            ).fetchall()
            return [self._deserialize(r[0]) for r in rows]

    async def recall_by_tag(self, tag: str) -> list[Episode]:
        async with self._session() as session:
            rows = (
                await session.execute(
                    text("SELECT data FROM episodes WHERE data->'tags' ? :tag"),
                    {"tag": tag},
                )
            ).fetchall()
            return [self._deserialize(r[0]) for r in rows]

    async def count(self) -> int:
        async with self._session() as session:
            row = (
                await session.execute(text("SELECT count(*) FROM episodes"))
            ).fetchone()
            return row[0] if row else 0
