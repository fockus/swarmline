"""Тесты для RuntimeAdapter — обёртка SDK для stream_reply.

Покрытые кейсы:
- StreamEvent dataclass
- Lifecycle: connect / disconnect / is_connected / stderr callback
- stream_reply: happy path (text, tool_use, done)
- Multi-turn: subprocess остаётся живым (receive_response, а не receive_messages)
- BrokenPipe на query → auto-reconnect + retry
- BrokenPipe на query после reconnect → error event
- BrokenPipe при receive_response → error event + reconnect
- Произвольная ошибка на query / receive_response → error event
- ResultMessage НЕ дублирует текст
- _reconnect: disconnect старого client → новый connect
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("claude_agent_sdk", reason="claude-agent-sdk не установлен")
from cognitia.runtime.adapter import RuntimeAdapter, StreamEvent

pytestmark = pytest.mark.requires_claude_sdk


# ---------------------------------------------------------------------------
# Фабрики моков для повторного использования
# ---------------------------------------------------------------------------


def _make_text_block(text: str = "Привет!") -> MagicMock:
    """Мок TextBlock."""
    from cognitia.runtime.adapter import TextBlock

    block = MagicMock(spec=TextBlock)
    block.text = text
    return block


def _make_tool_use_block(
    name: str = "mcp__iss__search",
    input_data: dict | None = None,
) -> MagicMock:
    """Мок ToolUseBlock."""
    from cognitia.runtime.adapter import ToolUseBlock

    block = MagicMock(spec=ToolUseBlock)
    block.name = name
    block.input = input_data or {}
    return block


def _make_tool_result_block(content: str = "result") -> MagicMock:
    """Мок ToolResultBlock."""
    from cognitia.runtime.adapter import ToolResultBlock

    block = MagicMock(spec=ToolResultBlock)
    block.content = content
    return block


def _make_thinking_block(thinking: str = "Let me think...", signature: str = "sig") -> MagicMock:
    """Мок ThinkingBlock."""
    from cognitia.runtime.adapter import ThinkingBlock

    block = MagicMock(spec=ThinkingBlock)
    block.thinking = thinking
    block.signature = signature
    return block


def _make_assistant_msg(blocks: list) -> MagicMock:
    """Мок AssistantMessage с заданными content blocks."""
    from cognitia.runtime.adapter import AssistantMessage

    msg = MagicMock(spec=AssistantMessage)
    msg.content = blocks
    return msg


def _make_sdk_stream_event(event: dict[str, Any]) -> MagicMock:
    """Мок raw SDK StreamEvent."""
    from claude_agent_sdk.types import StreamEvent

    msg = MagicMock(spec=StreamEvent)
    msg.uuid = "ev-1"
    msg.session_id = "sess-1"
    msg.event = event
    msg.parent_tool_use_id = None
    return msg


def _make_task_started_msg(description: str = "Research task") -> MagicMock:
    """Мок TaskStartedMessage (или SystemMessage fallback)."""
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
    """Мок TaskProgressMessage (или SystemMessage fallback)."""
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
    """Мок TaskNotificationMessage (или SystemMessage fallback)."""
    from claude_agent_sdk import SystemMessage

    msg = MagicMock(spec=SystemMessage)
    msg.summary = summary
    msg.status = status
    msg.session_id = "sess-1"
    msg.subtype = "task_notification"
    msg.data = {"summary": summary, "status": status}
    return msg


def _make_result_msg() -> MagicMock:
    """Мок ResultMessage (финальный итог turn'а)."""
    from cognitia.runtime.adapter import ResultMessage

    msg = MagicMock(spec=ResultMessage)
    msg.content = "final summary"
    return msg


def _make_adapter_with_client(
    mock_client: AsyncMock,
) -> tuple[RuntimeAdapter, MagicMock]:
    """Создать RuntimeAdapter с замоканным ClaudeSDKClient.

    Returns:
        (adapter, mock_options)
    """
    mock_options = MagicMock()
    mock_options.stderr = None
    adapter = RuntimeAdapter(mock_options)
    # Подставляем клиент напрямую (без реального connect)
    adapter._client = mock_client
    return adapter, mock_options


# ---------------------------------------------------------------------------
# StreamEvent
# ---------------------------------------------------------------------------


class TestStreamEvent:
    """StreamEvent — dataclass для событий потока."""

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
    """Жизненный цикл адаптера: connect / disconnect / is_connected."""

    def test_initial_not_connected(self) -> None:
        """Новый адаптер — не подключён."""
        mock_options = MagicMock()
        adapter = RuntimeAdapter(mock_options)
        assert adapter.is_connected is False

    @pytest.mark.asyncio
    async def test_connect(self) -> None:
        """connect создаёт client и вызывает client.connect()."""
        mock_options = MagicMock()
        mock_options.stderr = None
        with (
            patch("cognitia.runtime.adapter.ClaudeSDKClient") as MockClient,
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
        """connect устанавливает stderr callback если не задан."""
        mock_options = MagicMock()
        mock_options.stderr = None

        with (
            patch("cognitia.runtime.adapter.ClaudeSDKClient") as MockClient,
            patch("dataclasses.replace", return_value=mock_options) as mock_replace,
        ):
            mock_instance = AsyncMock()
            MockClient.return_value = mock_instance

            adapter = RuntimeAdapter(mock_options)
            await adapter.connect()

            mock_replace.assert_called_once()
            # Проверяем что stderr=_on_stderr передан
            _, kwargs = mock_replace.call_args
            assert kwargs["stderr"] is RuntimeAdapter._on_stderr

    @pytest.mark.asyncio
    async def test_connect_preserves_custom_stderr(self) -> None:
        """connect НЕ перезаписывает пользовательский stderr callback."""
        custom_cb = MagicMock()
        mock_options = MagicMock()
        mock_options.stderr = custom_cb

        with patch("cognitia.runtime.adapter.ClaudeSDKClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value = mock_instance

            adapter = RuntimeAdapter(mock_options)
            await adapter.connect()

            # stderr не должен быть заменён
            assert adapter._options.stderr is custom_cb

    @pytest.mark.asyncio
    async def test_disconnect(self) -> None:
        """disconnect закрывает client."""
        mock_options = MagicMock()
        with patch("cognitia.runtime.adapter.ClaudeSDKClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value = mock_instance

            adapter = RuntimeAdapter(mock_options)
            await adapter.connect()
            await adapter.disconnect()

            assert adapter.is_connected is False
            mock_instance.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self) -> None:
        """disconnect без подключения — не падает."""
        mock_options = MagicMock()
        adapter = RuntimeAdapter(mock_options)
        await adapter.disconnect()  # Не должно бросать исключение


# ---------------------------------------------------------------------------
# Reconnect
# ---------------------------------------------------------------------------


class TestReconnect:
    """_reconnect: disconnect старого + connect нового subprocess."""

    @pytest.mark.asyncio
    async def test_reconnect_disconnects_old_creates_new(self) -> None:
        """_reconnect отключает старый client и создаёт новый."""
        mock_client_old = AsyncMock()
        adapter, _ = _make_adapter_with_client(mock_client_old)

        with patch("cognitia.runtime.adapter.ClaudeSDKClient") as MockClient:
            mock_client_new = AsyncMock()
            MockClient.return_value = mock_client_new

            await adapter._reconnect()

            # Старый client отключён
            mock_client_old.disconnect.assert_awaited_once()
            # Новый client подключён
            mock_client_new.connect.assert_awaited_once()
            assert adapter._client is mock_client_new

    @pytest.mark.asyncio
    async def test_reconnect_handles_disconnect_error(self) -> None:
        """_reconnect не падает если disconnect старого бросает ошибку."""
        mock_client_old = AsyncMock()
        mock_client_old.disconnect.side_effect = RuntimeError("already dead")
        adapter, _ = _make_adapter_with_client(mock_client_old)

        with patch("cognitia.runtime.adapter.ClaudeSDKClient") as MockClient:
            mock_client_new = AsyncMock()
            MockClient.return_value = mock_client_new

            await adapter._reconnect()

            # Новый client всё равно создан
            assert adapter._client is mock_client_new


# ---------------------------------------------------------------------------
# stream_reply — happy path
# ---------------------------------------------------------------------------


class TestStreamReply:
    """stream_reply — стриминг ответов через SDK."""

    @pytest.mark.asyncio
    async def test_not_connected_yields_error(self) -> None:
        """Без подключения — yield error event."""
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
        """Стриминг текстовых сообщений → text_delta + done."""
        mock_client = AsyncMock()

        async def fake_receive_response():
            yield _make_assistant_msg([_make_text_block("Привет!")])

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
        """Стриминг tool_use_start и tool_use_result."""
        mock_client = AsyncMock()

        async def fake_receive_response():
            yield _make_assistant_msg(
                [
                    _make_tool_use_block("mcp__iss__search", {"query": "SBER"}),
                    _make_tool_result_block("found: SBER"),
                    _make_text_block("Нашёл: SBER"),
                ]
            )

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
        # tool_use_start содержит имя инструмента
        tool_event = next(e for e in events if e.type == "tool_use_start")
        assert tool_event.tool_name == "mcp__iss__search"

    @pytest.mark.asyncio
    async def test_thinking_block_not_emitted_as_text(self) -> None:
        """ThinkingBlock не стримится пользователю — только логируется."""
        mock_client = AsyncMock()

        async def fake_receive_response():
            yield _make_assistant_msg(
                [
                    _make_thinking_block("Analyzing the question..."),
                    _make_text_block("Вот ответ"),
                ]
            )

        mock_client.receive_response = fake_receive_response
        adapter, _ = _make_adapter_with_client(mock_client)

        events = []
        async for event in adapter.stream_reply("вопрос"):
            events.append(event)

        types = [e.type for e in events]
        # ThinkingBlock не должен генерировать text_delta
        text_events = [e for e in events if e.type == "text_delta"]
        assert len(text_events) == 1
        assert text_events[0].text == "Вот ответ"
        assert "done" in types

    @pytest.mark.asyncio
    async def test_result_message_not_emitted_as_text(self) -> None:
        """ResultMessage НЕ дублирует текст — текст уже был в AssistantMessage."""
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
        # Только один text_delta от AssistantMessage, не от ResultMessage
        assert len(text_events) == 1
        assert text_events[0].text == "Ответ"

    @pytest.mark.asyncio
    async def test_multi_turn_subprocess_stays_alive(self) -> None:
        """2 вызова stream_reply подряд — subprocess не умирает.

        Ключевой тест: receive_response() останавливается на ResultMessage,
        subprocess остаётся живым для следующего query.
        """
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

        # Turn 2 — subprocess жив, query() НЕ бросает BrokenPipe
        events_2 = []
        async for event in adapter.stream_reply("вопрос 2"):
            events_2.append(event)

        # Оба turn'а успешны
        assert any(e.type == "done" for e in events_1)
        assert any(e.type == "done" for e in events_2)
        assert events_1[-1].text == "Ответ #1"
        assert events_2[-1].text == "Ответ #2"
        # query вызван 2 раза
        assert mock_client.query.await_count == 2


# ---------------------------------------------------------------------------
# stream_reply — BrokenPipe и reconnect
# ---------------------------------------------------------------------------


class TestStreamReplyBrokenPipe:
    """BrokenPipeError — автоматический reconnect."""

    @pytest.mark.asyncio
    async def test_broken_pipe_on_query_reconnects_and_retries(self) -> None:
        """BrokenPipe на первом query → reconnect → retry → успех."""
        mock_client = AsyncMock()
        # Первый query бросает BrokenPipe, второй — OK
        mock_client.query.side_effect = [BrokenPipeError("pipe dead"), None]

        async def fake_receive_response():
            yield _make_assistant_msg([_make_text_block("OK после reconnect")])

        mock_client.receive_response = fake_receive_response
        adapter, _ = _make_adapter_with_client(mock_client)

        # Подменяем _reconnect чтобы не создавать реальный subprocess
        adapter._reconnect = AsyncMock()

        events = []
        async for event in adapter.stream_reply("привет"):
            events.append(event)

        # reconnect вызван 1 раз
        adapter._reconnect.assert_awaited_once()
        # Ответ получен
        assert any(e.type == "done" for e in events)
        assert events[-1].text == "OK после reconnect"

    @pytest.mark.asyncio
    async def test_broken_pipe_on_query_both_attempts_fail(self) -> None:
        """BrokenPipe на оба query → error event."""
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
        """OSError (родитель BrokenPipeError) тоже триггерит reconnect."""
        mock_client = AsyncMock()
        mock_client.query.side_effect = [OSError("connection lost"), None]

        async def fake_receive_response():
            yield _make_assistant_msg([_make_text_block("recovered")])

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
        """ConnectionError тоже триггерит reconnect."""
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
        """BrokenPipe при чтении ответа → error + reconnect для будущих запросов."""
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

        # Есть partial text_delta и error
        types = [e.type for e in events]
        assert "text_delta" in types
        assert "error" in types
        assert "done" not in types  # done НЕ отправлен — ответ неполный
        # reconnect вызван для будущих запросов
        adapter._reconnect.assert_awaited_once()


# ---------------------------------------------------------------------------
# stream_reply — произвольные ошибки
# ---------------------------------------------------------------------------


class TestStreamReplyGenericErrors:
    """Произвольные ошибки (не BrokenPipe) — error event без reconnect."""

    @pytest.mark.asyncio
    async def test_generic_error_on_query(self) -> None:
        """Произвольная ошибка на query → error event, без reconnect."""
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
        # reconnect НЕ вызван — это не pipe-ошибка
        adapter._reconnect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_generic_error_during_receive(self) -> None:
        """Произвольная ошибка при receive_response → error event."""
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
        # reconnect НЕ вызван
        adapter._reconnect.assert_not_awaited()


# ---------------------------------------------------------------------------
# Dynamic Control — set_model, interrupt, set_permission_mode, get_mcp_status, rewind_files
# ---------------------------------------------------------------------------


class TestDynamicControl:
    """Dynamic control методы RuntimeAdapter."""

    @pytest.mark.asyncio
    async def test_set_model_delegates_to_client(self) -> None:
        """set_model() делегирует в client.set_model()."""
        mock_client = AsyncMock()
        adapter, _ = _make_adapter_with_client(mock_client)

        await adapter.set_model("claude-opus-4-20250514")

        mock_client.set_model.assert_awaited_once_with("claude-opus-4-20250514")

    @pytest.mark.asyncio
    async def test_set_model_not_connected_raises(self) -> None:
        """set_model() без подключения → RuntimeError."""
        mock_options = MagicMock()
        adapter = RuntimeAdapter(mock_options)

        with pytest.raises(RuntimeError, match="не подключён"):
            await adapter.set_model("sonnet")

    @pytest.mark.asyncio
    async def test_interrupt_delegates_to_client(self) -> None:
        """interrupt() делегирует в client.interrupt()."""
        mock_client = AsyncMock()
        adapter, _ = _make_adapter_with_client(mock_client)

        await adapter.interrupt()

        mock_client.interrupt.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_interrupt_not_connected_raises(self) -> None:
        """interrupt() без подключения → RuntimeError."""
        mock_options = MagicMock()
        adapter = RuntimeAdapter(mock_options)

        with pytest.raises(RuntimeError, match="не подключён"):
            await adapter.interrupt()

    @pytest.mark.asyncio
    async def test_set_permission_mode_delegates_to_client(self) -> None:
        """set_permission_mode() делегирует в client.set_permission_mode()."""
        mock_client = AsyncMock()
        adapter, _ = _make_adapter_with_client(mock_client)

        await adapter.set_permission_mode("acceptEdits")

        mock_client.set_permission_mode.assert_awaited_once_with("acceptEdits")

    @pytest.mark.asyncio
    async def test_set_permission_mode_not_connected_raises(self) -> None:
        """set_permission_mode() без подключения → RuntimeError."""
        mock_options = MagicMock()
        adapter = RuntimeAdapter(mock_options)

        with pytest.raises(RuntimeError, match="не подключён"):
            await adapter.set_permission_mode("default")

    @pytest.mark.asyncio
    async def test_get_mcp_status_delegates_to_client(self) -> None:
        """get_mcp_status() делегирует в client.get_mcp_status()."""
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
        """get_mcp_status() без подключения → RuntimeError."""
        mock_options = MagicMock()
        adapter = RuntimeAdapter(mock_options)

        with pytest.raises(RuntimeError, match="не подключён"):
            await adapter.get_mcp_status()

    @pytest.mark.asyncio
    async def test_rewind_files_delegates_to_client(self) -> None:
        """rewind_files() делегирует в client.rewind_files()."""
        mock_client = AsyncMock()
        adapter, _ = _make_adapter_with_client(mock_client)

        await adapter.rewind_files("msg-uuid-123")

        mock_client.rewind_files.assert_awaited_once_with("msg-uuid-123")

    @pytest.mark.asyncio
    async def test_rewind_files_not_connected_raises(self) -> None:
        """rewind_files() без подключения → RuntimeError."""
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
    """Мок ResultMessage с метриками."""
    from cognitia.runtime.adapter import ResultMessage

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
    """Extraction метрик из ResultMessage в done StreamEvent."""

    @pytest.mark.asyncio
    async def test_done_event_contains_session_id(self) -> None:
        """done event содержит session_id из ResultMessage."""
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
        """done event содержит total_cost_usd."""
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
        """done event содержит usage."""
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
        """done event содержит structured_output."""
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
    async def test_done_event_without_result_message_has_none_metrics(self) -> None:
        """Без ResultMessage — метрики None."""
        mock_client = AsyncMock()

        async def fake_receive_response():
            yield _make_assistant_msg([_make_text_block("OK")])

        mock_client.receive_response = fake_receive_response
        adapter, _ = _make_adapter_with_client(mock_client)

        events = []
        async for event in adapter.stream_reply("test"):
            events.append(event)

        done_event = events[-1]
        assert done_event.type == "done"
        assert done_event.session_id is None
        assert done_event.total_cost_usd is None
        assert done_event.usage is None
        assert done_event.structured_output is None


class TestPartialAndStatusEvents:
    """Raw partial SDK events и system task messages."""

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

        assert [event.type for event in events] == ["status", "status", "status", "done"]
        assert "Research started" in events[0].text
        assert "Searching" in events[1].text
        assert "Research complete" in events[2].text
