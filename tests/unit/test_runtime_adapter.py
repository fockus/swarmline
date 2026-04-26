"""Tests for RuntimeAdapter - SDK wrapper for stream_reply. Covered Cases:
- StreamEvent dataclass
- Lifecycle: connect / disconnect / is_connected / stderr callback
- stream_reply: happy path (text, tool_use, done)
- Multi-turn: subprocess remains alive (receive_response, not receive_messages)
- BrokenPipe on query -> auto-reconnect + retry
- BrokenPipe on query after reconnect -> error event
- BrokenPipe on receive_response -> error event + reconnect
- Arbitrary error on query / receive_response -> error event
- ResultMessage does NOT duplicate text
- _reconnect: disconnect old client -> new connect"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("claude_agent_sdk", reason="claude-agent-sdk не установлен")
from swarmline.runtime.adapter import RuntimeAdapter, StreamEvent

pytestmark = pytest.mark.requires_claude_sdk


# ---------------------------------------------------------------------------
# Mock factories for reuse
# ---------------------------------------------------------------------------


def _make_text_block(text: str = "Привет!") -> MagicMock:
    """Mock TextBlock."""
    from swarmline.runtime.adapter import TextBlock

    block = MagicMock(spec=TextBlock)
    block.text = text
    return block


def _make_tool_use_block(
    name: str = "mcp__iss__search",
    input_data: dict | None = None,
    tool_use_id: str = "tool-1",
) -> MagicMock:
    """Mock ToolUseBlock."""
    from swarmline.runtime.adapter import ToolUseBlock

    block = MagicMock(spec=ToolUseBlock)
    block.name = name
    block.input = input_data or {}
    block.id = tool_use_id
    return block


def _make_tool_result_block(
    content: str = "result",
    *,
    tool_use_id: str = "tool-1",
    is_error: bool = False,
) -> MagicMock:
    """Mock ToolResultBlock."""
    from swarmline.runtime.adapter import ToolResultBlock

    block = MagicMock(spec=ToolResultBlock)
    block.content = content
    block.tool_use_id = tool_use_id
    block.is_error = is_error
    return block


def _make_thinking_block(
    thinking: str = "Let me think...", signature: str = "sig"
) -> MagicMock:
    """Mock ThinkingBlock."""
    from swarmline.runtime.adapter import ThinkingBlock

    block = MagicMock(spec=ThinkingBlock)
    block.thinking = thinking
    block.signature = signature
    return block


def _make_assistant_msg(blocks: list) -> MagicMock:
    """Mock AssistantMessage with given content blocks."""
    from swarmline.runtime.adapter import AssistantMessage

    msg = MagicMock(spec=AssistantMessage)
    msg.content = blocks
    return msg


def _make_sdk_stream_event(event: dict[str, Any]) -> MagicMock:
    """Mock raw SDK StreamEvent."""
    from claude_agent_sdk.types import StreamEvent

    msg = MagicMock(spec=StreamEvent)
    msg.uuid = "ev-1"
    msg.session_id = "sess-1"
    msg.event = event
    msg.parent_tool_use_id = None
    return msg


def _make_task_started_msg(description: str = "Research task") -> MagicMock:
    """Mock TaskStartedMessage (or SystemMessage fallback)."""
    from claude_agent_sdk import SystemMessage

    msg = MagicMock(spec=SystemMessage)
    msg.description = description
    msg.session_id = "sess-1"
    msg.subtype = "task_started"
    msg.data = {"description": description}
    return msg


def _make_task_progress_msg(
    description: str = "Working",
    last_tool_name: str | None = None,
) -> MagicMock:
    """Mock TaskProgressMessage (or SystemMessage fallback)."""
    from claude_agent_sdk import SystemMessage

    msg = MagicMock(spec=SystemMessage)
    msg.description = description
    msg.last_tool_name = last_tool_name
    msg.session_id = "sess-1"
    msg.subtype = "task_progress"
    msg.data = {"description": description, "last_tool_name": last_tool_name}
    return msg


def _make_task_notification_msg(
    summary: str = "Task complete",
    status: str = "completed",
) -> MagicMock:
    """Mock TaskNotificationMessage (or SystemMessage fallback)."""
    from claude_agent_sdk import SystemMessage

    msg = MagicMock(spec=SystemMessage)
    msg.summary = summary
    msg.status = status
    msg.session_id = "sess-1"
    msg.subtype = "task_notification"
    msg.data = {"summary": summary, "status": status}
    return msg


def _make_result_msg() -> MagicMock:
    """Mock ResultMessage (final result of the turn)."""
    from swarmline.runtime.adapter import ResultMessage

    msg = MagicMock(spec=ResultMessage)
    msg.content = "final summary"
    return msg


def _make_adapter_with_client(
    mock_client: AsyncMock,
) -> tuple[RuntimeAdapter, MagicMock]:
    """Create RuntimeAdapter with ClaudeSDKClient mocked. Returns: (adapter, mock_options)"""
    mock_options = MagicMock()
    mock_options.stderr = None
    adapter = RuntimeAdapter(mock_options)
    # We substitute the client directly (without real connect)
    adapter._client = mock_client
    return adapter, mock_options


# ---------------------------------------------------------------------------
# StreamEvent
# ---------------------------------------------------------------------------


class TestStreamEvent:
    """StreamEvent - dataclass for stream events."""

    def test_defaults(self) -> None:
        event = StreamEvent(type="text_delta")
        assert event.text == ""
        assert event.tool_name == ""
        assert event.tool_input is None
        assert event.tool_result == ""
        assert event.is_final is False

    def test_text_delta(self) -> None:
        event = StreamEvent(type="text_delta", text="Привет!")
        assert event.type == "text_delta"
        assert event.text == "Привет!"

    def test_tool_use_start(self) -> None:
        event = StreamEvent(
            type="tool_use_start",
            tool_name="mcp__iss__get_bonds",
            tool_input={"query": "облигации"},
        )
        assert event.tool_name == "mcp__iss__get_bonds"
        assert event.tool_input["query"] == "облигации"

    def test_done_event(self) -> None:
        event = StreamEvent(type="done", text="Полный ответ", is_final=True)
        assert event.is_final is True


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestRuntimeAdapterLifecycle:
    """Adapter life cycle: connect / disconnect / is_connected."""

    def test_initial_not_connected(self) -> None:
        """New adapter - not connected."""
        mock_options = MagicMock()
        adapter = RuntimeAdapter(mock_options)
        assert adapter.is_connected is False

    @pytest.mark.asyncio
    async def test_connect(self) -> None:
        """connect creates a client and calls client.connect()."""
        mock_options = MagicMock()
        mock_options.stderr = None
        with (
            patch("swarmline.runtime.adapter.ClaudeSDKClient") as MockClient,
            patch("dataclasses.replace", return_value=mock_options),
        ):
            mock_instance = AsyncMock()
            MockClient.return_value = mock_instance

            adapter = RuntimeAdapter(mock_options)
            await adapter.connect()

            assert adapter.is_connected is True
            mock_instance.connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_sets_stderr_callback(self) -> None:
        """connect sets stderr callback if not given."""
        mock_options = MagicMock()
        mock_options.stderr = None

        with (
            patch("swarmline.runtime.adapter.ClaudeSDKClient") as MockClient,
            patch("dataclasses.replace", return_value=mock_options) as mock_replace,
        ):
            mock_instance = AsyncMock()
            MockClient.return_value = mock_instance

            adapter = RuntimeAdapter(mock_options)
            await adapter.connect()

            mock_replace.assert_called_once()
            # Verify that stderr=_on_stderr is passed
            _, kwargs = mock_replace.call_args
            assert kwargs["stderr"] is RuntimeAdapter._on_stderr

    @pytest.mark.asyncio
    async def test_connect_preserves_custom_stderr(self) -> None:
        """connect does NOT overwrite user stderr callback."""
        custom_cb = MagicMock()
        mock_options = MagicMock()
        mock_options.stderr = custom_cb

        with patch("swarmline.runtime.adapter.ClaudeSDKClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value = mock_instance

            adapter = RuntimeAdapter(mock_options)
            await adapter.connect()

            # stderr should not be replaced
            assert adapter._options.stderr is custom_cb

    @pytest.mark.asyncio
    async def test_disconnect(self) -> None:
        """disconnect closes client."""
        mock_options = MagicMock()
        with patch("swarmline.runtime.adapter.ClaudeSDKClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value = mock_instance

            adapter = RuntimeAdapter(mock_options)
            await adapter.connect()
            await adapter.disconnect()

            assert adapter.is_connected is False
            mock_instance.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self) -> None:
        """disconnect without connection - not crashes."""
        mock_options = MagicMock()
        adapter = RuntimeAdapter(mock_options)
        await adapter.disconnect()  # Not should throw an exception


# ---------------------------------------------------------------------------
# Reconnect
# ---------------------------------------------------------------------------


class TestReconnect:
    """_reconnect: disconnect old + connect new subprocess."""

    @pytest.mark.asyncio
    async def test_reconnect_disconnects_old_creates_new(self) -> None:
        """_reconnect disconnects the legacy client and creates a new one."""
        mock_client_old = AsyncMock()
        adapter, _ = _make_adapter_with_client(mock_client_old)

        with patch("swarmline.runtime.adapter.ClaudeSDKClient") as MockClient:
            mock_client_new = AsyncMock()
            MockClient.return_value = mock_client_new

            await adapter._reconnect()

            # Legacy client disabled
            mock_client_old.disconnect.assert_awaited_once()
            # New client connected
            mock_client_new.connect.assert_awaited_once()
            assert adapter._client is mock_client_new

    @pytest.mark.asyncio
    async def test_reconnect_handles_disconnect_error(self) -> None:
        """_reconnect not crashes if disconnect old throws an error."""
        mock_client_old = AsyncMock()
        mock_client_old.disconnect.side_effect = RuntimeError("already dead")
        adapter, _ = _make_adapter_with_client(mock_client_old)

        with patch("swarmline.runtime.adapter.ClaudeSDKClient") as MockClient:
            mock_client_new = AsyncMock()
            MockClient.return_value = mock_client_new

            await adapter._reconnect()

            # New client is still created
            assert adapter._client is mock_client_new


# ---------------------------------------------------------------------------
# stream_reply — happy path
# ---------------------------------------------------------------------------


class TestStreamReply:
    """stream_reply - streaming replies via SDK."""

    @pytest.mark.asyncio
    async def test_not_connected_yields_error(self) -> None:
        """Without connection - yield error event."""
        mock_options = MagicMock()
        adapter = RuntimeAdapter(mock_options)

        events = []
        async for event in adapter.stream_reply("привет"):
            events.append(event)

        assert len(events) == 1
        assert events[0].type == "error"
        assert "не подключён" in events[0].text

    @pytest.mark.asyncio
    async def test_stream_text_messages(self) -> None:
        """Streaming text messages -> text_delta + done."""
        mock_client = AsyncMock()

        async def fake_receive_response():
            yield _make_assistant_msg([_make_text_block("Привет!")])
            yield _make_result_msg()

        mock_client.receive_response = fake_receive_response
        adapter, _ = _make_adapter_with_client(mock_client)

        events = []
        async for event in adapter.stream_reply("привет"):
            events.append(event)

        types = [e.type for e in events]
        assert "text_delta" in types
        assert "done" in types
        assert events[-1].is_final is True
        assert events[-1].text == "Привет!"

    @pytest.mark.asyncio
    async def test_stream_tool_use_events(self) -> None:
        """Streaming tool_use_start and tool_use_result."""
        mock_client = AsyncMock()

        async def fake_receive_response():
            yield _make_assistant_msg(
                [
                    _make_tool_use_block("mcp__iss__search", {"query": "SBER"}),
                    _make_tool_result_block("found: SBER"),
                    _make_text_block("Нашёл: SBER"),
                ]
            )
            yield _make_result_msg()

        mock_client.receive_response = fake_receive_response
        adapter, _ = _make_adapter_with_client(mock_client)

        events = []
        async for event in adapter.stream_reply("найди SBER"):
            events.append(event)

        types = [e.type for e in events]
        assert "tool_use_start" in types
        assert "tool_use_result" in types
        assert "text_delta" in types
        assert "done" in types
        # tool_use_start contains tool name
        tool_event = next(e for e in events if e.type == "tool_use_start")
        assert tool_event.tool_name == "mcp__iss__search"
        assert tool_event.correlation_id == "tool-1"
        result_event = next(e for e in events if e.type == "tool_use_result")
        assert result_event.tool_name == "mcp__iss__search"
        assert result_event.correlation_id == "tool-1"
        assert result_event.tool_error is False

    @pytest.mark.asyncio
    async def test_stream_tool_result_preserves_error_metadata(self) -> None:
        mock_client = AsyncMock()

        async def fake_receive_response():
            yield _make_assistant_msg(
                [
                    _make_tool_use_block(
                        "mcp__iss__search", {"query": "SBER"}, tool_use_id="tool-9"
                    ),
                    _make_tool_result_block(
                        "failed: upstream timeout",
                        tool_use_id="tool-9",
                        is_error=True,
                    ),
                ]
            )
            yield _make_result_msg()

        mock_client.receive_response = fake_receive_response
        adapter, _ = _make_adapter_with_client(mock_client)

        events = []
        async for event in adapter.stream_reply("найди SBER"):
            events.append(event)

        result_event = next(e for e in events if e.type == "tool_use_result")
        assert result_event.tool_name == "mcp__iss__search"
        assert result_event.correlation_id == "tool-9"
        assert result_event.tool_error is True
        assert result_event.tool_result == "failed: upstream timeout"

    @pytest.mark.asyncio
    async def test_thinking_block_not_emitted_as_text(self) -> None:
        """ThinkingBlock is not streamed to the user - it is only logged."""
        mock_client = AsyncMock()

        async def fake_receive_response():
            yield _make_assistant_msg(
                [
                    _make_thinking_block("Analyzing the question..."),
                    _make_text_block("Вот ответ"),
                ]
            )
            yield _make_result_msg()

        mock_client.receive_response = fake_receive_response
        adapter, _ = _make_adapter_with_client(mock_client)

        events = []
        async for event in adapter.stream_reply("вопрос"):
            events.append(event)

        types = [e.type for e in events]
        # ThinkingBlock should not generate text_delta
        text_events = [e for e in events if e.type == "text_delta"]
        assert len(text_events) == 1
        assert text_events[0].text == "Вот ответ"
        assert "done" in types

    @pytest.mark.asyncio
    async def test_result_message_not_emitted_as_text(self) -> None:
        """ResultMessage does NOT duplicate text - the text was already in AssistantMessage."""
        mock_client = AsyncMock()

        async def fake_receive_response():
            yield _make_assistant_msg([_make_text_block("Ответ")])
            yield _make_result_msg()

        mock_client.receive_response = fake_receive_response
        adapter, _ = _make_adapter_with_client(mock_client)

        events = []
        async for event in adapter.stream_reply("вопрос"):
            events.append(event)

        text_events = [e for e in events if e.type == "text_delta"]
        # Only one text_delta from AssistantMessage, not from ResultMessage
        assert len(text_events) == 1
        assert text_events[0].text == "Ответ"

    @pytest.mark.asyncio
    async def test_multi_turn_subprocess_stays_alive(self) -> None:
        """2 stream_reply calls in a row - subprocess does not die. Key test: receive_response() stops on ResultMessage, subprocess remains alive for the next query."""
        mock_client = AsyncMock()
        call_count = 0

        async def fake_receive_response():
            nonlocal call_count
            call_count += 1
            yield _make_assistant_msg([_make_text_block(f"Ответ #{call_count}")])
            yield _make_result_msg()

        mock_client.receive_response = fake_receive_response
        adapter, _ = _make_adapter_with_client(mock_client)

        # Turn 1
        events_1 = []
        async for event in adapter.stream_reply("вопрос 1"):
            events_1.append(event)

        # Turn 2 - subprocess is alive, query() does NOT throw BrokenPipe
        events_2 = []
        async for event in adapter.stream_reply("вопрос 2"):
            events_2.append(event)

        # Both turns are successful
        assert any(e.type == "done" for e in events_1)
        assert any(e.type == "done" for e in events_2)
        assert events_1[-1].text == "Ответ #1"
        assert events_2[-1].text == "Ответ #2"
        # query called 2 times
        assert mock_client.query.await_count == 2


# ---------------------------------------------------------------------------
# stream_reply - BrokenPipe and reconnect
# ---------------------------------------------------------------------------


class TestStreamReplyBrokenPipe:
    """BrokenPipeError - automatic reconnect."""

    @pytest.mark.asyncio
    async def test_broken_pipe_on_query_reconnects_and_retries(self) -> None:
        """BrokenPipe on the first query -> reconnect -> retry -> success."""
        mock_client = AsyncMock()
        # The first query throws BrokenPipe, the second - OK
        mock_client.query.side_effect = [BrokenPipeError("pipe dead"), None]

        async def fake_receive_response():
            yield _make_assistant_msg([_make_text_block("OK после reconnect")])
            yield _make_result_msg()

        mock_client.receive_response = fake_receive_response
        adapter, _ = _make_adapter_with_client(mock_client)

        # Swap _reconnect to not create a real subprocess
        adapter._reconnect = AsyncMock()

        events = []
        async for event in adapter.stream_reply("привет"):
            events.append(event)

        # reconnect called 1 time
        adapter._reconnect.assert_awaited_once()
        # Reply received
        assert any(e.type == "done" for e in events)
        assert events[-1].text == "OK после reconnect"

    @pytest.mark.asyncio
    async def test_broken_pipe_on_query_both_attempts_fail(self) -> None:
        """BrokenPipe on both query -> error event."""
        mock_client = AsyncMock()
        mock_client.query.side_effect = BrokenPipeError("pipe dead")

        adapter, _ = _make_adapter_with_client(mock_client)
        adapter._reconnect = AsyncMock()

        events = []
        async for event in adapter.stream_reply("привет"):
            events.append(event)

        assert len(events) == 1
        assert events[0].type == "error"
        assert "subprocess упал" in events[0].text

    @pytest.mark.asyncio
    async def test_oserror_on_query_triggers_reconnect(self) -> None:
        """OSError (parent of BrokenPipeError) also triggers reconnect."""
        mock_client = AsyncMock()
        mock_client.query.side_effect = [OSError("connection lost"), None]

        async def fake_receive_response():
            yield _make_assistant_msg([_make_text_block("recovered")])
            yield _make_result_msg()

        mock_client.receive_response = fake_receive_response
        adapter, _ = _make_adapter_with_client(mock_client)
        adapter._reconnect = AsyncMock()

        events = []
        async for event in adapter.stream_reply("привет"):
            events.append(event)

        adapter._reconnect.assert_awaited_once()
        assert any(e.type == "done" for e in events)

    @pytest.mark.asyncio
    async def test_connection_error_on_query_triggers_reconnect(self) -> None:
        """ConnectionError also triggers reconnect."""
        mock_client = AsyncMock()
        mock_client.query.side_effect = [ConnectionError("reset"), None]

        async def fake_receive_response():
            yield _make_assistant_msg([_make_text_block("ok")])

        mock_client.receive_response = fake_receive_response
        adapter, _ = _make_adapter_with_client(mock_client)
        adapter._reconnect = AsyncMock()

        events = []
        async for event in adapter.stream_reply("привет"):
            events.append(event)

        adapter._reconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_broken_pipe_during_receive_yields_error_and_reconnects(self) -> None:
        """BrokenPipe when reading response -> error + reconnect for future requests."""
        mock_client = AsyncMock()

        async def broken_receive():
            yield _make_assistant_msg([_make_text_block("partial")])
            raise BrokenPipeError("pipe broke mid-stream")

        mock_client.receive_response = broken_receive
        adapter, _ = _make_adapter_with_client(mock_client)
        adapter._reconnect = AsyncMock()

        events = []
        async for event in adapter.stream_reply("вопрос"):
            events.append(event)

        # There is partial text_delta and error
        types = [e.type for e in events]
        assert "text_delta" in types
        assert "error" in types
        assert "done" not in types  # done NOT sent - notfull response
        # reconnect called for future requests
        adapter._reconnect.assert_awaited_once()


# ---------------------------------------------------------------------------
# stream_reply - arbitrary errors
# ---------------------------------------------------------------------------


class TestStreamReplyGenericErrors:
    """Arbitrary errors (not BrokenPipe) - error event without reconnect."""

    @pytest.mark.asyncio
    async def test_generic_error_on_query(self) -> None:
        """Arbitrary error on query -> error event, without reconnect."""
        mock_client = AsyncMock()
        mock_client.query.side_effect = ValueError("bad input")

        adapter, _ = _make_adapter_with_client(mock_client)
        adapter._reconnect = AsyncMock()

        events = []
        async for event in adapter.stream_reply("привет"):
            events.append(event)

        assert len(events) == 1
        assert events[0].type == "error"
        assert "Ошибка SDK query" in events[0].text
        # reconnect is NOT called - this is not pipe-error
        adapter._reconnect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_generic_error_during_receive(self) -> None:
        """Arbitrary error when receive_response -> error event."""
        mock_client = AsyncMock()

        async def broken_receive():
            if False:  # pragma: no cover
                yield None
            raise RuntimeError("unexpected SDK error")

        mock_client.receive_response = broken_receive
        adapter, _ = _make_adapter_with_client(mock_client)
        adapter._reconnect = AsyncMock()

        events = []
        async for event in adapter.stream_reply("привет"):
            events.append(event)

        assert len(events) == 1
        assert events[0].type == "error"
        assert "Ошибка SDK" in events[0].text
        # reconnect is NOT called
        adapter._reconnect.assert_not_awaited()


# ---------------------------------------------------------------------------
# Dynamic Control — set_model, interrupt, set_permission_mode, get_mcp_status, rewind_files
# ---------------------------------------------------------------------------


class TestDynamicControl:
    """Dynamic control methods of RuntimeAdapter."""

    @pytest.mark.asyncio
    async def test_set_model_delegates_to_client(self) -> None:
        """set_model() delegates in client.set_model()."""
        mock_client = AsyncMock()
        adapter, _ = _make_adapter_with_client(mock_client)

        await adapter.set_model("claude-opus-4-20250514")

        mock_client.set_model.assert_awaited_once_with("claude-opus-4-20250514")

    @pytest.mark.asyncio
    async def test_set_model_not_connected_raises(self) -> None:
        """set_model() without connection -> RuntimeError."""
        mock_options = MagicMock()
        adapter = RuntimeAdapter(mock_options)

        with pytest.raises(RuntimeError, match="не подключён"):
            await adapter.set_model("sonnet")

    @pytest.mark.asyncio
    async def test_interrupt_delegates_to_client(self) -> None:
        """interrupt() delegates in client.interrupt()."""
        mock_client = AsyncMock()
        adapter, _ = _make_adapter_with_client(mock_client)

        await adapter.interrupt()

        mock_client.interrupt.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_interrupt_not_connected_raises(self) -> None:
        """interrupt() without connection -> RuntimeError."""
        mock_options = MagicMock()
        adapter = RuntimeAdapter(mock_options)

        with pytest.raises(RuntimeError, match="не подключён"):
            await adapter.interrupt()

    @pytest.mark.asyncio
    async def test_set_permission_mode_delegates_to_client(self) -> None:
        """set_permission_mode() delegates in client.set_permission_mode()."""
        mock_client = AsyncMock()
        adapter, _ = _make_adapter_with_client(mock_client)

        await adapter.set_permission_mode("acceptEdits")

        mock_client.set_permission_mode.assert_awaited_once_with("acceptEdits")

    @pytest.mark.asyncio
    async def test_set_permission_mode_not_connected_raises(self) -> None:
        """set_permission_mode() without connection -> RuntimeError."""
        mock_options = MagicMock()
        adapter = RuntimeAdapter(mock_options)

        with pytest.raises(RuntimeError, match="не подключён"):
            await adapter.set_permission_mode("default")

    @pytest.mark.asyncio
    async def test_get_mcp_status_delegates_to_client(self) -> None:
        """get_mcp_status() delegates in client.get_mcp_status()."""
        mock_client = AsyncMock()
        mock_client.get_mcp_status.return_value = {
            "mcpServers": [{"name": "iss", "status": "connected"}],
        }
        adapter, _ = _make_adapter_with_client(mock_client)

        result = await adapter.get_mcp_status()

        mock_client.get_mcp_status.assert_awaited_once()
        assert result["mcpServers"][0]["name"] == "iss"

    @pytest.mark.asyncio
    async def test_get_mcp_status_not_connected_raises(self) -> None:
        """get_mcp_status() without connection -> RuntimeError."""
        mock_options = MagicMock()
        adapter = RuntimeAdapter(mock_options)

        with pytest.raises(RuntimeError, match="не подключён"):
            await adapter.get_mcp_status()

    @pytest.mark.asyncio
    async def test_rewind_files_delegates_to_client(self) -> None:
        """rewind_files() delegates in client.rewind_files()."""
        mock_client = AsyncMock()
        adapter, _ = _make_adapter_with_client(mock_client)

        await adapter.rewind_files("msg-uuid-123")

        mock_client.rewind_files.assert_awaited_once_with("msg-uuid-123")

    @pytest.mark.asyncio
    async def test_rewind_files_not_connected_raises(self) -> None:
        """rewind_files() without connection -> RuntimeError."""
        mock_options = MagicMock()
        adapter = RuntimeAdapter(mock_options)

        with pytest.raises(RuntimeError, match="не подключён"):
            await adapter.rewind_files("msg-uuid-123")


# ---------------------------------------------------------------------------
# ResultMessage metrics extraction
# ---------------------------------------------------------------------------


def _make_result_msg_with_metrics(
    session_id: str = "sess-1",
    total_cost_usd: float | None = 0.05,
    usage: dict | None = None,
    structured_output: Any = None,
    duration_ms: int = 1500,
    num_turns: int = 3,
) -> MagicMock:
    """Mock ResultMessage with metrics."""
    from swarmline.runtime.adapter import ResultMessage

    msg = MagicMock(spec=ResultMessage)
    msg.session_id = session_id
    msg.total_cost_usd = total_cost_usd
    msg.usage = usage or {"input_tokens": 100, "output_tokens": 50}
    msg.structured_output = structured_output
    msg.duration_ms = duration_ms
    msg.duration_api_ms = duration_ms
    msg.num_turns = num_turns
    msg.is_error = False
    msg.result = None
    msg.subtype = "success"
    return msg


class TestResultMessageMetrics:
    """Extraction of metrics from ResultMessage in done StreamEvent."""

    @pytest.mark.asyncio
    async def test_done_event_contains_session_id(self) -> None:
        """done event contains session_id from ResultMessage."""
        mock_client = AsyncMock()

        async def fake_receive_response():
            yield _make_assistant_msg([_make_text_block("OK")])
            yield _make_result_msg_with_metrics(session_id="sess-abc")

        mock_client.receive_response = fake_receive_response
        adapter, _ = _make_adapter_with_client(mock_client)

        events = []
        async for event in adapter.stream_reply("test"):
            events.append(event)

        done_event = events[-1]
        assert done_event.type == "done"
        assert done_event.session_id == "sess-abc"

    @pytest.mark.asyncio
    async def test_done_event_contains_cost(self) -> None:
        """done event contains total_cost_usd."""
        mock_client = AsyncMock()

        async def fake_receive_response():
            yield _make_assistant_msg([_make_text_block("OK")])
            yield _make_result_msg_with_metrics(total_cost_usd=0.123)

        mock_client.receive_response = fake_receive_response
        adapter, _ = _make_adapter_with_client(mock_client)

        events = []
        async for event in adapter.stream_reply("test"):
            events.append(event)

        done_event = events[-1]
        assert done_event.total_cost_usd == 0.123

    @pytest.mark.asyncio
    async def test_done_event_contains_usage(self) -> None:
        """done event contains usage."""
        mock_client = AsyncMock()
        usage = {"input_tokens": 200, "output_tokens": 100}

        async def fake_receive_response():
            yield _make_assistant_msg([_make_text_block("OK")])
            yield _make_result_msg_with_metrics(usage=usage)

        mock_client.receive_response = fake_receive_response
        adapter, _ = _make_adapter_with_client(mock_client)

        events = []
        async for event in adapter.stream_reply("test"):
            events.append(event)

        done_event = events[-1]
        assert done_event.usage == usage

    @pytest.mark.asyncio
    async def test_done_event_contains_structured_output(self) -> None:
        """done event contains structured_output."""
        mock_client = AsyncMock()
        struct = {"answer": "42", "confidence": 0.99}

        async def fake_receive_response():
            yield _make_assistant_msg([_make_text_block("OK")])
            yield _make_result_msg_with_metrics(structured_output=struct)

        mock_client.receive_response = fake_receive_response
        adapter, _ = _make_adapter_with_client(mock_client)

        events = []
        async for event in adapter.stream_reply("test"):
            events.append(event)

        done_event = events[-1]
        assert done_event.structured_output == struct

    @pytest.mark.asyncio
    async def test_missing_result_message_emits_error(self) -> None:
        """Without ResultMessage stream_reply should not end as done."""
        mock_client = AsyncMock()

        async def fake_receive_response():
            yield _make_assistant_msg([_make_text_block("OK")])

        mock_client.receive_response = fake_receive_response
        adapter, _ = _make_adapter_with_client(mock_client)

        events = []
        async for event in adapter.stream_reply("test"):
            events.append(event)

        assert [event.type for event in events] == ["text_delta", "error"]
        assert "final ResultMessage" in events[-1].text


class TestPartialAndStatusEvents:
    """Raw partial SDK events and system task messages."""

    @pytest.mark.asyncio
    async def test_partial_stream_events_emit_text_without_duplication(self) -> None:
        mock_client = AsyncMock()
        mock_options = MagicMock()
        mock_options.stderr = None
        mock_options.include_partial_messages = True

        async def fake_receive_response():
            yield _make_sdk_stream_event(
                {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "Hel"},
                }
            )
            yield _make_sdk_stream_event(
                {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "lo"},
                }
            )
            yield _make_assistant_msg([_make_text_block("Hello")])
            yield _make_result_msg_with_metrics()

        mock_client.receive_response = fake_receive_response
        adapter = RuntimeAdapter(mock_options)
        adapter._client = mock_client

        events = []
        async for event in adapter.stream_reply("test"):
            events.append(event)

        assert [event.type for event in events] == ["text_delta", "text_delta", "done"]
        assert events[0].text == "Hel"
        assert events[1].text == "lo"
        assert events[2].text == "Hello"

    @pytest.mark.asyncio
    async def test_task_system_messages_emit_status_events(self) -> None:
        mock_client = AsyncMock()

        async def fake_receive_response():
            yield _make_task_started_msg("Research started")
            yield _make_task_progress_msg("Searching", last_tool_name="WebSearch")
            yield _make_task_notification_msg("Research complete")
            yield _make_result_msg_with_metrics()

        mock_client.receive_response = fake_receive_response
        adapter, _ = _make_adapter_with_client(mock_client)

        events = []
        async for event in adapter.stream_reply("test"):
            events.append(event)

        assert [event.type for event in events] == [
            "status",
            "status",
            "status",
            "done",
        ]
        assert "Research started" in events[0].text
        assert "Searching" in events[1].text
        assert "Research complete" in events[2].text
