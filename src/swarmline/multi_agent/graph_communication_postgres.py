"""Postgres-backed graph communication — persistent inter-agent messaging."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from swarmline.multi_agent.graph_comm_types import ChannelType, GraphMessage

POSTGRES_GRAPH_COMM_SCHEMA = """
CREATE TABLE IF NOT EXISTS graph_messages (
    id TEXT PRIMARY KEY,
    from_agent_id TEXT NOT NULL,
    to_agent_id TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'direct',
    content TEXT NOT NULL,
    task_id TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_graph_messages_to ON graph_messages(to_agent_id);
CREATE INDEX IF NOT EXISTS idx_graph_messages_task ON graph_messages(task_id);
"""


class PostgresGraphCommunication:
    """Postgres implementation of GraphCommunication.

    Requires an AgentGraphQuery for subtree/chain traversal.
    Optionally emits events via EventBus.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        graph_query: Any,
        event_bus: Any | None = None,
    ) -> None:
        self._sf = session_factory
        self._graph = graph_query
        self._bus = event_bus

    @asynccontextmanager
    async def _session(self, *, commit: bool = False) -> AsyncIterator[AsyncSession]:
        async with self._sf() as session:
            yield session
            if commit:
                await session.commit()

    async def _store_msg(self, session: AsyncSession, msg: GraphMessage) -> None:
        import json as _json

        await session.execute(
            text(
                "INSERT INTO graph_messages "
                "(id, from_agent_id, to_agent_id, channel, content, task_id, created_at, metadata) "
                "VALUES (:id, :from_id, :to_id, :channel, :content, :task_id, :created_at, :metadata)"
            ),
            {
                "id": msg.id,
                "from_id": msg.from_agent_id,
                "to_id": msg.to_agent_id,
                "channel": msg.channel.value,
                "content": msg.content,
                "task_id": msg.task_id,
                "created_at": msg.created_at,
                "metadata": _json.dumps(msg.metadata),
            },
        )

    async def send_direct(self, msg: GraphMessage) -> None:
        async with self._session(commit=True) as session:
            await self._store_msg(session, msg)
        await self._emit("graph.message.direct", msg)

    async def broadcast_subtree(
        self,
        from_id: str,
        content: str,
        *,
        task_id: str | None = None,
    ) -> None:
        descendants = await self._graph.get_subtree(from_id)
        async with self._session(commit=True) as session:
            for node in descendants:
                if node.id == from_id:
                    continue
                msg = GraphMessage(
                    id=uuid.uuid4().hex,
                    from_agent_id=from_id,
                    to_agent_id=node.id,
                    channel=ChannelType.BROADCAST,
                    content=content,
                    task_id=task_id,
                )
                await self._store_msg(session, msg)
                await self._emit("graph.message.broadcast", msg)

    async def escalate(
        self,
        from_id: str,
        content: str,
        *,
        task_id: str | None = None,
    ) -> None:
        chain = await self._graph.get_chain_of_command(from_id)
        async with self._session(commit=True) as session:
            for node in chain[1:]:
                msg = GraphMessage(
                    id=uuid.uuid4().hex,
                    from_agent_id=from_id,
                    to_agent_id=node.id,
                    channel=ChannelType.ESCALATION,
                    content=content,
                    task_id=task_id,
                )
                await self._store_msg(session, msg)
                await self._emit("graph.message.escalation", msg)

    def _row_to_msg(self, r: Any) -> GraphMessage:
        import json as _json

        meta = r[7] if r[7] else {}
        if isinstance(meta, str):
            meta = _json.loads(meta)
        return GraphMessage(
            id=r[0],
            from_agent_id=r[1],
            to_agent_id=r[2],
            channel=ChannelType(r[3]),
            content=r[4],
            task_id=r[5],
            created_at=float(r[6]),
            metadata=meta,
        )

    async def get_inbox(self, agent_id: str) -> list[GraphMessage]:
        async with self._session() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, from_agent_id, to_agent_id, channel, content, task_id, created_at, metadata "
                        "FROM graph_messages WHERE to_agent_id = :id ORDER BY created_at"
                    ),
                    {"id": agent_id},
                )
            ).fetchall()
            return [self._row_to_msg(r) for r in rows]

    async def get_thread(self, task_id: str) -> list[GraphMessage]:
        async with self._session() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, from_agent_id, to_agent_id, channel, content, task_id, created_at, metadata "
                        "FROM graph_messages WHERE task_id = :id ORDER BY created_at"
                    ),
                    {"id": task_id},
                )
            ).fetchall()
            return [self._row_to_msg(r) for r in rows]

    async def _emit(self, topic: str, msg: GraphMessage) -> None:
        if self._bus is not None:
            await self._bus.emit(
                topic,
                {
                    "id": msg.id,
                    "from": msg.from_agent_id,
                    "to": msg.to_agent_id,
                    "channel": msg.channel.value,
                    "task_id": msg.task_id,
                },
            )
