"""Tests for ContentBlock domain types — TextBlock, ImageBlock, and Message.content_blocks."""

import pytest

from swarmline.domain_types import ContentBlock, ImageBlock, Message, TextBlock


# ---------------------------------------------------------------------------
# TextBlock
# ---------------------------------------------------------------------------


class TestTextBlock:
    """TextBlock — frozen dataclass for text content."""

    def test_create_with_text(self) -> None:
        block = TextBlock(text="Hello, world!")
        assert block.text == "Hello, world!"

    def test_frozen(self) -> None:
        block = TextBlock(text="immutable")
        with pytest.raises(AttributeError):
            block.text = "mutated"  # type: ignore[misc]

    def test_to_dict_returns_type_and_text(self) -> None:
        block = TextBlock(text="some text")
        d = block.to_dict()
        assert d == {"type": "text", "text": "some text"}

    def test_empty_text_allowed(self) -> None:
        block = TextBlock(text="")
        assert block.text == ""
        assert block.to_dict() == {"type": "text", "text": ""}

    def test_equality(self) -> None:
        a = TextBlock(text="same")
        b = TextBlock(text="same")
        assert a == b

    def test_hashable(self) -> None:
        block = TextBlock(text="hash me")
        assert {block: 1}[TextBlock(text="hash me")] == 1


# ---------------------------------------------------------------------------
# ImageBlock
# ---------------------------------------------------------------------------


class TestImageBlock:
    """ImageBlock — frozen dataclass for base64-encoded image content."""

    def test_create_with_data_and_media_type(self) -> None:
        block = ImageBlock(data="iVBORw0KGgo=", media_type="image/png")
        assert block.data == "iVBORw0KGgo="
        assert block.media_type == "image/png"

    def test_frozen(self) -> None:
        block = ImageBlock(data="abc", media_type="image/jpeg")
        with pytest.raises(AttributeError):
            block.data = "xyz"  # type: ignore[misc]

    def test_to_dict_returns_type_and_fields(self) -> None:
        block = ImageBlock(data="base64data", media_type="image/webp")
        d = block.to_dict()
        assert d == {
            "type": "image",
            "data": "base64data",
            "media_type": "image/webp",
        }

    def test_equality(self) -> None:
        a = ImageBlock(data="x", media_type="image/png")
        b = ImageBlock(data="x", media_type="image/png")
        assert a == b

    def test_hashable(self) -> None:
        block = ImageBlock(data="x", media_type="image/png")
        assert {block: 42}[ImageBlock(data="x", media_type="image/png")] == 42


# ---------------------------------------------------------------------------
# ContentBlock type alias
# ---------------------------------------------------------------------------


class TestContentBlockAlias:
    """ContentBlock = TextBlock | ImageBlock — union type alias."""

    def test_text_block_is_content_block(self) -> None:
        block: ContentBlock = TextBlock(text="hi")
        assert isinstance(block, TextBlock)

    def test_image_block_is_content_block(self) -> None:
        block: ContentBlock = ImageBlock(data="x", media_type="image/png")
        assert isinstance(block, ImageBlock)


# ---------------------------------------------------------------------------
# Message.content_blocks extension
# ---------------------------------------------------------------------------


class TestMessageContentBlocks:
    """Message.content_blocks — optional list of ContentBlock."""

    def test_default_content_blocks_is_none(self) -> None:
        msg = Message(role="user", content="text only")
        assert msg.content_blocks is None

    def test_content_blocks_with_text(self) -> None:
        blocks = [TextBlock(text="Hello")]
        msg = Message(role="user", content="Hello", content_blocks=blocks)
        assert msg.content_blocks is not None
        assert len(msg.content_blocks) == 1
        assert isinstance(msg.content_blocks[0], TextBlock)

    def test_content_blocks_with_image(self) -> None:
        blocks = [ImageBlock(data="abc", media_type="image/png")]
        msg = Message(role="user", content="", content_blocks=blocks)
        assert msg.content_blocks is not None
        assert isinstance(msg.content_blocks[0], ImageBlock)

    def test_content_blocks_mixed(self) -> None:
        blocks: list[ContentBlock] = [
            TextBlock(text="Describe this image:"),
            ImageBlock(data="base64img", media_type="image/jpeg"),
        ]
        msg = Message(role="user", content="", content_blocks=blocks)
        assert msg.content_blocks is not None
        assert len(msg.content_blocks) == 2
        assert isinstance(msg.content_blocks[0], TextBlock)
        assert isinstance(msg.content_blocks[1], ImageBlock)

    def test_to_dict_without_content_blocks(self) -> None:
        msg = Message(role="user", content="test")
        d = msg.to_dict()
        assert "content_blocks" not in d

    def test_to_dict_with_content_blocks(self) -> None:
        blocks: list[ContentBlock] = [
            TextBlock(text="Look:"),
            ImageBlock(data="img64", media_type="image/png"),
        ]
        msg = Message(role="user", content="Look:", content_blocks=blocks)
        d = msg.to_dict()
        assert "content_blocks" in d
        assert d["content_blocks"] == [
            {"type": "text", "text": "Look:"},
            {"type": "image", "data": "img64", "media_type": "image/png"},
        ]

    def test_to_dict_preserves_other_fields(self) -> None:
        blocks = [TextBlock(text="hi")]
        msg = Message(
            role="tool",
            content="hi",
            name="read",
            content_blocks=blocks,
            metadata={"ts": 1},
        )
        d = msg.to_dict()
        assert d["role"] == "tool"
        assert d["content"] == "hi"
        assert d["name"] == "read"
        assert d["metadata"] == {"ts": 1}
        assert d["content_blocks"] == [{"type": "text", "text": "hi"}]

    def test_message_frozen_with_content_blocks(self) -> None:
        blocks = [TextBlock(text="hi")]
        msg = Message(role="user", content="hi", content_blocks=blocks)
        with pytest.raises(AttributeError):
            msg.content_blocks = None  # type: ignore[misc]

    def test_backward_compat_existing_message_unchanged(self) -> None:
        """Existing Message creation without content_blocks still works."""
        msg = Message(role="user", content="hello")
        d = msg.to_dict()
        assert d == {"role": "user", "content": "hello"}
        assert msg.content_blocks is None
