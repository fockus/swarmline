"""TaskSessionStore — bind session state to (agent_id, task_id) pair.

Provides protocol + InMemory and SQLite implementations.
Agents can resume conversations on specific tasks after restart/heartbeat.
"""

from __future__ import annotations

import asyncio
import copy
import json
import sqlite3
import threading
import time
from typing import Any, Protocol, runtime_checkable

from cognitia.session.task_session_types import TaskSessionParams


@runtime_checkable
class TaskSessionStore(Protocol):
    """Bind session state to (agent_id, task_id) pair. ISP: 4 methods."""

    async def save(self, agent_id: str, task_id: str, params: dict[str, Any]) -> None: ...

    async def load(self, agent_id: str, task_id: str) -> dict[str, Any] | None: ...

    async def delete(self, agent_id: str, task_id: str) -> bool: ...

    async def list_by_agent(self, agent_id: str) -> list[TaskSessionParams]: ...


# ---------------------------------------------------------------------------
# InMemory implementation
# ---------------------------------------------------------------------------


class InMemoryTaskSessionStore:
    """In-memory task session store. Suitable for tests and single-process use."""

    def __init__(self, event_bus: Any | None = None) -> None:
        self._store: dict[tuple[str, str], TaskSessionParams] = {}
        self._lock = asyncio.Lock()
        self._event_bus = event_bus

    @staticmethod
    def _key(agent_id: str, task_id: str) -> tuple[str, str]:
        return agent_id, task_id

    async def save(self, agent_id: str, task_id: str, params: dict[str, Any]) -> None:
        now = time.time()
        async with self._lock:
            key = self._key(agent_id, task_id)
            existing = self._store.get(key)
            created_at = existing.created_at if existing is not None else now
            self._store[key] = TaskSessionParams(
                agent_id=agent_id,
                task_id=task_id,
                params=copy.deepcopy(params),
                created_at=created_at,
                updated_at=now,
            )
        if self._event_bus is not None:
            await self._event_bus.emit("session.task.saved", {
                "agent_id": agent_id,
                "task_id": task_id,
            })

    async def load(self, agent_id: str, task_id: str) -> dict[str, Any] | None:
        async with self._lock:
            entry = self._store.get(self._key(agent_id, task_id))
            if entry is None:
                return None
            return copy.deepcopy(entry.params)

    async def delete(self, agent_id: str, task_id: str) -> bool:
        async with self._lock:
            key = self._key(agent_id, task_id)
            if key in self._store:
                del self._store[key]
                found = True
            else:
                found = False
        if found and self._event_bus is not None:
            await self._event_bus.emit("session.task.deleted", {
                "agent_id": agent_id,
                "task_id": task_id,
            })
        return found

    async def list_by_agent(self, agent_id: str) -> list[TaskSessionParams]:
        async with self._lock:
            return [
                TaskSessionParams(
                    agent_id=entry.agent_id,
                    task_id=entry.task_id,
                    params=copy.deepcopy(entry.params),
                    created_at=entry.created_at,
                    updated_at=entry.updated_at,
                )
                for entry in self._store.values()
                if entry.agent_id == agent_id
            ]


# ---------------------------------------------------------------------------
# SQLite implementation
# ---------------------------------------------------------------------------


class SqliteTaskSessionStore:
    """SQLite-backed task session store. Zero-config, file-based.

    Uses asyncio.to_thread() to avoid blocking the event loop.
    Matches the threading.Lock + WAL pattern from backends.py.
    """

    def __init__(self, db_path: str = "cognitia_task_sessions.db", event_bus: Any | None = None) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._event_bus = event_bus
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS task_sessions ("
                "agent_id TEXT NOT NULL, "
                "task_id TEXT NOT NULL, "
                "params TEXT NOT NULL, "
                "created_at REAL NOT NULL, "
                "updated_at REAL NOT NULL, "
                "PRIMARY KEY (agent_id, task_id))"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ts_agent "
                "ON task_sessions(agent_id)"
            )
            self._conn.commit()

    # --- sync helpers (run via asyncio.to_thread) ---

    def _save_sync(self, agent_id: str, task_id: str, params_json: str) -> None:
        now = time.time()
        with self._lock:
            cursor = self._conn.execute(
                "SELECT created_at FROM task_sessions WHERE agent_id = ? AND task_id = ?",
                (agent_id, task_id),
            )
            row = cursor.fetchone()
            created_at = row[0] if row else now
            self._conn.execute(
                "INSERT OR REPLACE INTO task_sessions "
                "(agent_id, task_id, params, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (agent_id, task_id, params_json, created_at, now),
            )
            self._conn.commit()

    def _load_sync(self, agent_id: str, task_id: str) -> str | None:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT params FROM task_sessions WHERE agent_id = ? AND task_id = ?",
                (agent_id, task_id),
            )
            row = cursor.fetchone()
        return row[0] if row else None

    def _delete_sync(self, agent_id: str, task_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM task_sessions WHERE agent_id = ? AND task_id = ?",
                (agent_id, task_id),
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def _list_by_agent_sync(self, agent_id: str) -> list[TaskSessionParams]:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT agent_id, task_id, params, created_at, updated_at "
                "FROM task_sessions WHERE agent_id = ?",
                (agent_id,),
            )
            rows = cursor.fetchall()
        return [
            TaskSessionParams(
                agent_id=row[0],
                task_id=row[1],
                params=json.loads(row[2]),
                created_at=row[3],
                updated_at=row[4],
            )
            for row in rows
        ]

    # --- async API ---

    async def save(self, agent_id: str, task_id: str, params: dict[str, Any]) -> None:
        params_json = json.dumps(params, ensure_ascii=False)
        await asyncio.to_thread(self._save_sync, agent_id, task_id, params_json)
        if self._event_bus is not None:
            await self._event_bus.emit("session.task.saved", {
                "agent_id": agent_id,
                "task_id": task_id,
            })

    async def load(self, agent_id: str, task_id: str) -> dict[str, Any] | None:
        raw = await asyncio.to_thread(self._load_sync, agent_id, task_id)
        if raw is None:
            return None
        return json.loads(raw)

    async def delete(self, agent_id: str, task_id: str) -> bool:
        found = await asyncio.to_thread(self._delete_sync, agent_id, task_id)
        if found and self._event_bus is not None:
            await self._event_bus.emit("session.task.deleted", {
                "agent_id": agent_id,
                "task_id": task_id,
            })
        return found

    async def list_by_agent(self, agent_id: str) -> list[TaskSessionParams]:
        return await asyncio.to_thread(self._list_by_agent_sync, agent_id)

    def close(self) -> None:
        """Close the SQLite connection."""
        with self._lock:
            self._conn.close()
