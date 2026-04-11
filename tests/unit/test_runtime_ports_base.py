"""Unit: convert_event / StreamEvent for BaseRuntimePort."""

from __future__ import annotations

from swarmline.runtime.ports.base import convert_event
from swarmline.runtime.types import RuntimeEvent


def test_convert_event_maps_approval_required() -> None:
    event = RuntimeEvent.approval_required(
        action_name="edit_file",
        args={"path": "app.py"},
        allowed_decisions=["approve", "reject"],
        interrupt_id="interrupt-1",
        description="Review edit",
    )

    converted = convert_event(event)

    assert converted is not None
    assert converted.type == "approval_required"
    assert converted.text == "Review edit"
    assert converted.tool_name == "edit_file"
    assert converted.tool_input == {"path": "app.py"}
    assert converted.allowed_decisions == ["approve", "reject"]
    assert converted.interrupt_id == "interrupt-1"


def test_convert_event_maps_user_input_requested() -> None:
    event = RuntimeEvent.user_input_requested(
        prompt="Need answer",
        interrupt_id="interrupt-2",
    )

    converted = convert_event(event)

    assert converted is not None
    assert converted.type == "user_input_requested"
    assert converted.text == "Need answer"
    assert converted.interrupt_id == "interrupt-2"


def test_convert_event_maps_native_notice() -> None:
    event = RuntimeEvent.native_notice(
        "Native thread active",
        metadata={"thread_id": "thread-1"},
    )

    converted = convert_event(event)

    assert converted is not None
    assert converted.type == "native_notice"
    assert converted.text == "Native thread active"
    assert converted.native_metadata == {"thread_id": "thread-1"}
