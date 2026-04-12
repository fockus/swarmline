"""Tests for native tool calling types and converters.

Unit tests for NativeToolCall, NativeToolCallResult, NativeToolCallAdapter protocol,
and provider-specific converter functions (toolspecs_to_anthropic/openai/google).
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarmline.domain_types import ToolSpec


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _sample_toolspecs() -> list[ToolSpec]:
    """Create sample ToolSpec list for converter tests."""
    return [
        ToolSpec(
            name="calculator",
            description="Evaluate a math expression",
            parameters={
                "type": "object",
                "properties": {"expr": {"type": "string"}},
                "required": ["expr"],
            },
        ),
        ToolSpec(
            name="search",
            description="Search the web",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Domain type tests
# ---------------------------------------------------------------------------


class TestNativeToolCall:
    """Tests for NativeToolCall frozen dataclass."""

    def test_native_tool_call_creation_with_defaults(self) -> None:
        from swarmline.runtime.thin.native_tools import NativeToolCall

        tc = NativeToolCall(id="tc1", name="calculator")
        assert tc.id == "tc1"
        assert tc.name == "calculator"
        assert tc.args == {}

    def test_native_tool_call_creation_with_args(self) -> None:
        from swarmline.runtime.thin.native_tools import NativeToolCall

        tc = NativeToolCall(id="tc1", name="calculator", args={"expr": "2+2"})
        assert tc.args == {"expr": "2+2"}

    def test_native_tool_call_frozen(self) -> None:
        from swarmline.runtime.thin.native_tools import NativeToolCall

        tc = NativeToolCall(id="tc1", name="calculator")
        with pytest.raises(FrozenInstanceError):
            tc.name = "other"  # type: ignore[misc]


class TestNativeToolCallResult:
    """Tests for NativeToolCallResult frozen dataclass."""

    def test_native_tool_call_result_defaults(self) -> None:
        from swarmline.runtime.thin.native_tools import NativeToolCallResult

        result = NativeToolCallResult()
        assert result.text == ""
        assert result.tool_calls == ()
        assert result.stop_reason == "end_turn"

    def test_native_tool_call_result_with_tool_calls(self) -> None:
        from swarmline.runtime.thin.native_tools import NativeToolCall, NativeToolCallResult

        tc = NativeToolCall(id="tc1", name="calculator", args={"expr": "2+2"})
        result = NativeToolCallResult(text="let me calculate", tool_calls=(tc,))
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "calculator"

    def test_native_tool_call_result_frozen(self) -> None:
        from swarmline.runtime.thin.native_tools import NativeToolCallResult

        result = NativeToolCallResult()
        with pytest.raises(FrozenInstanceError):
            result.text = "modified"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Converter tests
# ---------------------------------------------------------------------------


class TestToolspecConverters:
    """Tests for ToolSpec-to-provider format converters."""

    def test_toolspecs_to_anthropic_format(self) -> None:
        from swarmline.runtime.thin.native_tools import toolspecs_to_anthropic

        specs = _sample_toolspecs()
        result = toolspecs_to_anthropic(specs)

        assert len(result) == 2
        assert result[0] == {
            "name": "calculator",
            "description": "Evaluate a math expression",
            "input_schema": {
                "type": "object",
                "properties": {"expr": {"type": "string"}},
                "required": ["expr"],
            },
        }
        assert result[1]["name"] == "search"

    def test_toolspecs_to_openai_format(self) -> None:
        from swarmline.runtime.thin.native_tools import toolspecs_to_openai

        specs = _sample_toolspecs()
        result = toolspecs_to_openai(specs)

        assert len(result) == 2
        assert result[0] == {
            "type": "function",
            "function": {
                "name": "calculator",
                "description": "Evaluate a math expression",
                "parameters": {
                    "type": "object",
                    "properties": {"expr": {"type": "string"}},
                    "required": ["expr"],
                },
            },
        }
        assert result[1]["type"] == "function"
        assert result[1]["function"]["name"] == "search"

    def test_toolspecs_to_google_format(self) -> None:
        from swarmline.runtime.thin.native_tools import toolspecs_to_google

        specs = _sample_toolspecs()
        result = toolspecs_to_google(specs)

        assert len(result) == 2
        assert result[0] == {
            "name": "calculator",
            "description": "Evaluate a math expression",
            "parameters": {
                "type": "object",
                "properties": {"expr": {"type": "string"}},
                "required": ["expr"],
            },
        }

    def test_toolspecs_to_anthropic_empty_list(self) -> None:
        from swarmline.runtime.thin.native_tools import toolspecs_to_anthropic

        assert toolspecs_to_anthropic([]) == []

    def test_toolspecs_to_openai_empty_list(self) -> None:
        from swarmline.runtime.thin.native_tools import toolspecs_to_openai

        assert toolspecs_to_openai([]) == []

    def test_toolspecs_to_google_empty_list(self) -> None:
        from swarmline.runtime.thin.native_tools import toolspecs_to_google

        assert toolspecs_to_google([]) == []


# ---------------------------------------------------------------------------
# Adapter call_with_tools tests (mock SDKs)
# ---------------------------------------------------------------------------


class TestAnthropicAdapterCallWithTools:
    """Test AnthropicAdapter.call_with_tools with mocked anthropic SDK."""

    @pytest.mark.asyncio
    async def test_anthropic_adapter_call_with_tools_text_only(self) -> None:
        """call_with_tools returns text when no tool_use blocks."""
        from swarmline.runtime.thin.native_tools import NativeToolCallResult

        mock_text_block = MagicMock()
        mock_text_block.text = "Hello world"
        mock_text_block.type = "text"

        mock_response = MagicMock()
        mock_response.content = [mock_text_block]
        mock_response.stop_reason = "end_turn"

        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            from swarmline.runtime.thin.llm_providers import AnthropicAdapter

            adapter = AnthropicAdapter.__new__(AnthropicAdapter)
            adapter._model = "claude-sonnet-4-20250514"
            adapter._base_url = None
            adapter._client = mock_client

            result = await adapter.call_with_tools(
                messages=[{"role": "user", "content": "Hello"}],
                system_prompt="test",
                tools=[],
            )

        assert isinstance(result, NativeToolCallResult)
        assert result.text == "Hello world"
        assert result.tool_calls == ()
        assert result.stop_reason == "end_turn"

    @pytest.mark.asyncio
    async def test_anthropic_adapter_call_with_tools_tool_use(self) -> None:
        """call_with_tools returns tool calls from tool_use blocks."""
        from swarmline.runtime.thin.native_tools import NativeToolCallResult

        mock_tool_block = MagicMock()
        mock_tool_block.type = "tool_use"
        mock_tool_block.id = "toolu_123"
        mock_tool_block.name = "calculator"
        mock_tool_block.input = {"expr": "2+2"}
        # Ensure hasattr(block, "text") returns False
        del mock_tool_block.text

        mock_response = MagicMock()
        mock_response.content = [mock_tool_block]
        mock_response.stop_reason = "tool_use"

        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            from swarmline.runtime.thin.llm_providers import AnthropicAdapter

            adapter = AnthropicAdapter.__new__(AnthropicAdapter)
            adapter._model = "claude-sonnet-4-20250514"
            adapter._base_url = None
            adapter._client = mock_client

            result = await adapter.call_with_tools(
                messages=[{"role": "user", "content": "calc 2+2"}],
                system_prompt="test",
                tools=[{"name": "calculator", "description": "calc", "input_schema": {}}],
            )

        assert isinstance(result, NativeToolCallResult)
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id == "toolu_123"
        assert result.tool_calls[0].name == "calculator"
        assert result.tool_calls[0].args == {"expr": "2+2"}
        assert result.stop_reason == "tool_use"


class TestOpenAIAdapterCallWithTools:
    """Test OpenAICompatAdapter.call_with_tools with mocked openai SDK."""

    @pytest.mark.asyncio
    async def test_openai_adapter_call_with_tools_text_only(self) -> None:
        """call_with_tools returns text when no tool calls."""
        from swarmline.runtime.thin.native_tools import NativeToolCallResult

        mock_message = MagicMock()
        mock_message.content = "Hello world"
        mock_message.tool_calls = None

        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_choice.finish_reason = "stop"

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat = MagicMock()
        mock_client.chat.completions = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.dict("sys.modules", {"openai": MagicMock()}):
            from swarmline.runtime.thin.llm_providers import OpenAICompatAdapter

            adapter = OpenAICompatAdapter.__new__(OpenAICompatAdapter)
            adapter._model = "gpt-4o"
            adapter._base_url = None
            adapter._client = mock_client

            result = await adapter.call_with_tools(
                messages=[{"role": "user", "content": "Hello"}],
                system_prompt="test",
                tools=[],
            )

        assert isinstance(result, NativeToolCallResult)
        assert result.text == "Hello world"
        assert result.tool_calls == ()

    @pytest.mark.asyncio
    async def test_openai_adapter_call_with_tools_tool_calls(self) -> None:
        """call_with_tools returns parsed tool calls."""
        from swarmline.runtime.thin.native_tools import NativeToolCallResult

        mock_tc = MagicMock()
        mock_tc.id = "call_abc123"
        mock_tc.function = MagicMock()
        mock_tc.function.name = "calculator"
        mock_tc.function.arguments = json.dumps({"expr": "2+2"})

        mock_message = MagicMock()
        mock_message.content = ""
        mock_message.tool_calls = [mock_tc]

        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_choice.finish_reason = "tool_calls"

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat = MagicMock()
        mock_client.chat.completions = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.dict("sys.modules", {"openai": MagicMock()}):
            from swarmline.runtime.thin.llm_providers import OpenAICompatAdapter

            adapter = OpenAICompatAdapter.__new__(OpenAICompatAdapter)
            adapter._model = "gpt-4o"
            adapter._base_url = None
            adapter._client = mock_client

            result = await adapter.call_with_tools(
                messages=[{"role": "user", "content": "calc 2+2"}],
                system_prompt="test",
                tools=[{"type": "function", "function": {"name": "calculator", "parameters": {}}}],
            )

        assert isinstance(result, NativeToolCallResult)
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id == "call_abc123"
        assert result.tool_calls[0].name == "calculator"
        assert result.tool_calls[0].args == {"expr": "2+2"}


class TestGoogleAdapterCallWithTools:
    """Test GoogleAdapter.call_with_tools with mocked google SDK."""

    @pytest.mark.asyncio
    async def test_google_adapter_call_with_tools_text_only(self) -> None:
        """call_with_tools returns text when no function calls."""
        from swarmline.runtime.thin.native_tools import NativeToolCallResult

        mock_text_part = MagicMock()
        mock_text_part.text = "Hello world"
        del mock_text_part.function_call  # no function_call attribute

        mock_candidate = MagicMock()
        mock_candidate.content = MagicMock()
        mock_candidate.content.parts = [mock_text_part]

        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]

        mock_generate = AsyncMock(return_value=mock_response)

        mock_genai = MagicMock()
        mock_genai.types = MagicMock()
        mock_genai.types.FunctionDeclaration = MagicMock()
        mock_genai.types.Tool = MagicMock()
        mock_genai.types.GenerateContentConfig = MagicMock(return_value=MagicMock())

        mock_client = MagicMock()
        mock_client.aio = MagicMock()
        mock_client.aio.models = MagicMock()
        mock_client.aio.models.generate_content = mock_generate

        with patch.dict("sys.modules", {"google": MagicMock(), "google.genai": mock_genai}):
            from swarmline.runtime.thin.llm_providers import GoogleAdapter

            adapter = GoogleAdapter.__new__(GoogleAdapter)
            adapter._model = "gemini-2.5-pro"
            adapter._base_url = None
            adapter._client = mock_client

            result = await adapter.call_with_tools(
                messages=[{"role": "user", "content": "Hello"}],
                system_prompt="test",
                tools=[{"name": "calculator", "description": "calc", "parameters": {}}],
            )

        assert isinstance(result, NativeToolCallResult)
        assert result.text == "Hello world"
        assert result.tool_calls == ()

    @pytest.mark.asyncio
    async def test_google_adapter_call_with_tools_function_call(self) -> None:
        """call_with_tools returns tool calls from function_call parts."""
        from swarmline.runtime.thin.native_tools import NativeToolCallResult

        mock_fc = MagicMock()
        mock_fc.id = "google_0"
        mock_fc.name = "calculator"
        mock_fc.args = {"expr": "2+2"}

        mock_fc_part = MagicMock()
        mock_fc_part.text = None
        mock_fc_part.function_call = mock_fc

        mock_candidate = MagicMock()
        mock_candidate.content = MagicMock()
        mock_candidate.content.parts = [mock_fc_part]

        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]

        mock_generate = AsyncMock(return_value=mock_response)

        mock_genai = MagicMock()
        mock_genai.types = MagicMock()
        mock_genai.types.FunctionDeclaration = MagicMock()
        mock_genai.types.Tool = MagicMock()
        mock_genai.types.GenerateContentConfig = MagicMock(return_value=MagicMock())

        mock_client = MagicMock()
        mock_client.aio = MagicMock()
        mock_client.aio.models = MagicMock()
        mock_client.aio.models.generate_content = mock_generate

        with patch.dict("sys.modules", {"google": MagicMock(), "google.genai": mock_genai}):
            from swarmline.runtime.thin.llm_providers import GoogleAdapter

            adapter = GoogleAdapter.__new__(GoogleAdapter)
            adapter._model = "gemini-2.5-pro"
            adapter._base_url = None
            adapter._client = mock_client

            result = await adapter.call_with_tools(
                messages=[{"role": "user", "content": "calc 2+2"}],
                system_prompt="test",
                tools=[{"name": "calculator", "description": "calc", "parameters": {}}],
            )

        assert isinstance(result, NativeToolCallResult)
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "calculator"
        assert result.tool_calls[0].args == {"expr": "2+2"}
