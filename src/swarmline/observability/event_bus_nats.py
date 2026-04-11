"""NATS-backed EventBus — distributed pub/sub via NATS Core.

Local subscribers are called directly (same as InMemory).
Cross-process subscribers receive events via NATS subjects.
Requires ``nats-py`` (lazy import).

Usage::

    from swarmline.observability.event_bus_nats import NatsEventBus

    bus = NatsEventBus(nats_url="nats://my-nats:4222")
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


class NatsEventBus:
    """EventBus backed by NATS for distributed eventing.

    - Local callbacks are invoked directly (fire-and-forget, same as InMemory).
    - Events are published to NATS subject ``swarmline.{event_type}``
      for cross-process distribution.
    - A NATS subscription receives remote events and dispatches to
      local callbacks.
    """

    def __init__(
        self,
        nats_url: str,
        *,
        subject_prefix: str = "swarmline",
    ) -> None:
        self._url = nats_url
        self._prefix = subject_prefix
        self._subscribers: dict[str, dict[str, Callable[..., Any]]] = {}
        self._counter = 0
        self._nc: Any = None
        self._nats_subs: dict[str, Any] = {}  # event_type -> NATS subscription
        self._origin_id: str = uuid.uuid4().hex[:12]

    async def connect(self) -> None:
        """Initialize NATS connection."""
        try:
            import nats
        except ImportError as exc:
            raise ImportError(
                "nats-py package required: pip install 'swarmline[nats]' "
                "or pip install nats-py"
            ) from exc

        self._nc = await nats.connect(self._url)

    async def close(self) -> None:
        """Unsubscribe all and close NATS connection."""
        for sub in self._nats_subs.values():
            await sub.unsubscribe()
        self._nats_subs.clear()
        if self._nc and not self._nc.is_closed:
            await self._nc.drain()

    def subscribe(self, event_type: str, callback: Callable[..., Any]) -> str:
        """Register a local callback. Also subscribes to NATS subject."""
        sub_id = f"nsub_{self._counter}"
        self._counter += 1
        is_first = event_type not in self._subscribers or not self._subscribers[event_type]
        self._subscribers.setdefault(event_type, {})[sub_id] = callback

        if is_first and self._nc is not None:
            asyncio.ensure_future(self._subscribe_nats(event_type))

        return sub_id

    def unsubscribe(self, subscription_id: str) -> None:
        """Remove a local callback. Unsubscribes from NATS if last."""
        for event_type, subs in self._subscribers.items():
            if subscription_id in subs:
                del subs[subscription_id]
                if not subs and event_type in self._nats_subs:
                    asyncio.ensure_future(self._unsubscribe_nats(event_type))
                break

    async def emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit event: dispatch locally + publish to NATS subject."""
        await self._dispatch_local(event_type, data)

        if self._nc is not None and not self._nc.is_closed:
            subject = f"{self._prefix}.{event_type}"
            payload = json.dumps({
                "type": event_type, "data": data, "_origin": self._origin_id,
            }).encode()
            await self._nc.publish(subject, payload)

    async def _dispatch_local(self, event_type: str, data: dict[str, Any]) -> None:
        """Invoke all local callbacks for an event type."""
        for cb in list(self._subscribers.get(event_type, {}).values()):
            try:
                result = cb(data)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # noqa: BLE001
                pass

    async def _subscribe_nats(self, event_type: str) -> None:
        """Subscribe to a NATS subject for an event type."""
        if self._nc is None or self._nc.is_closed:
            return
        subject = f"{self._prefix}.{event_type}"

        async def handler(msg: Any) -> None:
            try:
                payload = json.loads(msg.data.decode())
                if payload.get("_origin") == self._origin_id:
                    return  # skip own messages — already dispatched locally
                await self._dispatch_local(payload["type"], payload["data"])
            except (json.JSONDecodeError, KeyError):
                pass

        sub = await self._nc.subscribe(subject, cb=handler)
        self._nats_subs[event_type] = sub

    async def _unsubscribe_nats(self, event_type: str) -> None:
        """Unsubscribe from a NATS subject."""
        sub = self._nats_subs.pop(event_type, None)
        if sub:
            await sub.unsubscribe()
