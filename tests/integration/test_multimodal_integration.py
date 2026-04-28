"""Integration tests for Phase 16: Multimodal Input pipeline.

Tests verify content_blocks flow through the full pipeline:
domain types → _messages_to_lm → _filter_chat_messages → provider adapters.
"""

from __future__ import annotations

import base64
import json
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarmline.domain_types import ImageBlock, Message, TextBlock

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# ContentBlock domain type round-trip
# ---------------------------------------------------------------------------


class TestContentBlocksSerialization:
    """content_blocks serialize and deserialize correctly through Message.to_dict()."""

    def test_message_to_dict_includes_content_blocks(self) -> None:
        msg = Message(
            role="user",
            content="What is this?",
            content_blocks=[
                TextBlock(text="What is this?"),
                ImageBlock(data="aW1hZ2U=", media_type="image/png"),
            ],
        )
        d = msg.to_dict()
        assert "content_blocks" in d
        assert len(d["content_blocks"]) == 2
        assert d["content_blocks"][0] == {"type": "text", "text": "What is this?"}
        assert d["content_blocks"][1] == {
            "type": "image",
            "data": "aW1hZ2U=",
            "media_type": "image/png",
        }

    def test_message_to_dict_omits_content_blocks_when_none(self) -> None:
        msg = Message(role="user", content="hi")
        d = msg.to_dict()
        assert "content_blocks" not in d

    def test_content_blocks_round_trip_preserves_data(self) -> None:
        original_data = base64.b64encode(b"fake png bytes").decode()
        msg = Message(
            role="user",
            content="Analyze image",
            content_blocks=[
                TextBlock(text="Analyze image"),
                ImageBlock(data=original_data, media_type="image/png"),
            ],
        )
        serialized = msg.to_dict()
        # Verify round-trip preserves base64 data
        assert serialized["content_blocks"][1]["data"] == original_data
        assert (
            base64.b64decode(serialized["content_blocks"][1]["data"])
            == b"fake png bytes"
        )


# ---------------------------------------------------------------------------
# _messages_to_lm pipeline
# ---------------------------------------------------------------------------


class TestMessagesToLmPipeline:
    """_messages_to_lm includes content_blocks when present."""

    def test_messages_to_lm_includes_content_blocks(self) -> None:
        from swarmline.runtime.thin.helpers import _messages_to_lm

        msg = Message(
            role="user",
            content="Describe this",
            content_blocks=[
                TextBlock(text="Describe this"),
                ImageBlock(data="abc123", media_type="image/jpeg"),
            ],
        )
        result = _messages_to_lm([msg])
        assert len(result) == 1
        assert "content_blocks" in result[0]
        assert len(result[0]["content_blocks"]) == 2

    def test_messages_to_lm_omits_content_blocks_when_none(self) -> None:
        from swarmline.runtime.thin.helpers import _messages_to_lm

        msg = Message(role="user", content="just text")
        result = _messages_to_lm([msg])
        assert "content_blocks" not in result[0]


# ---------------------------------------------------------------------------
# Full pipeline: Message → _messages_to_lm → _filter → adapter conversion
# ---------------------------------------------------------------------------


def _make_mock_anthropic_module() -> MagicMock:
    mock_module = MagicMock()
    mock_module.AsyncAnthropic.return_value = AsyncMock()
    mock_module.AuthenticationError = type("AuthenticationError", (Exception,), {})
    mock_module.APIConnectionError = type("APIConnectionError", (Exception,), {})
    mock_module.APIStatusError = type("APIStatusError", (Exception,), {})
    return mock_module


def _make_mock_openai_module() -> MagicMock:
    mock_module = MagicMock()
    mock_module.AsyncOpenAI.return_value = AsyncMock()
    return mock_module


def _make_mock_google_module() -> MagicMock:
    mock_module = MagicMock()
    mock_types = MagicMock()
    mock_types.HttpOptions = MagicMock(side_effect=lambda **kwargs: kwargs)
    mock_module.types = mock_types
    mock_module.Client.return_value = MagicMock()
    return mock_module


def _make_mock_google_package(genai_module: MagicMock) -> types.ModuleType:
    google_pkg = types.ModuleType("google")
    google_pkg.genai = genai_module  # type: ignore[attr-defined]
    return google_pkg


