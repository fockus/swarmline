"""CooldownStatePort protocol and InMemoryCooldownState reference implementation.

No hermes attribution: the cooldown design originates in the taskloom application
layer and is ported to swarmline as a generic, product-free implementation.
No product coupling — stdlib only; keyed by plain ``str`` scope_id.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

__all__ = [
    "CooldownStatePort",
    "InMemoryCooldownState",
]


@runtime_checkable
class CooldownStatePort(Protocol):
    """Per-scope provider cooldown state port (ISP: 3 methods).

    Keyed by ``(scope_id, provider_key)``; ``provider_key`` is the normalised
    (lowercased) provider name.
    """

    def is_in_cooldown(self, scope_id: str, provider_key: str, now: datetime) -> bool:
        """Return True iff the provider is still within its cooldown window."""
        ...

    def set_cooldown(
        self, scope_id: str, provider_key: str, expires_at: datetime
    ) -> None:
        """Record a cooldown expiry for the given scope + provider."""
        ...

    def clear_cooldown(self, scope_id: str, provider_key: str) -> None:
        """Remove any cooldown for the given scope + provider (noop if absent)."""
        ...


class InMemoryCooldownState:
    """Reference in-memory CooldownStatePort implementation.

    Single-process only; replace with a Redis/Postgres adapter for distributed
    deployments.  Keyed by ``(scope_id, provider_key)`` → expiry unix timestamp.
    """

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], float] = {}

    def is_in_cooldown(self, scope_id: str, provider_key: str, now: datetime) -> bool:
        expires = self._store.get((scope_id, provider_key), 0.0)
        return expires > now.timestamp()

    def set_cooldown(
        self, scope_id: str, provider_key: str, expires_at: datetime
    ) -> None:
        self._store[(scope_id, provider_key)] = expires_at.timestamp()

    def clear_cooldown(self, scope_id: str, provider_key: str) -> None:
        self._store.pop((scope_id, provider_key), None)
