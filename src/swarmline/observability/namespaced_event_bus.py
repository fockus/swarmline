"""NamespacedEventBus — event bus with namespace:event_type pattern matching.

Routes events via 'namespace:event_type' patterns with wildcard support:
- "ns:event" — exact match
- "ns:*" — all events in namespace
- "*:event" — event across all namespaces
- "*:*" — global catch-all for namespaced events
- "plain" — non-namespaced exact match (no pattern matching)
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable


class NamespacedEventBus:
    """Event bus with namespace-scoped routing and wildcard pattern matching.

    Satisfies the EventBus Protocol (subscribe/unsubscribe/emit).
    Fire-and-forget: exceptions in callbacks are silently swallowed.
    Supports both sync and async callbacks.
    """

    def __init__(self) -> None:
        self._exact_subs: dict[str, dict[str, Callable[..., Any]]] = {}
        self._pattern_subs: dict[str, dict[str, Callable[..., Any]]] = {}
        self._counter = 0

    def subscribe(self, event_type: str, callback: Callable[..., Any]) -> str:
        """Register a callback for event_type or pattern. Returns subscription ID."""
        sub_id = f"nsub_{self._counter}"
        self._counter += 1
        if "*" in event_type:
            self._pattern_subs.setdefault(event_type, {})[sub_id] = callback
        else:
            self._exact_subs.setdefault(event_type, {})[sub_id] = callback
        return sub_id

    def unsubscribe(self, subscription_id: str) -> None:
        """Remove a subscription by ID. No-op if ID not found."""
        for subs in self._exact_subs.values():
            subs.pop(subscription_id, None)
        for subs in self._pattern_subs.values():
            subs.pop(subscription_id, None)

    async def emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event. Matches exact subscribers and wildcard patterns."""
        callbacks: list[Callable[..., Any]] = []

        # Exact matches always fire
        callbacks.extend(self._exact_subs.get(event_type, {}).values())

        # Pattern matching only for namespaced events (contains ':')
        if ":" in event_type:
            ns, evt = event_type.split(":", 1)
            for pattern, subs in self._pattern_subs.items():
                p_ns, p_evt = pattern.split(":", 1)
                if (p_ns == "*" or p_ns == ns) and (p_evt == "*" or p_evt == evt):
                    callbacks.extend(subs.values())

        for cb in list(callbacks):
            try:
                result = cb(data)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # noqa: BLE001
                pass  # fire-and-forget
