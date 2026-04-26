"""SQLite-backed agent registry."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import sqlite3
import threading

from swarmline.multi_agent.registry_types import AgentFilter, AgentRecord, AgentStatus


class SqliteAgentRegistry:
    """SQLite implementation of AgentRegistry protocol.

    Uses asyncio.to_thread for non-blocking I/O.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS agent_registry "
            "(id TEXT PRIMARY KEY, data TEXT NOT NULL)"
        )
        self._conn.commit()

    @staticmethod
    def _ser(record: AgentRecord) -> str:
        d = dataclasses.asdict(record)
        d["status"] = record.status.value
        return json.dumps(d)

    @staticmethod
    def _deser(raw: str) -> AgentRecord:
        d = json.loads(raw)
        d["status"] = AgentStatus(d["status"])
        return AgentRecord(**d)

    def _register_sync(self, record: AgentRecord) -> None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT 1 FROM agent_registry WHERE id = ?", (record.id,)
            )
            if cur.fetchone():
                raise ValueError(f"Agent '{record.id}' already registered")
            self._conn.execute(
                "INSERT INTO agent_registry (id, data) VALUES (?, ?)",
                (record.id, self._ser(record)),
            )
            self._conn.commit()

    def _get_sync(self, agent_id: str) -> AgentRecord | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT data FROM agent_registry WHERE id = ?", (agent_id,)
            )
            row = cur.fetchone()
            return self._deser(row[0]) if row else None

    def _list_sync(self) -> list[AgentRecord]:
        with self._lock:
            cur = self._conn.execute("SELECT data FROM agent_registry")
            return [self._deser(r[0]) for r in cur.fetchall()]

    def _update_status_sync(self, agent_id: str, status: AgentStatus) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "SELECT data FROM agent_registry WHERE id = ?", (agent_id,)
            )
            row = cur.fetchone()
            if not row:
                return False
            record = self._deser(row[0])
            updated = dataclasses.replace(record, status=status)
            self._conn.execute(
                "UPDATE agent_registry SET data = ? WHERE id = ?",
                (self._ser(updated), agent_id),
            )
            self._conn.commit()
            return True

    def _remove_sync(self, agent_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM agent_registry WHERE id = ?", (agent_id,)
            )
            self._conn.commit()
            return cur.rowcount > 0

    # --- Async API ---

    async def register(self, record: AgentRecord) -> None:
        await asyncio.to_thread(self._register_sync, record)

    async def get(self, agent_id: str) -> AgentRecord | None:
        return await asyncio.to_thread(self._get_sync, agent_id)

    async def list_agents(
        self, filters: AgentFilter | None = None
    ) -> list[AgentRecord]:
        records = await asyncio.to_thread(self._list_sync)
        if filters:
            if filters.role is not None:
                records = [r for r in records if r.role == filters.role]
            if filters.status is not None:
                records = [r for r in records if r.status == filters.status]
            if filters.parent_id is not None:
                records = [r for r in records if r.parent_id == filters.parent_id]
        return records

    async def update_status(self, agent_id: str, status: AgentStatus) -> bool:
        return await asyncio.to_thread(self._update_status_sync, agent_id, status)

    async def remove(self, agent_id: str) -> bool:
        return await asyncio.to_thread(self._remove_sync, agent_id)
