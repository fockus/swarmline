"""Unit tests: RuntimeEvent typed accessors — text, tool_name, is_final, etc."""

from __future__ import annotations

from swarmline.runtime.types import (
    RuntimeErrorData,
    RuntimeEvent,
)


class TestTextAccessor:
    """RuntimeEvent.text property."""

    def test_assistant_delta_text(self) -> None:
        event = RuntimeEvent.assistant_delta("hello")
        assert event.text == "hello"

    def test_status_text(self) -> None:
        event = RuntimeEvent.status("processing")
        assert event.text == "processing"

    def test_final_text(self) -> None:
        event = RuntimeEvent.final("done answer")
        assert event.text == "done answer"

    def test_error_no_text(self) -> None:
        event = RuntimeEvent.error(
            RuntimeErrorData(kind="runtime_crash", message="boom")
        )
        assert event.text == ""

    def test_tool_call_no_text(self) -> None:
        event = RuntimeEvent.tool_call_started("read_file")
        assert event.text == ""


class TestToolNameAccessor:
    """RuntimeEvent.tool_name property."""

    def test_tool_call_started_name(self) -> None:
        event = RuntimeEvent.tool_call_started("read_file", args={"path": "x"})
        assert event.tool_name == "read_file"

    def test_tool_call_finished_name(self) -> None:
        event = RuntimeEvent.tool_call_finished("write_file", correlation_id="abc")
        assert event.tool_name == "write_file"

    def test_assistant_delta_no_tool_name(self) -> None:
        event = RuntimeEvent.assistant_delta("hi")
        assert event.tool_name == ""


class TestIsFinal:
    """RuntimeEvent.is_final property."""

    def test_final_event_is_final(self) -> None:
        event = RuntimeEvent.final("result")
        assert event.is_final is True

    def test_non_final_not_final(self) -> None:
        event = RuntimeEvent.assistant_delta("hi")
        assert event.is_final is False

    def test_error_not_final(self) -> None:
        event = RuntimeEvent.error(RuntimeErrorData(kind="runtime_crash", message="x"))
        assert event.is_final is False


class TestIsError:
    """RuntimeEvent.is_error property."""

    def test_error_event(self) -> None:
        event = RuntimeEvent.error(RuntimeErrorData(kind="runtime_crash", message="x"))
        assert event.is_error is True

    def test_final_not_error(self) -> None:
        event = RuntimeEvent.final("ok")
        assert event.is_error is False


class TestIsText:
    """RuntimeEvent.is_text property."""

    def test_assistant_delta_is_text(self) -> None:
        event = RuntimeEvent.assistant_delta("chunk")
        assert event.is_text is True

    def test_status_not_text(self) -> None:
        event = RuntimeEvent.status("loading")
        assert event.is_text is False


class TestStructuredOutput:
    """RuntimeEvent.structured_output property."""

    def test_final_with_structured_output(self) -> None:
        event = RuntimeEvent.final("ok", structured_output={"key": "val"})
        assert event.structured_output == {"key": "val"}

    def test_final_without_structured_output(self) -> None:
        event = RuntimeEvent.final("ok")
        assert event.structured_output is None

    def test_non_final_no_structured_output(self) -> None:
        event = RuntimeEvent.assistant_delta("hi")
        assert event.structured_output is None
