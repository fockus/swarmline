"""In-memory graph communication — direct, broadcast, escalation."""

from __future__ import annotations

import uuid
from typing import Any

from swarmline.multi_agent.graph_comm_types import ChannelType, GraphMessage


class InMemoryGraphCommunication:
    """In-memory implementation of GraphCommunication.

    Requires an AgentGraphQuery for subtree/chain traversal.
    Optionally emits events via EventBus.
    """

    def __init__(self, graph_query: Any, event_bus: Any | None = None) -> None:
        self._graph = graph_query
        self._bus = event_bus
        self._messages: list[GraphMessage] = []

    async def send_direct(self, msg: GraphMessage) -> None:
        self._messages.append(msg)
        await self._emit("graph.message.direct", msg)

    async def broadcast_subtree(
        self, from_id: str, content: str, *, task_id: str | None = None
    ) -> None:
        descendants = await self._graph.get_subtree(from_id)
        for node in descendants:
            if node.id == from_id:
                continue  # skip self
            msg = GraphMessage(
                id=uuid.uuid4().hex,
                from_agent_id=from_id,
                to_agent_id=node.id,
                channel=ChannelType.BROADCAST,
                content=content,
                task_id=task_id,
            )
            self._messages.append(msg)
            await self._emit("graph.message.broadcast", msg)

    async def escalate(
        self, from_id: str, content: str, *, task_id: str | None = None
    ) -> None:
        chain = await self._graph.get_chain_of_command(from_id)
        # Skip self (first in chain), send to all ancestors
        for node in chain[1:]:
            msg = GraphMessage(
                id=uuid.uuid4().hex,
                from_agent_id=from_id,
                to_agent_id=node.id,
                channel=ChannelType.ESCALATION,
                content=content,
                task_id=task_id,
            )
            self._messages.append(msg)
            await self._emit("graph.message.escalation", msg)

    async def get_inbox(self, agent_id: str) -> list[GraphMessage]:
        return [m for m in self._messages if m.to_agent_id == agent_id]

    async def get_thread(self, task_id: str) -> list[GraphMessage]:
        return [m for m in self._messages if m.task_id == task_id]

    async def _emit(self, topic: str, msg: GraphMessage) -> None:
        if self._bus is not None:
            await self._bus.emit(topic, {
                "id": msg.id,
                "from": msg.from_agent_id,
                "to": msg.to_agent_id,
                "channel": msg.channel.value,
                "task_id": msg.task_id,
            })
