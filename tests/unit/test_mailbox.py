"""Tests for the frozen Mailbox (H6 supervisor-orchestrator, Task 3, REQ-009).

Covers addressed deliver/drain, immutability, once-only drain semantics
(via `without`), and delivery order. TDD: written before the
implementation exists. No live LLM, no network.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from swarmline.orchestration.supervisor.mailbox import Mailbox, OutboxMessage


def test_mailbox_deliver_then_drain_for_recipient() -> None:
    mb2 = Mailbox().deliver("w1", "do X")

    msgs = mb2.drain("w1")

    assert msgs == (OutboxMessage(to="w1", content="do X"),)
    # Addressed: another recipient gets nothing.
    assert mb2.drain("w2") == ()
    # The original/empty mailbox is unaffected by the deliver call.
    assert Mailbox().drain("w1") == ()
    assert mb2 is not Mailbox()


def test_mailbox_deliver_is_immutable() -> None:
    mb1 = Mailbox()

    mb2 = mb1.deliver("w1", "do X")

    assert mb2 is not mb1
    assert mb1.drain("w1") == ()


def test_mailbox_without_clears_recipient_queue() -> None:
    mb = Mailbox().deliver("w1", "do X").deliver("w2", "do Y")

    cleared = mb.without("w1")

    assert cleared.drain("w1") == ()
    # A different recipient's queue is untouched.
    assert cleared.drain("w2") == (OutboxMessage(to="w2", content="do Y"),)


def test_mailbox_preserves_delivery_order() -> None:
    mb = Mailbox().deliver("w1", "first").deliver("w1", "second")

    assert mb.drain("w1") == (
        OutboxMessage(to="w1", content="first"),
        OutboxMessage(to="w1", content="second"),
    )


def test_mailbox_frozen() -> None:
    mb = Mailbox()

    with pytest.raises(FrozenInstanceError):
        mb.messages = (OutboxMessage(to="w1", content="x"),)  # type: ignore[misc]


def test_mailbox_construction_detaches_from_caller_list() -> None:
    src = [OutboxMessage(to="w1", content="a")]

    mb = Mailbox(messages=src)  # type: ignore[arg-type]
    src.append(OutboxMessage(to="w1", content="b"))

    assert isinstance(mb.messages, tuple)
    # Post-construction mutation of the caller's list must NOT leak into
    # the "frozen" mailbox — construction must copy/detach, not alias.
    assert mb.drain("w1") == (OutboxMessage(to="w1", content="a"),)
