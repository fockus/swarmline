"""Тесты для ClaudeCodeRuntime — обёртка SDK под AgentRuntime v1."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest

from cognitia.runtime.claude_code import ClaudeCodeRuntime
from cognitia.runtime.types import Message, RuntimeEvent

# ---------------------------------------------------------------------------
# Фейковый StreamEvent (совместим с cognitia.runtime.adapter.StreamEvent)
# ---------------------------------------------------------------------------

@dataclass
class FakeStreamEvent:
    """Мок StreamEvent для тестирования без SDK."""

    type: str
    text: str = ""
    tool_name: str = ""
    tool_input: dict[str, Any] | None = None
    tool_result: str = ""
    is_final: bool = False


# ---------------------------------------------------------------------------
# Фейковый RuntimeAdapter
# ---------------------------------------------------------------------------

class FakeAdapter:
    """Мок RuntimeAdapter для тестов."""

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
# Хелпер для сбора событий
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
# Тесты
# ---------------------------------------------------------------------------

class TestClaudeCodeRuntimeBasic:
    """Базовые сценарии ClaudeCodeRuntime."""

    @pytest.mark.asyncio
    async def test_no_adapter_yields_error(self) -> None:
        """Без adapter → error event."""
        runtime = ClaudeCodeRuntime()
        events = await collect_events(runtime, [Message(role="user", content="hi")])

        assert len(events) == 1
        assert events[0].type == "error"
        assert "не инициализирован" in events[0].data["message"]

    @pytest.mark.asyncio
    async def test_not_connected_yields_error(self) -> None:
        """Adapter не подключён → error event."""
        adapter = FakeAdapter(connected=False)
        runtime = ClaudeCodeRuntime(adapter=adapter)
        events = await collect_events(runtime, [Message(role="user", content="hi")])

        assert len(events) == 1
        assert events[0].type == "error"
        assert "не подключён" in events[0].data["message"]

    @pytest.mark.asyncio
    async def test_no_user_message_yields_error(self) -> None:
        """Нет user message → error event."""
        adapter = FakeAdapter()
        runtime = ClaudeCodeRuntime(adapter=adapter)
        events = await collect_events(
            runtime, [Message(role="assistant", content="old")],
        )

        assert len(events) == 1
        assert events[0].type == "error"
        assert "Нет user message" in events[0].data["message"]


class TestClaudeCodeRuntimeStreaming:
    """Стриминг и конвертация событий."""

    @pytest.mark.asyncio
    async def test_text_stream_to_final(self) -> None:
        """text_delta → assistant_delta; done → final с full_text."""
        adapter = FakeAdapter(events=[
            FakeStreamEvent(type="text_delta", text="Привет"),
            FakeStreamEvent(type="text_delta", text=", мир!"),
            FakeStreamEvent(type="done", text="Привет, мир!", is_final=True),
        ])
        runtime = ClaudeCodeRuntime(adapter=adapter)
        events = await collect_events(runtime, [Message(role="user", content="say hi")])

        # Должны быть: 2x assistant_delta + 1x final (done не пробрасывается)
        types = [e.type for e in events]
        assert types == ["assistant_delta", "assistant_delta", "final"]

        # final содержит полный текст
        final = events[-1]
        assert final.data["text"] == "Привет, мир!"
        assert len(final.data["new_messages"]) == 1
        assert final.data["new_messages"][0]["role"] == "assistant"
        assert final.data["new_messages"][0]["content"] == "Привет, мир!"

    @pytest.mark.asyncio
    async def test_tool_events_converted(self) -> None:
        """tool_use_start/result конвертируются правильно."""
        adapter = FakeAdapter(events=[
            FakeStreamEvent(
                type="tool_use_start",
                tool_name="mcp__iss__get_bonds",
                tool_input={"q": "obligs"},
            ),
            FakeStreamEvent(
                type="tool_use_result",
                tool_name="mcp__iss__get_bonds",
                tool_result="found 5 bonds",
            ),
            FakeStreamEvent(type="text_delta", text="Результат"),
            FakeStreamEvent(type="done", text="Результат", is_final=True),
        ])
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

        # metrics
        final = events[-1]
        assert final.data["metrics"]["tool_calls_count"] == 1

    @pytest.mark.asyncio
    async def test_error_event_forwarded(self) -> None:
        """SDK error → RuntimeEvent error."""
        adapter = FakeAdapter(events=[
            FakeStreamEvent(type="error", text="SDK crash"),
        ])
        runtime = ClaudeCodeRuntime(adapter=adapter)
        events = await collect_events(runtime, [Message(role="user", content="x")])

        # error + final (пустой)
        errors = [e for e in events if e.type == "error"]
        assert len(errors) == 1
        assert "SDK crash" in errors[0].data["message"]

    @pytest.mark.asyncio
    async def test_extracts_last_user_message(self) -> None:
        """Использует последнее user message из истории."""
        adapter = FakeAdapter(events=[
            FakeStreamEvent(type="text_delta", text="OK"),
            FakeStreamEvent(type="done", text="OK", is_final=True),
        ])
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
        """cleanup() вызывает adapter.disconnect()."""
        adapter = FakeAdapter()
        runtime = ClaudeCodeRuntime(adapter=adapter)
        await runtime.cleanup()
        assert adapter._disconnected is True

    @pytest.mark.asyncio
    async def test_cleanup_without_adapter(self) -> None:
        """cleanup() без adapter — не падает."""
        runtime = ClaudeCodeRuntime()
        await runtime.cleanup()  # не должно бросить


class TestClaudeCodeRuntimeConvert:
    """Тесты _convert_event."""

    def test_unknown_type_becomes_status(self) -> None:
        """Неизвестный тип → status."""
        event = FakeStreamEvent(type="unknown_type", text="something")
        result = ClaudeCodeRuntime._convert_event(event)
        assert result is not None
        assert result.type == "status"
        assert result.data["text"] == "something"

    def test_done_returns_none(self) -> None:
        """done → None (формируем final сами)."""
        event = FakeStreamEvent(type="done")
        result = ClaudeCodeRuntime._convert_event(event)
        assert result is None
