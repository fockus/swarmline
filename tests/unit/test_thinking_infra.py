"""Unit tests: Thinking Events — infrastructure wiring (Phase 15, Task 2).

AnthropicAdapter thinking extraction, default_llm_call thinking pass-through,
run_buffered/try_stream LlmCallResult handling, strategy thinking_delta emission,
ThinRuntime non-Anthropic warning.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarmline.domain_types import RuntimeEvent, ThinkingConfig
from swarmline.runtime.thin.llm_client import (
    BufferedLlmAttempt,
    LlmCallResult,
    default_llm_call,
    run_buffered_llm_call,
    try_stream_llm_call,
)
from swarmline.runtime.thin.llm_providers import AnthropicAdapter
from swarmline.runtime.types import RuntimeConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_anthropic_module() -> MagicMock:
    mock_module = MagicMock()
    mock_module.AsyncAnthropic.return_value = AsyncMock()
    mock_module.AuthenticationError = type("AuthenticationError", (Exception,), {})
    mock_module.APIConnectionError = type("APIConnectionError", (Exception,), {})
    mock_module.APIStatusError = type("APIStatusError", (Exception,), {})
    return mock_module


@pytest.fixture(autouse=True)
def _clear_adapter_cache() -> None:
    from swarmline.runtime.thin.llm_providers import _adapter_cache

    _adapter_cache.clear()
    yield
    _adapter_cache.clear()


# ---------------------------------------------------------------------------
# AnthropicAdapter.call() — thinking extraction
# ---------------------------------------------------------------------------


class TestAnthropicAdapterThinking:
    """AnthropicAdapter.call() extracts thinking blocks when _thinking_config passed."""

    @pytest.fixture
    def mock_anthropic_with_thinking(self):
        mock_module = _make_mock_anthropic_module()
        mock_client = AsyncMock()

        thinking_block = MagicMock(spec=["type", "thinking"])
        thinking_block.type = "thinking"
        thinking_block.thinking = "Let me reason about this..."

        text_block = MagicMock(spec=["type", "text"])
        text_block.type = "text"
        text_block.text = "The answer is 42."

        mock_response = MagicMock()
        mock_response.content = [thinking_block, text_block]
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_module.AsyncAnthropic.return_value = mock_client
        return mock_module, mock_client

    @pytest.fixture
    def mock_anthropic_no_thinking(self):
        mock_module = _make_mock_anthropic_module()
        mock_client = AsyncMock()

        text_block = MagicMock(spec=["type", "text"])
        text_block.type = "text"
        text_block.text = "Simple answer."

        mock_response = MagicMock()
        mock_response.content = [text_block]
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_module.AsyncAnthropic.return_value = mock_client
        return mock_module, mock_client

    @pytest.mark.asyncio
    async def test_call_with_thinking_config_sends_thinking_param(
        self, mock_anthropic_with_thinking
    ) -> None:
        mock_module, mock_client = mock_anthropic_with_thinking
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            await adapter.call(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="test",
                _thinking_config=ThinkingConfig(budget_tokens=5000),
            )
            kwargs = mock_client.messages.create.call_args.kwargs
            assert kwargs["thinking"] == {
                "type": "enabled",
                "budget_tokens": 5000,
            }

    @pytest.mark.asyncio
    async def test_call_with_thinking_returns_llm_call_result(
        self, mock_anthropic_with_thinking
    ) -> None:
        mock_module, mock_client = mock_anthropic_with_thinking
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            result = await adapter.call(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="test",
                _thinking_config=ThinkingConfig(budget_tokens=5000),
            )
            assert isinstance(result, LlmCallResult)
            assert result.text == "The answer is 42."
            assert result.thinking == "Let me reason about this..."

    @pytest.mark.asyncio
    async def test_call_without_thinking_config_returns_str(
        self, mock_anthropic_no_thinking
    ) -> None:
        mock_module, mock_client = mock_anthropic_no_thinking
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            result = await adapter.call(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="test",
            )
            assert isinstance(result, str)
            assert result == "Simple answer."

    @pytest.mark.asyncio
    async def test_call_with_thinking_config_but_no_thinking_blocks_returns_str(
        self, mock_anthropic_no_thinking
    ) -> None:
        """When thinking is requested but model returns no thinking blocks."""
        mock_module, mock_client = mock_anthropic_no_thinking
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            result = await adapter.call(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="test",
                _thinking_config=ThinkingConfig(budget_tokens=5000),
            )
            assert isinstance(result, str)
            assert result == "Simple answer."

    @pytest.mark.asyncio
    async def test_call_with_thinking_does_not_pass_max_tokens(
        self, mock_anthropic_with_thinking
    ) -> None:
        """When thinking enabled, max_tokens must still be set (Anthropic requires it)."""
        mock_module, mock_client = mock_anthropic_with_thinking
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            await adapter.call(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="test",
                _thinking_config=ThinkingConfig(budget_tokens=5000),
            )
            kwargs = mock_client.messages.create.call_args.kwargs
            assert "max_tokens" in kwargs

    @pytest.mark.asyncio
    async def test_call_with_thinking_multiple_thinking_blocks(self) -> None:
        """Multiple thinking blocks are concatenated."""
        mock_module = _make_mock_anthropic_module()
        mock_client = AsyncMock()

        think1 = MagicMock(spec=["type", "thinking"])
        think1.type = "thinking"
        think1.thinking = "Step 1. "

        think2 = MagicMock(spec=["type", "thinking"])
        think2.type = "thinking"
        think2.thinking = "Step 2."

        text_block = MagicMock(spec=["type", "text"])
        text_block.type = "text"
        text_block.text = "Done."

        mock_response = MagicMock()
        mock_response.content = [think1, think2, text_block]
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_module.AsyncAnthropic.return_value = mock_client

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            result = await adapter.call(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="test",
                _thinking_config=ThinkingConfig(budget_tokens=10000),
            )
            assert isinstance(result, LlmCallResult)
            assert result.thinking == "Step 1. Step 2."
            assert result.text == "Done."


# ---------------------------------------------------------------------------
# default_llm_call — thinking pass-through
# ---------------------------------------------------------------------------


class TestDefaultLlmCallThinking:
    """default_llm_call injects _thinking_config when config.thinking is set."""

    @pytest.mark.asyncio
    async def test_anthropic_with_thinking_adds_thinking_config(self) -> None:
        tc = ThinkingConfig(budget_tokens=8000)
        config = RuntimeConfig(runtime_name="thin", model="claude-sonnet-4-20250514", thinking=tc)

        with patch(
            "swarmline.runtime.thin.llm_client.get_cached_adapter"
        ) as mock_factory, patch(
            "swarmline.runtime.thin.llm_client.resolve_provider"
        ) as mock_resolve:
            from swarmline.runtime.provider_resolver import ResolvedProvider

            mock_resolve.return_value = ResolvedProvider(
                "claude-sonnet-4-20250514", "anthropic", "anthropic", None,
            )
            mock_adapter = AsyncMock()
            mock_adapter.call = AsyncMock(return_value="response")
            mock_factory.return_value = mock_adapter

            await default_llm_call(
                config,
                [{"role": "user", "content": "hi"}],
                "system",
            )
            call_kwargs = mock_adapter.call.call_args.kwargs
            assert "_thinking_config" in call_kwargs
            assert call_kwargs["_thinking_config"] is tc

    @pytest.mark.asyncio
    async def test_anthropic_with_thinking_disables_stream(self) -> None:
        """When thinking is set, stream kwarg must be popped (thinking API is non-streaming)."""
        tc = ThinkingConfig(budget_tokens=8000)
        config = RuntimeConfig(runtime_name="thin", model="claude-sonnet-4-20250514", thinking=tc)

        with patch(
            "swarmline.runtime.thin.llm_client.get_cached_adapter"
        ) as mock_factory, patch(
            "swarmline.runtime.thin.llm_client.resolve_provider"
        ) as mock_resolve:
            from swarmline.runtime.provider_resolver import ResolvedProvider

            mock_resolve.return_value = ResolvedProvider(
                "claude-sonnet-4-20250514", "anthropic", "anthropic", None,
            )
            mock_adapter = AsyncMock()
            llm_result = LlmCallResult(text="answer", thinking="thought")
            mock_adapter.call = AsyncMock(return_value=llm_result)
            mock_factory.return_value = mock_adapter

            result = await default_llm_call(
                config,
                [{"role": "user", "content": "hi"}],
                "system",
                stream=True,
            )
            # Should call adapter.call (not stream) and return LlmCallResult
            mock_adapter.call.assert_called_once()
            assert isinstance(result, LlmCallResult)

    @pytest.mark.asyncio
    async def test_non_anthropic_with_thinking_no_thinking_config(self) -> None:
        """Non-anthropic provider should NOT receive _thinking_config."""
        tc = ThinkingConfig(budget_tokens=8000)
        config = RuntimeConfig(runtime_name="thin", model="openai:gpt-4o", thinking=tc)

        with patch(
            "swarmline.runtime.thin.llm_client.get_cached_adapter"
        ) as mock_factory, patch(
            "swarmline.runtime.thin.llm_client.resolve_provider"
        ) as mock_resolve:
            from swarmline.runtime.provider_resolver import ResolvedProvider

            mock_resolve.return_value = ResolvedProvider(
                "gpt-4o", "openai", "openai_compat", None,
            )
            mock_adapter = AsyncMock()
            mock_adapter.call = AsyncMock(return_value="response")
            mock_factory.return_value = mock_adapter

            await default_llm_call(
                config,
                [{"role": "user", "content": "hi"}],
                "system",
            )
            call_kwargs = mock_adapter.call.call_args.kwargs
            assert "_thinking_config" not in call_kwargs

    @pytest.mark.asyncio
    async def test_no_thinking_config_backward_compat(self) -> None:
        """Without thinking config, behavior unchanged."""
        config = RuntimeConfig(runtime_name="thin", model="claude-sonnet-4-20250514")

        with patch(
            "swarmline.runtime.thin.llm_client.get_cached_adapter"
        ) as mock_factory:
            mock_adapter = AsyncMock()
            mock_adapter.call = AsyncMock(return_value="response")
            mock_factory.return_value = mock_adapter

            result = await default_llm_call(
                config,
                [{"role": "user", "content": "hi"}],
                "system",
            )
            assert isinstance(result, str)
            call_kwargs = mock_adapter.call.call_args.kwargs
            assert "_thinking_config" not in call_kwargs

    @pytest.mark.asyncio
    async def test_llm_call_result_returned_as_is(self) -> None:
        """When adapter returns LlmCallResult, default_llm_call returns it as-is."""
        tc = ThinkingConfig(budget_tokens=8000)
        config = RuntimeConfig(runtime_name="thin", model="claude-sonnet-4-20250514", thinking=tc)

        with patch(
            "swarmline.runtime.thin.llm_client.get_cached_adapter"
        ) as mock_factory, patch(
            "swarmline.runtime.thin.llm_client.resolve_provider"
        ) as mock_resolve:
            from swarmline.runtime.provider_resolver import ResolvedProvider

            mock_resolve.return_value = ResolvedProvider(
                "claude-sonnet-4-20250514", "anthropic", "anthropic", None,
            )
            mock_adapter = AsyncMock()
            llm_result = LlmCallResult(text="answer", thinking="thought")
            mock_adapter.call = AsyncMock(return_value=llm_result)
            mock_factory.return_value = mock_adapter

            result = await default_llm_call(
                config,
                [{"role": "user", "content": "hi"}],
                "system",
            )
            assert isinstance(result, LlmCallResult)
            assert result.text == "answer"
            assert result.thinking == "thought"


# ---------------------------------------------------------------------------
# run_buffered_llm_call — LlmCallResult handling
# ---------------------------------------------------------------------------


class TestRunBufferedLlmCallThinking:
    """run_buffered_llm_call handles LlmCallResult from llm_call."""

    @pytest.mark.asyncio
    async def test_llm_call_result_produces_thinking_attempt(self) -> None:
        llm_result = LlmCallResult(text="answer", thinking="thought")
        mock_llm_call = AsyncMock(return_value=llm_result)

        attempt = await run_buffered_llm_call(
            mock_llm_call,
            [{"role": "user", "content": "hi"}],
            "system",
        )
        assert isinstance(attempt, BufferedLlmAttempt)
        assert attempt.raw == "answer"
        assert attempt.thinking == "thought"
        assert attempt.used_stream is False

    @pytest.mark.asyncio
    async def test_llm_call_result_without_thinking(self) -> None:
        llm_result = LlmCallResult(text="answer", thinking=None)
        mock_llm_call = AsyncMock(return_value=llm_result)

        attempt = await run_buffered_llm_call(
            mock_llm_call,
            [{"role": "user", "content": "hi"}],
            "system",
        )
        assert attempt.raw == "answer"
        assert attempt.thinking is None

    @pytest.mark.asyncio
    async def test_plain_str_result_no_thinking(self) -> None:
        """Plain str result — backward compat, no thinking."""
        mock_llm_call = AsyncMock(return_value="plain text")

        attempt = await run_buffered_llm_call(
            mock_llm_call,
            [{"role": "user", "content": "hi"}],
            "system",
        )
        assert attempt.raw == "plain text"
        assert attempt.thinking is None


# ---------------------------------------------------------------------------
# try_stream_llm_call — LlmCallResult handling
# ---------------------------------------------------------------------------


class TestTryStreamLlmCallThinking:
    """try_stream_llm_call handles LlmCallResult."""

    @pytest.mark.asyncio
    async def test_llm_call_result_returned_as_text(self) -> None:
        """LlmCallResult treated as non-stream text response."""
        llm_result = LlmCallResult(text="answer", thinking="thought")
        mock_llm_call = AsyncMock(return_value=llm_result)

        result = await try_stream_llm_call(
            mock_llm_call,
            [{"role": "user", "content": "hi"}],
            "system",
        )
        assert result is not None
        chunks, full = result
        assert chunks == ["answer"]
        assert full == "answer"

    @pytest.mark.asyncio
    async def test_plain_str_still_works(self) -> None:
        mock_llm_call = AsyncMock(return_value="text")
        result = await try_stream_llm_call(
            mock_llm_call,
            [{"role": "user", "content": "hi"}],
            "system",
        )
        assert result is not None
        chunks, full = result
        assert chunks == ["text"]
        assert full == "text"


# ---------------------------------------------------------------------------
# Strategy: run_conversational — thinking_delta emission
# ---------------------------------------------------------------------------


class TestConversationalThinkingDelta:
    """run_conversational emits thinking_delta when attempt has thinking."""

    @pytest.mark.asyncio
    async def test_thinking_delta_emitted_before_text(self) -> None:
        # LLM returns a valid JSON envelope with thinking
        import json

        from swarmline.runtime.thin.conversational import run_conversational

        envelope = json.dumps({
            "type": "final",
            "final_message": "The answer is 42.",
        })
        llm_result = LlmCallResult(text=envelope, thinking="Let me think...")
        mock_llm_call = AsyncMock(return_value=llm_result)

        config = RuntimeConfig(
            runtime_name="thin",
            model="claude-sonnet-4-20250514",
            thinking=ThinkingConfig(budget_tokens=5000),
        )

        events: list[RuntimeEvent] = []
        async for event in run_conversational(
            mock_llm_call,
            [],
            "system",
            config,
            0.0,
        ):
            events.append(event)

        thinking_events = [e for e in events if e.type == "thinking_delta"]
        assert len(thinking_events) == 1
        assert thinking_events[0].text == "Let me think..."

        # thinking_delta must come before final
        types = [e.type for e in events]
        thinking_idx = types.index("thinking_delta")
        final_indices = [i for i, t in enumerate(types) if t == "final"]
        assert final_indices, "Must have a final event"
        assert thinking_idx < final_indices[0]

    @pytest.mark.asyncio
    async def test_no_thinking_delta_when_no_thinking(self) -> None:
        import json

        from swarmline.runtime.thin.conversational import run_conversational

        envelope = json.dumps({
            "type": "final",
            "final_message": "Simple answer.",
        })
        mock_llm_call = AsyncMock(return_value=envelope)

        config = RuntimeConfig(runtime_name="thin", model="claude-sonnet-4-20250514")

        events: list[RuntimeEvent] = []
        async for event in run_conversational(
            mock_llm_call,
            [],
            "system",
            config,
            0.0,
        ):
            events.append(event)

        thinking_events = [e for e in events if e.type == "thinking_delta"]
        assert len(thinking_events) == 0


# ---------------------------------------------------------------------------
# Strategy: run_react — thinking_delta emission
# ---------------------------------------------------------------------------


class TestReactThinkingDelta:
    """run_react emits thinking_delta when attempt has thinking."""

    @pytest.mark.asyncio
    async def test_thinking_delta_emitted_in_react(self) -> None:
        import json

        from swarmline.runtime.thin.executor import ToolExecutor
        from swarmline.runtime.thin.react_strategy import run_react

        envelope = json.dumps({
            "type": "final",
            "final_message": "Done.",
        })
        llm_result = LlmCallResult(text=envelope, thinking="Planning steps...")
        mock_llm_call = AsyncMock(return_value=llm_result)
        mock_executor = MagicMock(spec=ToolExecutor)

        config = RuntimeConfig(
            runtime_name="thin",
            model="claude-sonnet-4-20250514",
            thinking=ThinkingConfig(budget_tokens=5000),
        )

        events: list[RuntimeEvent] = []
        async for event in run_react(
            mock_llm_call,
            mock_executor,
            [],
            "system",
            [],
            config,
            0.0,
        ):
            events.append(event)

        thinking_events = [e for e in events if e.type == "thinking_delta"]
        assert len(thinking_events) == 1
        assert thinking_events[0].text == "Planning steps..."

    @pytest.mark.asyncio
    async def test_no_thinking_delta_without_thinking_config(self) -> None:
        import json

        from swarmline.runtime.thin.executor import ToolExecutor
        from swarmline.runtime.thin.react_strategy import run_react

        envelope = json.dumps({
            "type": "final",
            "final_message": "Done.",
        })
        mock_llm_call = AsyncMock(return_value=envelope)
        mock_executor = MagicMock(spec=ToolExecutor)

        config = RuntimeConfig(runtime_name="thin", model="claude-sonnet-4-20250514")

        events: list[RuntimeEvent] = []
        async for event in run_react(
            mock_llm_call,
            mock_executor,
            [],
            "system",
            [],
            config,
            0.0,
        ):
            events.append(event)

        thinking_events = [e for e in events if e.type == "thinking_delta"]
        assert len(thinking_events) == 0


# ---------------------------------------------------------------------------
# ThinRuntime.run() — non-Anthropic warning
# ---------------------------------------------------------------------------


class TestThinRuntimeThinkingWarning:
    """ThinRuntime.run() warns when thinking is set for non-Anthropic models."""

    @pytest.mark.asyncio
    async def test_non_anthropic_model_emits_warning(self) -> None:
        import json

        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import Message

        envelope = json.dumps({
            "type": "final",
            "final_message": "Hello.",
        })

        async def mock_llm_call(*args, **kwargs):
            return envelope

        config = RuntimeConfig(
            runtime_name="thin",
            model="openai:gpt-4o",
            thinking=ThinkingConfig(budget_tokens=5000),
        )

        rt = ThinRuntime(config=config, llm_call=mock_llm_call)

        events: list[RuntimeEvent] = []
        async for event in rt.run(
            messages=[Message(role="user", content="hi")],
            system_prompt="test",
            active_tools=[],
        ):
            events.append(event)

        warning_events = [
            e for e in events
            if e.type == "status" and "thinking" in e.text.lower()
        ]
        assert len(warning_events) >= 1

    @pytest.mark.asyncio
    async def test_anthropic_model_no_warning(self) -> None:
        import json

        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import Message

        envelope = json.dumps({
            "type": "final",
            "final_message": "Hello.",
        })

        async def mock_llm_call(*args, **kwargs):
            return envelope

        config = RuntimeConfig(
            runtime_name="thin",
            model="claude-sonnet-4-20250514",
            thinking=ThinkingConfig(budget_tokens=5000),
        )

        rt = ThinRuntime(config=config, llm_call=mock_llm_call)

        events: list[RuntimeEvent] = []
        async for event in rt.run(
            messages=[Message(role="user", content="hi")],
            system_prompt="test",
            active_tools=[],
        ):
            events.append(event)

        warning_events = [
            e for e in events
            if e.type == "status" and "thinking" in e.text.lower()
        ]
        assert len(warning_events) == 0

    @pytest.mark.asyncio
    async def test_no_thinking_config_no_warning(self) -> None:
        import json

        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import Message

        envelope = json.dumps({
            "type": "final",
            "final_message": "Hello.",
        })

        async def mock_llm_call(*args, **kwargs):
            return envelope

        config = RuntimeConfig(runtime_name="thin", model="openai:gpt-4o")

        rt = ThinRuntime(config=config, llm_call=mock_llm_call)

        events: list[RuntimeEvent] = []
        async for event in rt.run(
            messages=[Message(role="user", content="hi")],
            system_prompt="test",
            active_tools=[],
        ):
            events.append(event)

        warning_events = [
            e for e in events
            if e.type == "status" and "thinking" in e.text.lower()
        ]
        assert len(warning_events) == 0
