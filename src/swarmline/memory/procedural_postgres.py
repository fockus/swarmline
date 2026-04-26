"""Postgres-backed procedural memory — learned tool sequences."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from swarmline.memory.procedural_types import Procedure, ProcedureStep

POSTGRES_PROCEDURAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS procedures (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    trigger TEXT NOT NULL,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    data JSONB NOT NULL,
    search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector('english', name || ' ' || trigger || ' ' || COALESCE(data->>'description', ''))
    ) STORED
);
CREATE INDEX IF NOT EXISTS idx_procedures_search ON procedures USING GIN(search_vector);
"""


class PostgresProceduralMemory:
    """Postgres procedural memory with full-text search."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @asynccontextmanager
    async def _session(self, *, commit: bool = False) -> AsyncIterator[AsyncSession]:
        async with self._sf() as session:
            yield session
            if commit:
                await session.commit()

    @staticmethod
    def _serialize(proc: Procedure) -> dict[str, Any]:
        return {
            "id": proc.id,
            "name": proc.name,
            "description": proc.description,
            "trigger": proc.trigger,
            "steps": [
                {
                    "tool_name": s.tool_name,
                    "args_template": s.args_template,
                    "expected_outcome": s.expected_outcome,
                }
                for s in proc.steps
            ],
            "success_count": proc.success_count,
            "failure_count": proc.failure_count,
            "tags": list(proc.tags),
            "metadata": proc.metadata,
        }

    @staticmethod
    def _deserialize(data: dict[str, Any]) -> Procedure:
        steps = tuple(
            ProcedureStep(
                tool_name=s["tool_name"],
                args_template=s.get("args_template", {}),
                expected_outcome=s.get("expected_outcome", ""),
            )
            for s in data.get("steps", ())
        )
        return Procedure(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            trigger=data.get("trigger", ""),
            steps=steps,
            success_count=data.get("success_count", 0),
            failure_count=data.get("failure_count", 0),
            tags=tuple(data.get("tags", ())),
            metadata=data.get("metadata", {}),
        )

    async def store(self, procedure: Procedure) -> None:
        async with self._session(commit=True) as session:
            await session.execute(
                text(
                    "INSERT INTO procedures (id, name, trigger, success_count, failure_count, data) "
                    "VALUES (:id, :name, :trigger, :sc, :fc, CAST(:data AS jsonb)) "
                    "ON CONFLICT (id) DO UPDATE SET "
                    "name = EXCLUDED.name, trigger = EXCLUDED.trigger, "
                    "success_count = EXCLUDED.success_count, failure_count = EXCLUDED.failure_count, "
                    "data = EXCLUDED.data"
                ),
                {
                    "id": procedure.id,
                    "name": procedure.name,
                    "trigger": procedure.trigger,
                    "sc": procedure.success_count,
                    "fc": procedure.failure_count,
                    "data": json.dumps(self._serialize(procedure)),
                },
            )

    async def suggest(self, query: str, *, top_k: int = 3) -> list[Procedure]:
        async with self._session() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT data, "
                        "ts_rank(search_vector, plainto_tsquery('english', :query)) "
                        "+ CASE WHEN (success_count + failure_count) > 0 "
                        "  THEN success_count::float / (success_count + failure_count) "
                        "  ELSE 0 END AS score "
                        "FROM procedures "
                        "WHERE search_vector @@ plainto_tsquery('english', :query) "
                        "ORDER BY score DESC LIMIT :limit"
                    ),
                    {"query": query, "limit": top_k},
                )
            ).fetchall()
            return [self._deserialize(r[0]) for r in rows]

    async def record_outcome(self, proc_id: str, *, success: bool) -> None:
        col = "success_count" if success else "failure_count"
        async with self._session(commit=True) as session:
            row = (
                await session.execute(
                    text("SELECT data FROM procedures WHERE id = :id FOR UPDATE"),
                    {"id": proc_id},
                )
            ).fetchone()
            if not row:
                return
            proc = self._deserialize(row[0])
            new_sc = proc.success_count + (1 if success else 0)
            new_fc = proc.failure_count + (0 if success else 1)
            updated = Procedure(
                id=proc.id,
                name=proc.name,
                description=proc.description,
                trigger=proc.trigger,
                steps=proc.steps,
                success_count=new_sc,
                failure_count=new_fc,
                tags=proc.tags,
                metadata=proc.metadata,
            )
            await session.execute(
                text(
                    f"UPDATE procedures SET {col} = {col} + 1, "
                    "data = CAST(:data AS jsonb) WHERE id = :id"
                ),
                {"id": proc_id, "data": json.dumps(self._serialize(updated))},
            )

    async def get(self, proc_id: str) -> Procedure | None:
        async with self._session() as session:
            row = (
                await session.execute(
                    text("SELECT data FROM procedures WHERE id = :id"),
                    {"id": proc_id},
                )
            ).fetchone()
            return self._deserialize(row[0]) if row else None

    async def count(self) -> int:
        async with self._session() as session:
            row = (
                await session.execute(text("SELECT count(*) FROM procedures"))
            ).fetchone()
            return row[0] if row else 0
