"""Tests for ClaudeCodeRuntime - obertka SDK pod AgentRuntime v1."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
from cognitia.runtime.claude_code import ClaudeCodeRuntime
from cognitia.runtime.types import Message, RuntimeEvent

# ---------------------------------------------------------------------------
# Fake StreamEvent (sovmestim with cognitia.runtime.adapter.StreamEvent)
# ---------------------------------------------------------------------------


@dataclass
class FakeStreamEvent:
    """Mock StreamEvent for testirovaniya without SDK."""

    type: str
    text: str = ""
    tool_name: str = ""
    tool_input: dict[str, Any] | None = None
    tool_result: str = ""
    correlation_id: str = ""
    tool_error: bool = False
    is_final: bool = False
    session_id: str | None = None
    total_cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    structured_output: Any = None


# ---------------------------------------------------------------------------
# Fake RuntimeAdapter
# ---------------------------------------------------------------------------


class FakeAdapter:
    """Mock RuntimeAdapter for testov."""

    def __init__(
        self,
        events: list[FakeStreamEvent] | None = None,
        connected: bool = True,
    ) -> None:
        self._events = events or []
        self._connected = connected
        self._disconnected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def stream_reply(self, user_text: str) -> AsyncIterator[FakeStreamEvent]:
        for e in self._events:
            yield e

    async def disconnect(self) -> None:
        self._connected = False
        self._disconnected = True


# ---------------------------------------------------------------------------
# Helper for sbora sobytiy
# ---------------------------------------------------------------------------


async def collect_events(runtime: ClaudeCodeRuntime, messages: list[Message]) -> list[RuntimeEvent]:
    events = []
    async for ev in runtime.run(
        messages=messages,
        system_prompt="test prompt",
        active_tools=[],
    ):
        events.append(ev)
    return events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestClaudeCodeRuntimeBasic:
    """Basic scenarios ClaudeCodeRuntime."""

    @pytest.mark.asyncio
    async def test_no_adapter_yields_error(self) -> None:
        """Without adapter -> error event."""
        runtime = ClaudeCodeRuntime()
        events = await collect_events(runtime, [Message(role="user", content="hi")])

        assert len(events) == 1
        assert events[0].type == "error"
        assert "не инициализирован" in events[0].data["message"]

    @pytest.mark.asyncio
    async def test_not_connected_yields_error(self) -> None:
        """Adapter not connected -> error event."""
        adapter = FakeAdapter(connected=False)
        runtime = ClaudeCodeRuntime(adapter=adapter)
        events = await collect_events(runtime, [Message(role="user", content="hi")])

        assert len(events) == 1
        assert events[0].type == "error"
        assert "не подключён" in events[0].data["message"]

    @pytest.mark.asyncio
    async def test_no_user_message_yields_error(self) -> None:
        """Nott user message -> error event."""
        adapter = FakeAdapter()
        runtime = ClaudeCodeRuntime(adapter=adapter)
        events = await collect_events(
            runtime,
            [Message(role="assistant", content="old")],
        )

        assert len(events) == 1
        assert events[0].type == "error"
        assert "Нет user message" in events[0].data["message"]


class TestClaudeCodeRuntimeStreaming:
    """Striming and conversion sobytiy."""

    @pytest.mark.asyncio
    async def test_text_stream_to_final(self) -> None:
        """text_delta -> assistant_delta; done -> final with full_text."""
        adapter = FakeAdapter(
            events=[
                FakeStreamEvent(type="text_delta", text="Привет"),
                FakeStreamEvent(type="text_delta", text=", мир!"),
                FakeStreamEvent(
                    type="done",
                    text="Привет, мир!",
                    is_final=True,
                    session_id="sess-1",
                    total_cost_usd=0.2,
                    usage={"input_tokens": 10, "output_tokens": 5},
                    structured_output={"answer": "Привет, мир!"},
                ),
            ]
        )
        runtime = ClaudeCodeRuntime(adapter=adapter)
        events = await collect_events(runtime, [Message(role="user", content="say hi")])

        # Should byt: 2x assistant_delta + 1x final (done not probrasyvaetsya)
        types = [e.type for e in events]
        assert types == ["assistant_delta", "assistant_delta", "final"]

        # final contains full tekst
        final = events[-1]
        assert final.data["text"] == "Привет, мир!"
        assert len(final.data["new_messages"]) == 1
        assert final.data["new_messages"][0]["role"] == "assistant"
        assert final.data["new_messages"][0]["content"] == "Привет, мир!"
        assert final.data["session_id"] == "sess-1"
        assert final.data["total_cost_usd"] == 0.2
        assert final.data["usage"] == {"input_tokens": 10, "output_tokens": 5}
        assert final.data["structured_output"] == {"answer": "Привет, мир!"}

    @pytest.mark.asyncio
    async def test_tool_events_converted(self) -> None:
        """tool_use_start/result are converted pravilno."""
        adapter = FakeAdapter(
            events=[
                FakeStreamEvent(
                    type="tool_use_start",
                    tool_name="mcp__iss__get_bonds",
                    tool_input={"q": "obligs"},
                ),
                FakeStreamEvent(
                    type="tool_use_result",
                    tool_name="mcp__iss__get_bonds",
                    tool_result="found 5 bonds",
                    correlation_id="tool-7",
                    tool_error=True,
                ),
                FakeStreamEvent(type="text_delta", text="Результат"),
                FakeStreamEvent(type="done", text="Результат", is_final=True),
            ]
        )
        runtime = ClaudeCodeRuntime(adapter=adapter)
        events = await collect_events(runtime, [Message(role="user", content="bonds")])

        types = [e.type for e in events]
        assert "tool_call_started" in types
        assert "tool_call_finished" in types
        assert "final" in types

        # tool_call_started
        started = next(e for e in events if e.type == "tool_call_started")
        assert started.data["name"] == "mcp__iss__get_bonds"
        assert started.data["args"] == {"q": "obligs"}
        finished = next(e for e in events if e.type == "tool_call_finished")
        assert finished.data["name"] == "mcp__iss__get_bonds"
        assert finished.data["correlation_id"] == "tool-7"
        assert finished.data["ok"] is False
        assert finished.data["result_summary"] == "found 5 bonds"

        # metrics
        final = events[-1]
        assert final.data["metrics"]["tool_calls_count"] == 1

    @pytest.mark.asyncio
    async def test_error_event_forwarded(self) -> None:
        """SDK error → RuntimeEvent error."""
        adapter = FakeAdapter(
            events=[
                FakeStreamEvent(type="error", text="SDK crash"),
            ]
        )
        runtime = ClaudeCodeRuntime(adapter=adapter)
        events = await collect_events(runtime, [Message(role="user", content="x")])

        assert [event.type for event in events] == ["error"]
        assert "SDK crash" in events[0].data["message"]

    @pytest.mark.asyncio
    async def test_extracts_last_user_message(self) -> None:
        """Ispolzuet poslednote user message from history."""
        adapter = FakeAdapter(
            events=[
                FakeStreamEvent(type="text_delta", text="OK"),
                FakeStreamEvent(type="done", text="OK", is_final=True),
            ]
        )
        runtime = ClaudeCodeRuntime(adapter=adapter)

        messages = [
            Message(role="user", content="old"),
            Message(role="assistant", content="reply"),
            Message(role="user", content="latest"),
        ]
        events = await collect_events(runtime, messages)
        final = events[-1]
        assert final.type == "final"


class TestClaudeCodeRuntimeCleanup:
    """Cleanup/lifecycle."""

    @pytest.mark.asyncio
    async def test_cleanup_disconnects(self) -> None:
        """cleanup() vyzyvaet adapter.disconnect()."""
        adapter = FakeAdapter()
        runtime = ClaudeCodeRuntime(adapter=adapter)
        await runtime.cleanup()
        assert adapter._disconnected is True

    @pytest.mark.asyncio
    async def test_cleanup_without_adapter(self) -> None:
        """cleanup() without adapter - not fails."""
        runtime = ClaudeCodeRuntime()
        await runtime.cleanup()  # not should brosit


class TestClaudeCodeRuntimeConvert:
    """Tests _convert_event."""

    def test_unknown_type_becomes_status(self) -> None:
        """Notizvestnyy tip -> status."""
        event = FakeStreamEvent(type="unknown_type", text="something")
        result = ClaudeCodeRuntime._convert_event(event)
        assert result is not None
        assert result.type == "status"
        assert result.data["text"] == "something"

    def test_done_returns_none(self) -> None:
        """done -> None (formiruem final sami)."""
        event = FakeStreamEvent(type="done")
        result = ClaudeCodeRuntime._convert_event(event)
        assert result is None