class TestAnthropicPipelineIntegration:
    """Message with content_blocks flows through to Anthropic API call."""

    @pytest.mark.asyncio
    async def test_content_blocks_reach_anthropic_api(self) -> None:
        from swarmline.runtime.thin.helpers import _messages_to_lm
        from swarmline.runtime.thin.llm_providers import AnthropicAdapter

        mock_module = _make_mock_anthropic_module()
        mock_client = AsyncMock()
        mock_block = MagicMock()
        mock_block.text = "I see a cat"
        mock_response = MagicMock()
        mock_response.content = [mock_block]
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        msg = Message(
            role="user",
            content="What is this?",
            content_blocks=[
                TextBlock(text="What is this?"),
                ImageBlock(data="aW1hZ2U=", media_type="image/png"),
            ],
        )
        lm_messages = _messages_to_lm([msg])

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            result = await adapter.call(
                messages=lm_messages, system_prompt="Describe images"
            )

        assert result == "I see a cat"
        call_kwargs = mock_client.messages.create.call_args.kwargs
        api_msg = call_kwargs["messages"][0]
        # content should be a list (multipart), not a string
        assert isinstance(api_msg["content"], list)
        assert api_msg["content"][0] == {"type": "text", "text": "What is this?"}
        assert api_msg["content"][1]["type"] == "image"
        assert api_msg["content"][1]["source"]["type"] == "base64"
        assert api_msg["content"][1]["source"]["media_type"] == "image/png"
        assert api_msg["content"][1]["source"]["data"] == "aW1hZ2U="


class TestOpenAIPipelineIntegration:
    """Message with content_blocks flows through to OpenAI API call."""

    @pytest.mark.asyncio
    async def test_content_blocks_reach_openai_api(self) -> None:
        from swarmline.runtime.thin.helpers import _messages_to_lm
        from swarmline.runtime.thin.llm_providers import OpenAICompatAdapter

        mock_module = _make_mock_openai_module()
        mock_client = AsyncMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "I see a dog"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        msg = Message(
            role="user",
            content="What is this?",
            content_blocks=[
                TextBlock(text="What is this?"),
                ImageBlock(data="aW1hZ2U=", media_type="image/jpeg"),
            ],
        )
        lm_messages = _messages_to_lm([msg])

        with patch.dict("sys.modules", {"openai": mock_module}):
            adapter = OpenAICompatAdapter(model="gpt-4o")
            adapter._client = mock_client
            result = await adapter.call(
                messages=lm_messages, system_prompt="Describe images"
            )

        assert result == "I see a dog"
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        # messages[0] = system, messages[1] = user
        user_msg = call_kwargs["messages"][1]
        assert isinstance(user_msg["content"], list)
        assert user_msg["content"][0] == {"type": "text", "text": "What is this?"}
        assert user_msg["content"][1]["type"] == "image_url"
        assert (
            user_msg["content"][1]["image_url"]["url"]
            == "data:image/jpeg;base64,aW1hZ2U="
        )


class TestGooglePipelineIntegration:
    """Message with content_blocks flows through to Google API call."""

    @pytest.mark.asyncio
    async def test_content_blocks_reach_google_api(self) -> None:
        from swarmline.runtime.thin.helpers import _messages_to_lm
        from swarmline.runtime.thin.llm_providers import GoogleAdapter

        mock_module = _make_mock_google_module()
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "I see a bird"
        mock_client.models.generate_content = AsyncMock(return_value=mock_response)

        msg = Message(
            role="user",
            content="What is this?",
            content_blocks=[
                TextBlock(text="What is this?"),
                ImageBlock(data="aW1hZ2U=", media_type="image/webp"),
            ],
        )
        lm_messages = _messages_to_lm([msg])

        with patch.dict(
            "sys.modules",
            {
                "google.genai": mock_module,
                "google": _make_mock_google_package(mock_module),
            },
        ):
            adapter = GoogleAdapter(model="gemini-2.5-pro")
            adapter._client = mock_client
            result = await adapter.call(
                messages=lm_messages, system_prompt="Describe images"
            )

        assert result == "I see a bird"
        call_kwargs = mock_client.models.generate_content.call_args.kwargs
        contents = call_kwargs["contents"]
        parts = contents[0]["parts"]
        assert len(parts) == 2
        assert parts[0] == {"text": "What is this?"}
        assert parts[1] == {
            "inline_data": {"mime_type": "image/webp", "data": "aW1hZ2U="}
        }


# ---------------------------------------------------------------------------
# Backward compatibility: messages without content_blocks
# ---------------------------------------------------------------------------


