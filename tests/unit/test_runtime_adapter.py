"""Тесты для RuntimeAdapter — обёртка SDK для stream_reply."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cognitia.runtime.adapter import RuntimeAdapter, StreamEvent


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


class TestRuntimeAdapterLifecycle:
    """Жизненный цикл адаптера: connect / disconnect / is_connected."""

    def test_initial_not_connected(self) -> None:
        """Новый адаптер — не подключён."""
        mock_options = MagicMock()
        adapter = RuntimeAdapter(mock_options)
        assert adapter.is_connected is False

    @pytest.mark.asyncio
    async def test_connect(self) -> None:
        """connect создаёт client."""
        mock_options = MagicMock()
        with patch("cognitia.runtime.adapter.ClaudeSDKClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value = mock_instance

            adapter = RuntimeAdapter(mock_options)
            await adapter.connect()

            assert adapter.is_connected is True
            mock_instance.connect.assert_awaited_once()

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
        """Стриминг текстовых сообщений из SDK."""
        mock_options = MagicMock()

        with patch("cognitia.runtime.adapter.ClaudeSDKClient") as MockClient:
            # Подготавливаем мок SDK-клиента
            mock_client = AsyncMock()
            MockClient.return_value = mock_client

            # Мок TextBlock
            text_block = MagicMock()
            text_block.text = "Привет! Как дела?"
            text_block.__class__.__name__ = "TextBlock"

            # Мок AssistantMessage
            from cognitia.runtime.adapter import AssistantMessage
            assistant_msg = MagicMock(spec=AssistantMessage)
            assistant_msg.content = [text_block]

            # Настраиваем receive_messages
            async def fake_receive():
                yield assistant_msg

            mock_client.receive_messages = fake_receive

            adapter = RuntimeAdapter(mock_options)
            await adapter.connect()

            events = []
            async for event in adapter.stream_reply("привет"):
                events.append(event)

            # Должен быть text_delta + done
            assert any(e.type == "done" for e in events)
