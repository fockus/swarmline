"""Postgres-backed agent registry."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from swarmline.multi_agent.registry_types import AgentFilter, AgentRecord, AgentStatus

POSTGRES_AGENT_REGISTRY_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_registry (
    id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'idle',
    parent_id TEXT,
    data JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_registry_role ON agent_registry(role);
CREATE INDEX IF NOT EXISTS idx_agent_registry_status ON agent_registry(status);
"""


class PostgresAgentRegistry:
    """Postgres implementation of AgentRegistry protocol."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @asynccontextmanager
    async def _session(self, *, commit: bool = False) -> AsyncIterator[AsyncSession]:
        async with self._sf() as session:
            yield session
            if commit:
                await session.commit()

    @staticmethod
    def _serialize(record: AgentRecord) -> dict[str, Any]:
        d = asdict(record)
        d["status"] = record.status.value
        return d

    @staticmethod
    def _deserialize(data: dict[str, Any]) -> AgentRecord:
        d = {**data}
        d["status"] = AgentStatus(d["status"])
        return AgentRecord(**d)

    async def register(self, record: AgentRecord) -> None:
        async with self._session(commit=True) as session:
            existing = (await session.execute(
                text("SELECT 1 FROM agent_registry WHERE id = :id"),
                {"id": record.id},
            )).fetchone()
            if existing:
                raise ValueError(f"Agent '{record.id}' already registered")
            await session.execute(
                text(
                    "INSERT INTO agent_registry (id, role, status, parent_id, data) "
                    "VALUES (:id, :role, :status, :parent_id, CAST(:data AS jsonb))"
                ),
                {
                    "id": record.id, "role": record.role,
                    "status": record.status.value, "parent_id": record.parent_id,
                    "data": json.dumps(self._serialize(record)),
                },
            )

    async def get(self, agent_id: str) -> AgentRecord | None:
        async with self._session() as session:
            row = (await session.execute(
                text("SELECT data FROM agent_registry WHERE id = :id"),
                {"id": agent_id},
            )).fetchone()
            return self._deserialize(row[0]) if row else None

    async def list_agents(self, filters: AgentFilter | None = None) -> list[AgentRecord]:
        async with self._session() as session:
            conditions: list[str] = []
            params: dict[str, Any] = {}
            if filters:
                if filters.role is not None:
                    conditions.append("role = :role")
                    params["role"] = filters.role
                if filters.status is not None:
                    conditions.append("status = :status")
                    params["status"] = filters.status.value
                if filters.parent_id is not None:
                    conditions.append("parent_id = :parent_id")
                    params["parent_id"] = filters.parent_id
            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            rows = (await session.execute(
                text(f"SELECT data FROM agent_registry {where}"), params,
            )).fetchall()
            return [self._deserialize(r[0]) for r in rows]

    async def update_status(self, agent_id: str, status: AgentStatus) -> bool:
        async with self._session(commit=True) as session:
            row = (await session.execute(
                text("SELECT data FROM agent_registry WHERE id = :id FOR UPDATE"),
                {"id": agent_id},
            )).fetchone()
            if not row:
                return False
            record = self._deserialize(row[0])
            updated = AgentRecord(
                id=record.id, name=record.name, role=record.role,
                parent_id=record.parent_id, runtime_name=record.runtime_name,
                runtime_config=record.runtime_config, status=status,
                budget_limit_usd=record.budget_limit_usd, metadata=record.metadata,
            )
            await session.execute(
                text(
                    "UPDATE agent_registry SET status = :status, "
                    "data = CAST(:data AS jsonb) WHERE id = :id"
                ),
                {"id": agent_id, "status": status.value,
                 "data": json.dumps(self._serialize(updated))},
            )
            return True

    async def remove(self, agent_id: str) -> bool:
        async with self._session(commit=True) as session:
            result = await session.execute(
                text("DELETE FROM agent_registry WHERE id = :id"),
                {"id": agent_id},
            )
            return result.rowcount > 0  # type: ignore[attr-defined]
