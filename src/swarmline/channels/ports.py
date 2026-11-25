"""Channel abstraction protocols (ports).

All three protocols carry zero framework dependencies — they reference only
:mod:`swarmline.channels.envelopes` (stdlib dataclasses) and are therefore
safe to import in domain or application layers.

Generalised from:
    taskloom.application.ports.integrations
    (src/taskloom/application/ports/integrations.py:55-88)
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from swarmline.channels.envelopes import IncomingMessage, OutgoingMessage


@runtime_checkable
class ChannelAdapterPort(Protocol):
    """Contract for a single-channel transport adapter.

    Each concrete adapter handles one channel type (Telegram, web, Slack …).
    Implementations live in the product/infrastructure layer; swarmline only
    defines the protocol so application code can depend on the abstraction.

    ISP: 3 methods (≤ 5).
    """

    async def normalize(self, raw: dict[str, object]) -> IncomingMessage:
        """Deserialise a raw channel payload into a generic :class:`IncomingMessage`."""
        ...

    async def send(self, msg: OutgoingMessage) -> dict[str, object]:
        """Deliver an :class:`OutgoingMessage` via the transport.

        Returns a dict with at least a ``"status"`` key so callers can log the
        outcome without depending on adapter internals.
        """
        ...

    async def healthcheck(self) -> dict[str, object]:
        """Return a liveness/readiness dict for the channel transport.

        Typical return: ``{"channel": "telegram", "status": "ok"}``.
        """
        ...


@runtime_checkable
class ChannelRegistryPort(Protocol):
    """Contract for a registry that maps channel names to adapters.

    Keeping this as a Protocol lets application code depend on the interface
    without importing the concrete :class:`~swarmline.channels.registry.ChannelRegistry`.

    ISP: 4 methods (≤ 5).
    """

    def register(self, name: str, adapter: ChannelAdapterPort) -> None:
        """Register *adapter* under *name*.  Overwrites any existing entry."""
        ...

    def unregister(self, name: str) -> None:
        """Remove the adapter registered under *name*.

        Raises:
            KeyError: if *name* is not registered.
        """
        ...

    def get(self, name: str) -> ChannelAdapterPort:
        """Return the adapter registered under *name*.

        Raises:
            KeyError: if *name* is not registered.
        """
        ...

    def list_channels(self) -> list[str]:
        """Return a list of all registered channel names."""
        ...


@runtime_checkable
class GatewayPort(Protocol):
    """Contract for the channel gateway that dispatches incoming events.

    Generalized from ``taskloom.application.ports.integrations.GatewayPort``.
    The gateway is the single entry-point that routes an
    :class:`IncomingMessage` to the appropriate downstream handler.

    ISP: 1 method (≤ 5).
    """

    async def dispatch_event(self, event: IncomingMessage) -> dict[str, object]:
        """Route *event* to the appropriate handler.

        Returns a dict describing the dispatch outcome.
        """
        ...