class TestBackwardCompatIntegration:
    """Messages without content_blocks still work as before across all adapters."""

    @pytest.mark.asyncio
    async def test_anthropic_plain_text_unchanged(self) -> None:
        from swarmline.runtime.thin.helpers import _messages_to_lm
        from swarmline.runtime.thin.llm_providers import AnthropicAdapter

        mock_module = _make_mock_anthropic_module()
        mock_client = AsyncMock()
        mock_block = MagicMock()
        mock_block.text = "Hello"
        mock_client.messages.create = AsyncMock(
            return_value=MagicMock(content=[mock_block])
        )

        msg = Message(role="user", content="hi there")
        lm_messages = _messages_to_lm([msg])

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            result = await adapter.call(messages=lm_messages, system_prompt="test")

        assert result == "Hello"
        call_kwargs = mock_client.messages.create.call_args.kwargs
        api_msg = call_kwargs["messages"][0]
        # content should remain a plain string
        assert api_msg["content"] == "hi there"

    @pytest.mark.asyncio
    async def test_openai_plain_text_unchanged(self) -> None:
        from swarmline.runtime.thin.helpers import _messages_to_lm
        from swarmline.runtime.thin.llm_providers import OpenAICompatAdapter

        mock_module = _make_mock_openai_module()
        mock_client = AsyncMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "Hi"
        mock_client.chat.completions.create = AsyncMock(
            return_value=MagicMock(choices=[mock_choice])
        )

        msg = Message(role="user", content="hello")
        lm_messages = _messages_to_lm([msg])

        with patch.dict("sys.modules", {"openai": mock_module}):
            adapter = OpenAICompatAdapter(model="gpt-4o")
            adapter._client = mock_client
            result = await adapter.call(messages=lm_messages, system_prompt="test")

        assert result == "Hi"
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        user_msg = call_kwargs["messages"][1]
        assert user_msg["content"] == "hello"

    @pytest.mark.asyncio
    async def test_google_plain_text_unchanged(self) -> None:
        from swarmline.runtime.thin.helpers import _messages_to_lm
        from swarmline.runtime.thin.llm_providers import GoogleAdapter

        mock_module = _make_mock_google_module()
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Greetings"
        mock_client.models.generate_content = AsyncMock(return_value=mock_response)

        msg = Message(role="user", content="hey")
        lm_messages = _messages_to_lm([msg])

        with patch.dict(
            "sys.modules",
            {
                "google.genai": mock_module,
                "google": _make_mock_google_package(mock_module),
            },
        ):
            adapter = GoogleAdapter(model="gemini-2.5-pro")
            adapter._client = mock_client
            result = await adapter.call(messages=lm_messages, system_prompt="test")

        assert result == "Greetings"
        call_kwargs = mock_client.models.generate_content.call_args.kwargs
        contents = call_kwargs["contents"]
        parts = contents[0]["parts"]
        assert parts == [{"text": "hey"}]


# ---------------------------------------------------------------------------
# Read tool image detection (mock filesystem)
# ---------------------------------------------------------------------------


class TestReadToolImageDetection:
    """Read tool detects image files and returns base64 data."""

    @pytest.mark.asyncio
    async def test_read_png_returns_base64_image_data(self) -> None:
        from swarmline.tools.builtin import _create_read_executor
        from swarmline.tools.protocols import SandboxProvider

        raw_bytes = b"\x89PNG\r\n\x1a\nfake_png_data"
        expected_b64 = base64.b64encode(raw_bytes).decode()

        sandbox = AsyncMock(spec=SandboxProvider)
        # Make sandbox also satisfy BinaryReadProvider
        sandbox.read_file_bytes = AsyncMock(return_value=raw_bytes)
        # isinstance check needs runtime_checkable — patch it
        with patch(
            "swarmline.tools.builtin.isinstance",
            side_effect=lambda obj, cls: True,
        ):
            executor = _create_read_executor(sandbox)
            result_json = await executor({"path": "/data/photo.png"})

        result = json.loads(result_json)
        assert result["status"] == "ok"
        assert result["type"] == "image"
        assert result["media_type"] == "image/png"
        assert result["data"] == expected_b64


# ---------------------------------------------------------------------------
# Extractors (mock imports)
# ---------------------------------------------------------------------------


class TestExtractorIntegration:
    """PDF and Jupyter extractors produce text when deps available."""

    @pytest.mark.asyncio
    async def test_pdf_extractor_missing_dep_raises(self) -> None:
        from swarmline.tools.extractors import extract_pdf

        with patch.dict("sys.modules", {"pymupdf4llm": None}):
            with pytest.raises(ImportError, match="pymupdf4llm"):
                await extract_pdf("/fake/doc.pdf")

    @pytest.mark.asyncio
    async def test_jupyter_extractor_missing_dep_raises(self) -> None:
        from swarmline.tools.extractors import extract_jupyter

        with patch.dict("sys.modules", {"nbformat": None}):
            with pytest.raises(ImportError, match="nbformat"):
                await extract_jupyter("/fake/notebook.ipynb")
