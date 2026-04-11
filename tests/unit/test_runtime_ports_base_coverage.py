"""Coverage tests: BaseRuntimePort + convert_event - vse event types and stream_reply paths."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from swarmline.runtime.ports.base import (
    BaseRuntimePort,
    convert_event,
)
from swarmline.runtime.ports.thin import ThinRuntimePort
from swarmline.runtime.types import Message, RuntimeEvent
from swarmline.agent.tool import tool


# --- convert_event ---


class TestConvertEvent:
    """convert_event mappit vse tipy RuntimeEvent -> StreamEvent."""

    def test_convert_assistant_delta(self) -> None:
        e = RuntimeEvent(type="assistant_delta", data={"text": "hello"})
        result = convert_event(e)
        assert result is not None
        assert result.type == "text_delta"
        assert result.text == "hello"

    def test_convert_status_returns_none(self) -> None:
        e = RuntimeEvent(type="status", data={"state": "running"})
        assert convert_event(e) is None

    def test_convert_tool_call_started(self) -> None:
        e = RuntimeEvent(type="tool_call_started", data={"name": "read", "args": {"p": 1}})
        result = convert_event(e)
        assert result is not None
        assert result.type == "tool_use_start"
        assert result.tool_name == "read"
        assert result.tool_input == {"p": 1}

    def test_convert_tool_call_finished(self) -> None:
        e = RuntimeEvent(
            type="tool_call_finished",
            data={"name": "read", "result_summary": "done"},
        )
        result = convert_event(e)
        assert result is not None
        assert result.type == "tool_use_result"
        assert result.tool_name == "read"
        assert result.tool_result == "done"

    def test_convert_approval_required(self) -> None:
        e = RuntimeEvent(
            type="approval_required",
            data={
                "description": "run cmd",
                "action_name": "execute",
                "args": {"cmd": "ls"},
                "allowed_decisions": ["approve", "deny"],
                "interrupt_id": "int-1",
            },
        )
        result = convert_event(e)
        assert result is not None
        assert result.type == "approval_required"
        assert result.tool_name == "execute"
        assert result.allowed_decisions == ["approve", "deny"]
        assert result.interrupt_id == "int-1"

    def test_convert_user_input_requested(self) -> None:
        e = RuntimeEvent(
            type="user_input_requested",
            data={"prompt": "Enter name", "interrupt_id": "int-2"},
        )
        result = convert_event(e)
        assert result is not None
        assert result.type == "user_input_requested"
        assert result.text == "Enter name"

    def test_convert_native_notice(self) -> None:
        e = RuntimeEvent(
            type="native_notice",
            data={"text": "notice", "metadata": {"k": "v"}},
        )
        result = convert_event(e)
        assert result is not None
        assert result.type == "native_notice"
        assert result.native_metadata == {"k": "v"}

    def test_convert_error(self) -> None:
        e = RuntimeEvent(type="error", data={"message": "boom"})
        result = convert_event(e)
        assert result is not None
        assert result.type == "error"
        assert result.text == "boom"

    def test_convert_final_returns_none(self) -> None:
        e = RuntimeEvent(type="final", data={"text": "final answer"})
        assert convert_event(e) is None

    def test_convert_unknown_returns_none(self) -> None:
        e = RuntimeEvent(type="something_unknown", data={})
        assert convert_event(e) is None


# --- BaseRuntimePort ---


class FakeRuntimePort(BaseRuntimePort):
    """Testovaya implementation BaseRuntimePort."""

    def __init__(
        self,
        events: list[RuntimeEvent] | None = None,
        error: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(system_prompt="test system prompt", **kwargs)
        self._events = events or []
        self._error = error

    async def _run_runtime(
        self, messages: list[Message], system_prompt: str
    ) -> AsyncIterator[RuntimeEvent]:
        if self._error:
            raise self._error
        for e in self._events:
            yield e


class TestBaseRuntimePortConnectDisconnect:
    """connect/disconnect lifecycle."""

    async def test_connect_sets_connected(self) -> None:
        port = FakeRuntimePort()
        assert port.is_connected is False
        await port.connect()
        assert port.is_connected is True

    async def test_disconnect_clears_state(self) -> None:
        port = FakeRuntimePort()
        await port.connect()
        port._append_to_history("user", "hi")
        await port.disconnect()
        assert port.is_connected is False
        assert port._history == []


class TestBaseRuntimePortStreamReply:
    """stream_reply: happy path, not connected, error, final fallback."""

    async def test_stream_reply_not_connected_yields_error(self) -> None:
        port = FakeRuntimePort()
        events = [e async for e in port.stream_reply("hi")]
        assert len(events) == 1
        assert events[0].type == "error"
        assert "not connected" in events[0].text.lower()

    async def test_stream_reply_happy_path(self) -> None:
        port = FakeRuntimePort(events=[
            RuntimeEvent(type="assistant_delta", data={"text": "Hello "}),
            RuntimeEvent(type="assistant_delta", data={"text": "world"}),
            RuntimeEvent(type="final", data={"text": "Hello world"}),
        ])
        await port.connect()
        events = [e async for e in port.stream_reply("hi")]
        text_events = [e for e in events if e.type == "text_delta"]
        done_events = [e for e in events if e.type == "done"]
        assert len(text_events) == 2
        assert len(done_events) == 1
        assert done_events[0].text == "Hello world"
        assert done_events[0].is_final is True

    async def test_stream_reply_final_fallback(self) -> None:
        port = FakeRuntimePort(events=[
            RuntimeEvent(type="final", data={"text": "final answer"}),
        ])
        await port.connect()
        events = [e async for e in port.stream_reply("hi")]
        text_events = [e for e in events if e.type == "text_delta"]
        assert len(text_events) == 1
        assert text_events[0].text == "final answer"

    async def test_stream_reply_silent_eof_yields_error(self) -> None:
        port = FakeRuntimePort(events=[])
        await port.connect()
        events = [e async for e in port.stream_reply("hi")]
        assert [event.type for event in events] == ["error"]
        assert "without final" in events[0].text.lower()

    async def test_stream_reply_runtime_error(self) -> None:
        port = FakeRuntimePort(error=RuntimeError("connection lost"))
        await port.connect()
        events = [e async for e in port.stream_reply("hi")]
        error_events = [e for e in events if e.type == "error"]
        assert len(error_events) == 1
        assert "connection lost" in error_events[0].text

    async def test_stream_reply_appends_history(self) -> None:
        port = FakeRuntimePort(events=[
            RuntimeEvent(type="assistant_delta", data={"text": "reply"}),
            RuntimeEvent(type="final", data={"text": "reply"}),
        ])
        await port.connect()
        _ = [e async for e in port.stream_reply("hello")]
        assert len(port._history) == 2
        assert port._history[0].role == "user"
        assert port._history[1].role == "assistant"


class TestBaseRuntimePortHistory:
    """Sliding window and summarization."""

    async def test_history_sliding_window(self) -> None:
        port = FakeRuntimePort(history_max=3)
        for i in range(5):
            port._append_to_history("user", f"msg-{i}")
        assert len(port._history) == 3
        assert port._history[0].content == "msg-2"

    async def test_build_system_prompt_no_summary(self) -> None:
        port = FakeRuntimePort()
        assert port._build_system_prompt() == "test system prompt"

    async def test_build_system_prompt_with_summary(self) -> None:
        port = FakeRuntimePort()
        port._rolling_summary = "Previously discussed X"
        prompt = port._build_system_prompt()
        assert "Previously discussed X" in prompt
        assert "test system prompt" in prompt

    async def test_maybe_summarize_no_summarizer(self) -> None:
        port = FakeRuntimePort(history_max=2)
        port._append_to_history("user", "a")
        port._append_to_history("assistant", "b")
        await port._maybe_summarize()
        assert port._rolling_summary == ""

    async def test_maybe_summarize_below_max(self) -> None:
        class FakeSummarizer:
            async def asummarize(self, msgs: Any) -> str:
                return "summary"

        port = FakeRuntimePort(history_max=10, summarizer=FakeSummarizer())
        port._append_to_history("user", "a")
        await port._maybe_summarize()
        assert port._rolling_summary == ""

    async def test_maybe_summarize_with_async_summarizer(self) -> None:
        class FakeSummarizer:
            async def asummarize(self, msgs: Any) -> str:
                return "async summary"

        port = FakeRuntimePort(history_max=2, summarizer=FakeSummarizer())
        port._append_to_history("user", "a")
        port._append_to_history("assistant", "b")
        await port._maybe_summarize()
        assert port._rolling_summary == "async summary"

    async def test_maybe_summarize_with_sync_summarizer(self) -> None:
        class FakeSyncSummarizer:
            def summarize(self, msgs: Any) -> str:
                return "sync summary"

        port = FakeRuntimePort(history_max=2, summarizer=FakeSyncSummarizer())
        port._append_to_history("user", "a")
        port._append_to_history("assistant", "b")
        await port._maybe_summarize()
        assert port._rolling_summary == "sync summary"

    async def test_maybe_summarize_error_handled(self) -> None:
        class BrokenSummarizer:
            async def asummarize(self, msgs: Any) -> str:
                raise ValueError("boom")

        port = FakeRuntimePort(history_max=2, summarizer=BrokenSummarizer())
        port._append_to_history("user", "a")
        port._append_to_history("assistant", "b")
        await port._maybe_summarize()
        assert port._rolling_summary == ""


class _FakeThinRuntime:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run(self, **kwargs: Any):
        self.calls.append(kwargs)
        yield RuntimeEvent.final("ok")


class TestThinRuntimePort:
    """ThinRuntimePort should peredavat advertised tools in runtime."""

    async def test_run_runtime_forwards_local_tools_as_active_tools(self) -> None:
        @tool("calc", "Add numbers")
        def calc(a: int, b: int) -> int:
            return a + b

        port = ThinRuntimePort(
            system_prompt="system prompt",
            local_tools={"calc": calc},
        )
        fake_runtime = _FakeThinRuntime()
        port._runtime = fake_runtime

        events = [
            event
            async for event in port._run_runtime(
                messages=[Message(role="user", content="compute")],
                system_prompt="system prompt",
            )
        ]

        assert [event.type for event in events] == ["final"]
        assert len(fake_runtime.calls) == 1
        assert [spec.name for spec in fake_runtime.calls[0]["active_tools"]] == ["calc"]
