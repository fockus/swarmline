"""NATS-backed graph communication — real-time inter-agent messaging via NATS JetStream.

Messages stored in NATS JetStream for durability and replay.
Each agent inbox is a subject: ``swarmline.inbox.{agent_id}``.
Task threads use: ``swarmline.thread.{task_id}``.
Requires ``nats-py`` (lazy import).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from swarmline.multi_agent.graph_comm_types import ChannelType, GraphMessage


class NatsGraphCommunication:
    """NATS JetStream-based implementation of GraphCommunication.

    Uses JetStream for durable, ordered message storage.
    Falls back to core NATS (volatile) if JetStream not available.

    Optionally emits events via EventBus.
    """

    def __init__(
        self,
        nats_url: str,
        graph_query: Any,
        *,
        event_bus: Any | None = None,
        subject_prefix: str = "swarmline",
        stream_name: str = "SWARMLINE_MESSAGES",
    ) -> None:
        self._url = nats_url
        self._graph = graph_query
        self._bus = event_bus
        self._prefix = subject_prefix
        self._stream_name = stream_name
        self._nc: Any = None
        self._js: Any = None
        self._messages: list[GraphMessage] = []  # local fallback cache

    async def connect(self) -> None:
        """Initialize NATS connection and JetStream context."""
        try:
            import nats
        except ImportError as exc:
            raise ImportError(
                "nats-py package required: pip install 'swarmline[nats]' "
                "or pip install nats-py"
            ) from exc

        self._nc = await nats.connect(self._url)
        self._js = self._nc.jetstream()

        # Ensure stream exists
        try:
            await self._js.find_stream_name_by_subject(f"{self._prefix}.>")
        except Exception:  # noqa: BLE001
            await self._js.add_stream(
                name=self._stream_name,
                subjects=[f"{self._prefix}.>"],
            )

    async def close(self) -> None:
        """Close NATS connection."""
        if self._nc and not self._nc.is_closed:
            await self._nc.drain()

    def _msg_to_payload(self, msg: GraphMessage) -> bytes:
        return json.dumps({
            "id": msg.id, "from": msg.from_agent_id,
            "to": msg.to_agent_id, "channel": msg.channel.value,
            "content": msg.content, "task_id": msg.task_id,
            "created_at": msg.created_at,
            "metadata": msg.metadata,
        }).encode()

    @staticmethod
    def _payload_to_msg(data: bytes) -> GraphMessage:
        d = json.loads(data.decode())
        return GraphMessage(
            id=d["id"], from_agent_id=d["from"],
            to_agent_id=d["to"], channel=ChannelType(d["channel"]),
            content=d["content"], task_id=d.get("task_id"),
            created_at=float(d.get("created_at", 0)),
            metadata=d.get("metadata", {}),
        )

    async def _publish(self, subject: str, msg: GraphMessage) -> None:
        """Publish to JetStream, fallback to core NATS."""
        self._messages.append(msg)
        if self._js is not None:
            await self._js.publish(subject, self._msg_to_payload(msg))
        elif self._nc is not None:
            await self._nc.publish(subject, self._msg_to_payload(msg))

    async def send_direct(self, msg: GraphMessage) -> None:
        subject = f"{self._prefix}.inbox.{msg.to_agent_id}"
        await self._publish(subject, msg)
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
            subject = f"{self._prefix}.inbox.{node.id}"
            await self._publish(subject, msg)
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
            subject = f"{self._prefix}.inbox.{node.id}"
            await self._publish(subject, msg)
            await self._emit("graph.message.escalation", msg)

    async def _fetch_from_jetstream(self, subject_filter: str) -> list[GraphMessage]:
        """Fetch messages from JetStream via ordered consumer with subject filter."""
        if self._js is None:
            return []
        try:
            # Create ephemeral ordered consumer with subject filter
            sub = await self._js.subscribe(
                subject_filter,
                ordered_consumer=True,
            )
            messages: list[GraphMessage] = []
            try:
                while True:
                    try:
                        raw = await sub.next_msg(timeout=0.5)
                        messages.append(self._payload_to_msg(raw.data))
                    except Exception:  # noqa: BLE001
                        break  # no more messages
            finally:
                await sub.unsubscribe()
            return messages
        except Exception:  # noqa: BLE001
            # Fallback to local cache on any JetStream error
            return []

    async def get_inbox(self, agent_id: str) -> list[GraphMessage]:
        """Get inbox from JetStream, fallback to local cache."""
        if self._js is not None:
            js_msgs = await self._fetch_from_jetstream(
                f"{self._prefix}.inbox.{agent_id}"
            )
            if js_msgs:
                return js_msgs
        return [m for m in self._messages if m.to_agent_id == agent_id]

    async def get_thread(self, task_id: str) -> list[GraphMessage]:
        """Get thread from JetStream, fallback to local cache."""
        if self._js is not None:
            # Thread messages are in inbox subjects, filter by task_id
            all_msgs = await self._fetch_from_jetstream(f"{self._prefix}.>")
            thread = [m for m in all_msgs if m.task_id == task_id]
            if thread:
                return thread
        return [m for m in self._messages if m.task_id == task_id]

    async def _emit(self, topic: str, msg: GraphMessage) -> None:
        if self._bus is not None:
            await self._bus.emit(topic, {
                "id": msg.id, "from": msg.from_agent_id,
                "to": msg.to_agent_id, "channel": msg.channel.value,
                "task_id": msg.task_id,
            })
