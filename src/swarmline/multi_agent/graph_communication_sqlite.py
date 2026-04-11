"""SQLite-backed graph communication — persistent inter-agent messaging."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import uuid
from typing import Any

from swarmline.multi_agent.graph_comm_types import ChannelType, GraphMessage

_DDL = """
CREATE TABLE IF NOT EXISTS graph_messages (
    id TEXT PRIMARY KEY,
    from_agent_id TEXT NOT NULL,
    to_agent_id TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'direct',
    content TEXT NOT NULL,
    task_id TEXT,
    created_at REAL NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_gm_to ON graph_messages(to_agent_id);
CREATE INDEX IF NOT EXISTS idx_gm_task ON graph_messages(task_id);
"""


class SqliteGraphCommunication:
    """SQLite implementation of GraphCommunication.

    Requires an AgentGraphQuery for subtree/chain traversal.
    Optionally emits events via EventBus.
    """

    def __init__(
        self,
        graph_query: Any,
        db_path: str = ":memory:",
        event_bus: Any | None = None,
    ) -> None:
        self._graph = graph_query
        self._bus = event_bus
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        self._conn.executescript(_DDL)
        self._conn.commit()

    # --- sync helpers ---

    def _store_sync(self, msg: GraphMessage) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO graph_messages "
                "(id, from_agent_id, to_agent_id, channel, content, task_id, created_at, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (msg.id, msg.from_agent_id, msg.to_agent_id,
                 msg.channel.value, msg.content, msg.task_id,
                 msg.created_at, json.dumps(msg.metadata)),
            )
            self._conn.commit()

    def _inbox_sync(self, agent_id: str) -> list[GraphMessage]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT id, from_agent_id, to_agent_id, channel, content, task_id, created_at, metadata "
                "FROM graph_messages WHERE to_agent_id = ? ORDER BY created_at",
                (agent_id,),
            )
            return [self._row_to_msg(r) for r in cur.fetchall()]

    def _thread_sync(self, task_id: str) -> list[GraphMessage]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT id, from_agent_id, to_agent_id, channel, content, task_id, created_at, metadata "
                "FROM graph_messages WHERE task_id = ? ORDER BY created_at",
                (task_id,),
            )
            return [self._row_to_msg(r) for r in cur.fetchall()]

    @staticmethod
    def _row_to_msg(r: tuple) -> GraphMessage:
        return GraphMessage(
            id=r[0], from_agent_id=r[1], to_agent_id=r[2],
            channel=ChannelType(r[3]), content=r[4], task_id=r[5],
            created_at=r[6], metadata=json.loads(r[7]) if r[7] else {},
        )

    # --- async API ---

    async def send_direct(self, msg: GraphMessage) -> None:
        await asyncio.to_thread(self._store_sync, msg)
        await self._emit("graph.message.direct", msg)

    async def broadcast_subtree(
        self, from_id: str, content: str, *, task_id: str | None = None,
    ) -> None:
        descendants = await self._graph.get_subtree(from_id)
        for node in descendants:
            if node.id == from_id:
                continue
            msg = GraphMessage(
                id=uuid.uuid4().hex,
                from_agent_id=from_id, to_agent_id=node.id,
                channel=ChannelType.BROADCAST,
                content=content, task_id=task_id,
            )
            await asyncio.to_thread(self._store_sync, msg)
            await self._emit("graph.message.broadcast", msg)

    async def escalate(
        self, from_id: str, content: str, *, task_id: str | None = None,
    ) -> None:
        chain = await self._graph.get_chain_of_command(from_id)
        for node in chain[1:]:
            msg = GraphMessage(
                id=uuid.uuid4().hex,
                from_agent_id=from_id, to_agent_id=node.id,
                channel=ChannelType.ESCALATION,
                content=content, task_id=task_id,
            )
            await asyncio.to_thread(self._store_sync, msg)
            await self._emit("graph.message.escalation", msg)

    async def get_inbox(self, agent_id: str) -> list[GraphMessage]:
        return await asyncio.to_thread(self._inbox_sync, agent_id)

    async def get_thread(self, task_id: str) -> list[GraphMessage]:
        return await asyncio.to_thread(self._thread_sync, task_id)

    async def _emit(self, topic: str, msg: GraphMessage) -> None:
        if self._bus is not None:
            await self._bus.emit(topic, {
                "id": msg.id, "from": msg.from_agent_id,
                "to": msg.to_agent_id, "channel": msg.channel.value,
                "task_id": msg.task_id,
            })
