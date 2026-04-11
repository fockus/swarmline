"""EventBus — publish-subscribe event bus for runtime events.

Provides:
- EventBus: Protocol defining the pub-sub contract.
- InMemoryEventBus: Default fire-and-forget implementation.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Protocol, runtime_checkable


@runtime_checkable
class EventBus(Protocol):
    """Publish-subscribe event bus for runtime events."""

    def subscribe(self, event_type: str, callback: Callable[..., Any]) -> str:
        """Register a callback for event_type. Returns subscription ID."""
        ...

    def unsubscribe(self, subscription_id: str) -> None:
        """Remove a subscription by ID."""
        ...

    async def emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event to all subscribers of event_type."""
        ...


class InMemoryEventBus:
    """Default event bus -- fire-and-forget async callbacks.

    Callbacks that raise exceptions are silently ignored (fire-and-forget).
    Supports both sync and async callbacks.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, dict[str, Callable[..., Any]]] = {}
        self._counter = 0

    def subscribe(self, event_type: str, callback: Callable[..., Any]) -> str:
        """Register a callback for event_type. Returns unique subscription ID."""
        sub_id = f"sub_{self._counter}"
        self._counter += 1
        self._subscribers.setdefault(event_type, {})[sub_id] = callback
        return sub_id

    def unsubscribe(self, subscription_id: str) -> None:
        """Remove a subscription by ID. No-op if ID not found."""
        for subs in self._subscribers.values():
            subs.pop(subscription_id, None)

    async def emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event to all subscribers. Errors in callbacks are swallowed."""
        for cb in list(self._subscribers.get(event_type, {}).values()):
            try:
                result = cb(data)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # noqa: BLE001
                pass  # fire-and-forget
