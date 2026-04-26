"""Postgres-backed task queue — atomic claim via SELECT ... FOR UPDATE SKIP LOCKED."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from swarmline.multi_agent.task_types import (
    TaskFilter,
    TaskItem,
    TaskPriority,
    TaskStatus,
)

POSTGRES_TASK_QUEUE_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_queue (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'todo',
    priority TEXT NOT NULL DEFAULT 'medium',
    assignee_agent_id TEXT,
    data JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_queue_status ON task_queue(status);
CREATE INDEX IF NOT EXISTS idx_task_queue_priority ON task_queue(priority);
"""

_PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


class PostgresTaskQueue:
    """Postgres implementation of TaskQueue protocol.

    Uses FOR UPDATE SKIP LOCKED for atomic claim.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @asynccontextmanager
    async def _session(self, *, commit: bool = False) -> AsyncIterator[AsyncSession]:
        async with self._sf() as session:
            yield session
            if commit:
                await session.commit()

    @staticmethod
    def _serialize(item: TaskItem) -> dict[str, Any]:
        d = asdict(item)
        d["status"] = item.status.value
        d["priority"] = item.priority.value
        return d

    @staticmethod
    def _deserialize(data: dict[str, Any]) -> TaskItem:
        d = {**data}
        d["status"] = TaskStatus(d["status"])
        d["priority"] = TaskPriority(d["priority"])
        return TaskItem(**d)

    async def put(self, item: TaskItem) -> None:
        async with self._session(commit=True) as session:
            await session.execute(
                text(
                    "INSERT INTO task_queue (id, status, priority, assignee_agent_id, data) "
                    "VALUES (:id, :status, :priority, :assignee, CAST(:data AS jsonb)) "
                    "ON CONFLICT (id) DO UPDATE SET "
                    "status = EXCLUDED.status, priority = EXCLUDED.priority, "
                    "assignee_agent_id = EXCLUDED.assignee_agent_id, data = EXCLUDED.data"
                ),
                {
                    "id": item.id,
                    "status": item.status.value,
                    "priority": item.priority.value,
                    "assignee": item.assignee_agent_id,
                    "data": json.dumps(self._serialize(item)),
                },
            )

    async def get(self, filters: TaskFilter | None = None) -> TaskItem | None:
        async with self._session(commit=True) as session:
            # Build WHERE clause
            conditions = ["status = 'todo'"]
            params: dict[str, Any] = {}
            if filters and filters.priority:
                conditions.append("priority = :priority")
                params["priority"] = filters.priority.value
            if filters and filters.assignee_agent_id:
                conditions.append("assignee_agent_id = :assignee")
                params["assignee"] = filters.assignee_agent_id
            elif not filters or filters.assignee_agent_id is None:
                conditions.append("assignee_agent_id IS NULL")

            where = " AND ".join(conditions)
            row = (
                await session.execute(
                    text(
                        f"SELECT data FROM task_queue WHERE {where} "
                        "ORDER BY CASE priority "
                        "WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
                        "WHEN 'medium' THEN 2 WHEN 'low' THEN 3 END "
                        "LIMIT 1 FOR UPDATE SKIP LOCKED"
                    ),
                    params,
                )
            ).fetchone()
            if not row:
                return None

            item = self._deserialize(row[0])
            claimed = replace(item, status=TaskStatus.IN_PROGRESS)
            await session.execute(
                text(
                    "UPDATE task_queue SET status = 'in_progress', "
                    "data = CAST(:data AS jsonb) WHERE id = :id"
                ),
                {"id": claimed.id, "data": json.dumps(self._serialize(claimed))},
            )
            return claimed

    async def complete(self, task_id: str) -> bool:
        return await self._transition(task_id, TaskStatus.DONE)

    async def cancel(self, task_id: str) -> bool:
        return await self._transition(task_id, TaskStatus.CANCELLED)

    async def list_tasks(self, filters: TaskFilter | None = None) -> list[TaskItem]:
        async with self._session() as session:
            rows = (
                await session.execute(text("SELECT data FROM task_queue"))
            ).fetchall()
        items = [self._deserialize(r[0]) for r in rows]
        if filters:
            if filters.status:
                items = [i for i in items if i.status == filters.status]
            if filters.priority:
                items = [i for i in items if i.priority == filters.priority]
            if filters.assignee_agent_id:
                items = [
                    i for i in items if i.assignee_agent_id == filters.assignee_agent_id
                ]
        return items

    async def _transition(self, task_id: str, target: TaskStatus) -> bool:
        terminal = {TaskStatus.DONE, TaskStatus.CANCELLED}
        async with self._session(commit=True) as session:
            row = (
                await session.execute(
                    text("SELECT data FROM task_queue WHERE id = :id FOR UPDATE"),
                    {"id": task_id},
                )
            ).fetchone()
            if not row:
                return False
            item = self._deserialize(row[0])
            if item.status in terminal:
                return False
            updated = replace(item, status=target)
            await session.execute(
                text(
                    "UPDATE task_queue SET status = :status, data = CAST(:data AS jsonb) WHERE id = :id"
                ),
                {
                    "id": task_id,
                    "status": target.value,
                    "data": json.dumps(self._serialize(updated)),
                },
            )
            return True
