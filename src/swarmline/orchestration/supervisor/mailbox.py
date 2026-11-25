"""Mailbox — frozen addressed message-passing artifact (REQ-009).

H6 supervisor-orchestrator, Task 3. Message-passing so the supervisor can
correct workers mid-run: `send_message` (tools.py) delivers into the
mailbox, and workers (or `SupervisorState.drain_for`) drain their own
addressed queue.

`OutboxMessage` lives here (not in `state.py`) so `state.py` can import it
from `mailbox.py` without creating a `state → mailbox → state` cycle — the
Task-2 stub defined it in `state.py`; Task 3 relocates it as the natural
mailbox message type instead of inventing a parallel `Message` type.

Immutable, mirrors `Blackboard.with_patch`: every mutator returns a NEW
`Mailbox` instance, the receiver is never mutated in place. Delivery is
addressed (`OutboxMessage.to`) and once-only at the `SupervisorState` layer
via `drain` + `without` applied together (`SupervisorState.drain_for`) —
`drain` alone is a pure read and leaves the mailbox unchanged, matching the
`design.md` interface exactly (`deliver`/`drain`).

Kept import-light on purpose (I-020): stdlib only, mirrors the rest of
`orchestration/supervisor/`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OutboxMessage:
    """A single addressed message queued by `send_message` / `Mailbox.deliver`."""

    to: str
    content: str


@dataclass(frozen=True)
class Mailbox:
    """Addressed, immutable message queue keyed by recipient (REQ-009).

    Storage is a single flat tuple filtered by `OutboxMessage.to` on read —
    simplest correct representation that still preserves per-recipient
    delivery order (append-only, never reordered).
    """

    messages: tuple[OutboxMessage, ...] = ()

    def __post_init__(self) -> None:
        """Detach/normalize `messages` so callers can't mutate the snapshot.

        Mirrors `Blackboard.__post_init__`: `tuple(self.messages)` both
        COPIES a caller-supplied list (breaking the alias, so later
        `list.append` calls on the caller's object don't leak into this
        "frozen" mailbox) and enforces the immutable-tuple type. The
        already-a-tuple default (`()`) round-trips unchanged.
        """
        object.__setattr__(self, "messages", tuple(self.messages))

    def deliver(self, to: str, content: str) -> Mailbox:
        """Return a NEW Mailbox with `content` queued for `to`.

        The original Mailbox is never mutated — mirrors
        `Blackboard.with_patch`'s immutable-rebuild style.
        """
        return Mailbox(messages=(*self.messages, OutboxMessage(to=to, content=content)))

    def drain(self, for_: str) -> tuple[OutboxMessage, ...]:
        """Return `for_`'s queued messages in delivery order.

        Pure read — does NOT remove the messages from this Mailbox. Messages
        addressed to other recipients are never returned. Call `without`
        (or `SupervisorState.drain_for`) to clear `for_`'s queue after
        reading, achieving once-only delivery.
        """
        return tuple(msg for msg in self.messages if msg.to == for_)

    def without(self, for_: str) -> Mailbox:
        """Return a NEW Mailbox with `for_`'s queue emptied.

        Other recipients' queues are untouched. Combined with `drain`
        (typically at the `SupervisorState` layer) this gives once-only
        delivery despite `Mailbox` being frozen.
        """
        return Mailbox(messages=tuple(msg for msg in self.messages if msg.to != for_))
