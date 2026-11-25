"""Generic channel message envelopes.

All id fields are plain :class:`str` — no product-layer typed ids.
These dataclasses form the boundary between a channel adapter and
the rest of the application; they intentionally carry zero framework
dependencies (stdlib only).

Generalised from:
    taskloom.shared.channel  (src/taskloom/shared/channel.py)
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class IncomingMessage:
    """An inbound message received from an external channel.

    Args:
        channel_id: Identifier for the channel that received this message
            (e.g. ``"telegram"``, ``"web"``, ``"slack"``).
        sender_id: Identifier of the sender within the channel
            (plain string — no product-layer type).
        content: Text content of the message.
        conversation_id: Optional conversation/session reference
            (plain string — no product-layer type).
        thread_id: Optional external channel reference such as a chat id,
            thread id, or session id specific to the channel transport.
        metadata: Arbitrary key-value payload (e.g. raw webhook body).
            Stored as an immutable :class:`~types.MappingProxyType`; item
            assignment after construction raises :exc:`TypeError`.
    """

    channel_id: str
    sender_id: str
    content: str
    conversation_id: str | None = None
    thread_id: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # frozen=True blocks __setattr__, so we bypass it with object.__setattr__.
        # dict(self.metadata) copies the caller's dict so external mutation
        # cannot reach the stored value; MappingProxyType makes it read-only.
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class OutgoingMessage:
    """An outbound message to be delivered via a channel adapter.

    Args:
        channel_id: Target channel identifier.
        content: Text content to send.
        conversation_id: Optional conversation reference.
        thread_id: Optional external channel reference (e.g. chat id).
        metadata: Arbitrary key-value payload (e.g. formatting hints).
            Stored as an immutable :class:`~types.MappingProxyType`; item
            assignment after construction raises :exc:`TypeError`.
    """

    channel_id: str
    content: str
    conversation_id: str | None = None
    thread_id: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
