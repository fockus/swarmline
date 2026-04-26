"""Tests for content_blocks handling in ThinRuntime helpers and LLM providers."""

from swarmline.domain_types import ImageBlock, Message, TextBlock
from swarmline.runtime.thin.helpers import _messages_to_lm
from swarmline.runtime.thin.llm_providers import _filter_chat_messages


# ---------------------------------------------------------------------------
# _messages_to_lm — content_blocks serialization
# ---------------------------------------------------------------------------


class TestMessagesToLmContentBlocks:
    """_messages_to_lm should include content_blocks when present."""

    def test_plain_message_no_content_blocks_key(self) -> None:
        msgs = [Message(role="user", content="hi")]
        result = _messages_to_lm(msgs)
        assert result == [{"role": "user", "content": "hi"}]
        assert "content_blocks" not in result[0]

    def test_message_with_content_blocks_serialized(self) -> None:
        blocks = [
            TextBlock(text="Describe:"),
            ImageBlock(data="img64", media_type="image/png"),
        ]
        msgs = [Message(role="user", content="Describe:", content_blocks=blocks)]
        result = _messages_to_lm(msgs)
        assert len(result) == 1
        assert result[0]["content_blocks"] == [
            {"type": "text", "text": "Describe:"},
            {"type": "image", "data": "img64", "media_type": "image/png"},
        ]

    def test_mixed_messages_some_with_blocks(self) -> None:
        msgs = [
            Message(role="user", content="text only"),
            Message(
                role="user",
                content="with image",
                content_blocks=[ImageBlock(data="x", media_type="image/jpeg")],
            ),
        ]
        result = _messages_to_lm(msgs)
        assert "content_blocks" not in result[0]
        assert "content_blocks" in result[1]


# ---------------------------------------------------------------------------
# _filter_chat_messages — preserve content_blocks
# ---------------------------------------------------------------------------


class TestFilterChatMessagesContentBlocks:
    """_filter_chat_messages should preserve content_blocks from message dicts."""

    def test_plain_messages_unchanged(self) -> None:
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        result = _filter_chat_messages(msgs)
        assert len(result) == 2
        assert "content_blocks" not in result[0]

    def test_content_blocks_preserved(self) -> None:
        blocks = [{"type": "text", "text": "Look:"}]
        msgs = [
            {"role": "user", "content": "Look:", "content_blocks": blocks},
        ]
        result = _filter_chat_messages(msgs)
        assert len(result) == 1
        assert result[0]["content_blocks"] == blocks

    def test_non_chat_messages_filtered_out(self) -> None:
        msgs = [
            {
                "role": "system",
                "content": "sys",
                "content_blocks": [{"type": "text", "text": "sys"}],
            },
            {
                "role": "user",
                "content": "hi",
                "content_blocks": [{"type": "text", "text": "hi"}],
            },
        ]
        result = _filter_chat_messages(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content_blocks"] == [{"type": "text", "text": "hi"}]
