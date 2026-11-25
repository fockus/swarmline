"""Contract tests for swarmline.graph.commands (Epic D, Stage D1.2).

Covers the `Command` / `Send` value objects, the `END` / `START` sentinels,
and the `GraphConfigError` / `GraphRecursionError` exception types.
"""

from __future__ import annotations

import dataclasses

from swarmline.errors import SwarmlineError
from swarmline.graph.commands import (
    END,
    START,
    Command,
    GraphConfigError,
    GraphRecursionError,
    Send,
)
from swarmline.orchestration.workflow_graph import END_NODE


class TestCommand:
    def test_command_defaults_are_none(self) -> None:
        command = Command()

        assert command.update is None
        assert command.goto is None

    def test_command_is_frozen(self) -> None:
        command = Command()

        try:
            command.update = {"x": 1}  # type: ignore[misc]
        except dataclasses.FrozenInstanceError:
            pass
        else:
            raise AssertionError("expected Command to be frozen (immutable)")

    def test_command_accepts_update_and_goto(self) -> None:
        command = Command(update={"count": 1}, goto="next_node")

        assert command.update == {"count": 1}
        assert command.goto == "next_node"

    def test_command_accepts_goto_end_sentinel(self) -> None:
        command = Command(goto=END)

        assert command.goto is END

    def test_command_accepts_goto_list_of_send(self) -> None:
        sends = [Send(node="fan_out", payload={"i": 1})]
        command = Command(goto=sends)

        assert command.goto == sends


class TestSend:
    def test_send_carries_node_and_payload(self) -> None:
        send = Send(node="worker", payload={"item": 42})

        assert send.node == "worker"
        assert send.payload == {"item": 42}

    def test_send_is_frozen(self) -> None:
        send = Send(node="worker", payload={"item": 42})

        try:
            send.node = "other"  # type: ignore[misc]
        except dataclasses.FrozenInstanceError:
            pass
        else:
            raise AssertionError("expected Send to be frozen (immutable)")


class TestSentinels:
    def test_end_and_start_are_distinct_singletons(self) -> None:
        assert END is not START
        assert END is END
        assert START is START

    def test_end_value_interops_with_workflow_graph_end_node(self) -> None:
        assert END.value == "__end__"
        assert END.value == END_NODE

    def test_start_has_a_distinct_value(self) -> None:
        assert START.value == "__start__"
        assert START.value != END.value

    def test_sentinel_repr_is_readable(self) -> None:
        assert "END" in repr(END)
        assert "START" in repr(START)


class TestGraphErrors:
    def test_graph_errors_subclass_swarmline_error(self) -> None:
        assert issubclass(GraphConfigError, SwarmlineError)
        assert issubclass(GraphRecursionError, SwarmlineError)

    def test_graph_config_error_is_raisable_with_message(self) -> None:
        try:
            raise GraphConfigError("bad config")
        except SwarmlineError as exc:
            assert "bad config" in str(exc)

    def test_graph_recursion_error_is_raisable_with_message(self) -> None:
        try:
            raise GraphRecursionError("recursion limit exceeded")
        except SwarmlineError as exc:
            assert "recursion limit exceeded" in str(exc)
