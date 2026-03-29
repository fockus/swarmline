"""Redis-backed EventBus — distributed pub/sub via Redis Pub/Sub.

Local subscribers are called directly (same as InMemory).
Cross-process subscribers receive events via Redis channels.
Requires ``redis[hiredis]`` (lazy import).

Usage::

    from cognitia.observability.event_bus_redis import RedisEventBus

    bus = RedisEventBus(redis_url="redis://localhost:6379/0")
    await bus.connect()
    bus.subscribe("llm_call_end", my_callback)
    await bus.emit("llm_call_end", {"model": "sonnet"})
    await bus.close()
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Callable


class RedisEventBus:
    """EventBus backed by Redis Pub/Sub for distributed eventing.

    - Local callbacks are invoked directly (fire-and-forget, same as InMemory).
    - Events are also published to a Redis channel ``cognitia:{event_type}``
      so that other processes can subscribe.
    - A background listener task receives remote events and dispatches to
      local callbacks.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        *,
        channel_prefix: str = "cognitia",
    ) -> None:
        self._url = redis_url
        self._prefix = channel_prefix
        self._subscribers: dict[str, dict[str, Callable[..., Any]]] = {}
        self._counter = 0
        self._redis: Any = None
        self._pubsub: Any = None
        self._listener_task: asyncio.Task[None] | None = None
        self._origin_id: str = uuid.uuid4().hex[:12]

    async def connect(self) -> None:
        """Initialize Redis connection and start background listener."""
        try:
            from redis.asyncio import Redis
        except ImportError as exc:
            raise ImportError(
                "redis package required: pip install 'cognitia[redis]' "
                "or pip install redis[hiredis]"
            ) from exc

        self._redis = Redis.from_url(self._url, decode_responses=True)
        self._pubsub = self._redis.pubsub()
        self._listener_task = asyncio.create_task(self._listen())

    async def close(self) -> None:
        """Stop listener and close Redis connection."""
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.close()
        if self._redis:
            await self._redis.close()

    def subscribe(self, event_type: str, callback: Callable[..., Any]) -> str:
        """Register a local callback. Also subscribes to Redis channel."""
        sub_id = f"rsub_{self._counter}"
        self._counter += 1
        is_first = event_type not in self._subscribers or not self._subscribers[event_type]
        self._subscribers.setdefault(event_type, {})[sub_id] = callback

        # Subscribe to Redis channel if first local subscriber for this type
        if is_first and self._pubsub is not None:
            channel = f"{self._prefix}:{event_type}"
            asyncio.ensure_future(self._pubsub.subscribe(channel))

        return sub_id

    def unsubscribe(self, subscription_id: str) -> None:
        """Remove a local callback. Unsubscribes from Redis if last."""
        for event_type, subs in self._subscribers.items():
            if subscription_id in subs:
                del subs[subscription_id]
                if not subs and self._pubsub is not None:
                    channel = f"{self._prefix}:{event_type}"
                    asyncio.ensure_future(self._pubsub.unsubscribe(channel))
                break

    async def emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit event: dispatch locally + publish to Redis channel."""
        # Local dispatch (fire-and-forget)
        await self._dispatch_local(event_type, data)

        # Publish to Redis for cross-process subscribers
        if self._redis is not None:
            channel = f"{self._prefix}:{event_type}"
            payload = json.dumps({
                "type": event_type, "data": data, "_origin": self._origin_id,
            })
            await self._redis.publish(channel, payload)

    async def _dispatch_local(self, event_type: str, data: dict[str, Any]) -> None:
        """Invoke all local callbacks for an event type."""
        for cb in list(self._subscribers.get(event_type, {}).values()):
            try:
                result = cb(data)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # noqa: BLE001
                pass  # fire-and-forget

    async def _listen(self) -> None:
        """Background task: listen for Redis messages and dispatch locally."""
        if self._pubsub is None:
            return
        try:
            async for message in self._pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    payload = json.loads(message["data"])
                    if payload.get("_origin") == self._origin_id:
                        continue  # skip own messages — already dispatched locally
                    event_type = payload["type"]
                    data = payload["data"]
                    await self._dispatch_local(event_type, data)
                except (json.JSONDecodeError, KeyError):
                    pass
        except asyncio.CancelledError:
            pass
