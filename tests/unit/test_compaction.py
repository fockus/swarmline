"""Tests for compaction strategy - noop native, token-aware portable/thin."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from swarmline.runtime.ports.base import BaseRuntimePort
from swarmline.runtime.ports.deepagents import DeepAgentsRuntimePort
from swarmline.runtime.types import RuntimeConfig


class TestNativeDeepAgentsSkipsCompaction:
    """Native DeepAgents path NE vyzyvaet nashu compaction (upstream handles it)."""

    @pytest.mark.asyncio
    async def test_native_mode_skips_summarizer(self) -> None:
        """V native_first mode _maybe_summarize() = noop."""
        mock_summarizer = MagicMock()
        mock_summarizer.asummarize = AsyncMock(return_value="summary")

        port = DeepAgentsRuntimePort(
            system_prompt="test",
            config=RuntimeConfig(
                runtime_name="deepagents",
                feature_mode="native_first",
                allow_native_features=True,
            ),
            summarizer=mock_summarizer,
        )
        for i in range(30):
            port._append_to_history("user", "x" * 100)

        await port._maybe_summarize()
        mock_summarizer.asummarize.assert_not_called()

    @pytest.mark.asyncio
    async def test_hybrid_mode_skips_summarizer(self) -> None:
        """V hybrid mode _maybe_summarize() = noop."""
        mock_summarizer = MagicMock()
        mock_summarizer.asummarize = AsyncMock(return_value="summary")

        port = DeepAgentsRuntimePort(
            system_prompt="test",
            config=RuntimeConfig(
                runtime_name="deepagents",
                feature_mode="hybrid",
                allow_native_features=True,
            ),
            summarizer=mock_summarizer,
        )
        for i in range(30):
            port._append_to_history("user", "msg")

        await port._maybe_summarize()
        mock_summarizer.asummarize.assert_not_called()


class TestPortableDeepAgentsUsesCompaction:
    """Portable DeepAgents path ispolzuet nashu compaction."""

    @pytest.mark.asyncio
    async def test_portable_mode_calls_summarizer(self) -> None:
        """V portable mode _maybe_summarize() vyzyvaet summarizer."""
        mock_summarizer = MagicMock()
        mock_summarizer.asummarize = AsyncMock(return_value="summary")

        port = DeepAgentsRuntimePort(
            system_prompt="test",
            config=RuntimeConfig(
                runtime_name="deepagents",
                feature_mode="portable",
            ),
            summarizer=mock_summarizer,
        )
        for i in range(25):
            port._append_to_history("user", "msg")

        await port._maybe_summarize()
        mock_summarizer.asummarize.assert_called_once()


class TestBaseRuntimePortCompaction:
    """BaseRuntimePort compaction vse eshche works (regressiya)."""

    @pytest.mark.asyncio
    async def test_base_port_summarizer_called_on_overflow(self) -> None:
        mock_summarizer = MagicMock()
        mock_summarizer.asummarize = AsyncMock(return_value="summary")

        port = BaseRuntimePort(
            system_prompt="test",
            summarizer=mock_summarizer,
        )
        for i in range(25):
            port._append_to_history("user", "msg")

        await port._maybe_summarize()
        mock_summarizer.asummarize.assert_called_once()

    @pytest.mark.asyncio
    async def test_base_port_no_summarizer_no_error(self) -> None:
        port = BaseRuntimePort(system_prompt="test")
        for i in range(25):
            port._append_to_history("user", "msg")
        await port._maybe_summarize()  # Should not raise


class TestTokenAwareCompaction:
    """Token-aware compaction trigger in BaseRuntimePort."""

    @pytest.mark.asyncio
    async def test_token_trigger_fires_on_threshold(self) -> None:
        """compaction_trigger=('tokens', N) srabatyvaet pri dostizhenii limita."""
        mock_summarizer = MagicMock()
        mock_summarizer.asummarize = AsyncMock(return_value="summary")

        port = BaseRuntimePort(
            system_prompt="test",
            summarizer=mock_summarizer,
            compaction_trigger=("tokens", 100),
        )
        # ~25 tokens per message (100 chars / 4)
        for i in range(20):
            port._append_to_history("user", "x" * 100)

        await port._maybe_summarize()
        mock_summarizer.asummarize.assert_called_once()

    @pytest.mark.asyncio
    async def test_token_trigger_does_not_fire_below_threshold(self) -> None:
        """compaction_trigger=('tokens', N) not srabatyvaet do limita."""
        mock_summarizer = MagicMock()
        mock_summarizer.asummarize = AsyncMock(return_value="summary")

        port = BaseRuntimePort(
            system_prompt="test",
            summarizer=mock_summarizer,
            compaction_trigger=("tokens", 100_000),
        )
        for i in range(5):
            port._append_to_history("user", "short msg")

        await port._maybe_summarize()
        mock_summarizer.asummarize.assert_not_called()

    @pytest.mark.asyncio
    async def test_message_trigger_backward_compat(self) -> None:
        """compaction_trigger=('messages', N) works kak ranshe."""
        mock_summarizer = MagicMock()
        mock_summarizer.asummarize = AsyncMock(return_value="summary")

        port = BaseRuntimePort(
            system_prompt="test",
            summarizer=mock_summarizer,
            compaction_trigger=("messages", 10),
        )
        for i in range(15):
            port._append_to_history("user", "msg")

        await port._maybe_summarize()
        mock_summarizer.asummarize.assert_called_once()

    @pytest.mark.asyncio
    async def test_default_trigger_is_message_based(self) -> None:
        """Without compaction_trigger - message-based (kak ranshe)."""
        mock_summarizer = MagicMock()
        mock_summarizer.asummarize = AsyncMock(return_value="summary")

        port = BaseRuntimePort(
            system_prompt="test",
            summarizer=mock_summarizer,
        )
        for i in range(25):
            port._append_to_history("user", "msg")

        await port._maybe_summarize()
        mock_summarizer.asummarize.assert_called_once()


class TestUnknownCompactionTrigger:
    """Notizvestnyy trigger type -> ValueError."""

    def test_unknown_trigger_type_raises(self) -> None:
        port = BaseRuntimePort(
            system_prompt="test",
            compaction_trigger=("unknown", 100),  # type: ignore[arg-type]
        )
        with pytest.raises(ValueError, match="unknown"):
            port._should_compact()


class TestArgumentTruncation:
    """Argument truncation: dlinnye tool_calls.args are truncated pered summarization."""

    def test_truncate_long_args_in_history(self) -> None:
        """Messages with content > 2000 chars truncated pered peredachey in summarizer."""
        from swarmline.runtime.ports.base import truncate_long_args

        messages = [
            {"role": "user", "content": "short"},
            {"role": "tool", "content": "x" * 5000},
            {"role": "assistant", "content": "ok"},
        ]
        result = truncate_long_args(messages, max_chars=2000)
        assert len(result[0]["content"]) == 5  # short — untouched
        assert len(result[1]["content"]) <= 2000 + 50  # truncated + suffix
        assert "[truncated]" in result[1]["content"]
        assert result[2]["content"] == "ok"  # untouched

    def test_truncate_preserves_short_messages(self) -> None:
        from swarmline.runtime.ports.base import truncate_long_args

        messages = [
            {"role": "user", "content": "hello"},
            {"role": "tool", "content": "short result"},
        ]
        result = truncate_long_args(messages, max_chars=2000)
        assert result[0]["content"] == "hello"
        assert result[1]["content"] == "short result"

    def test_truncate_default_threshold(self) -> None:
        from swarmline.runtime.ports.base import truncate_long_args

        messages = [{"role": "tool", "content": "x" * 3000}]
        result = truncate_long_args(messages)
        assert len(result[0]["content"]) <= 2050
        assert "[truncated]" in result[0]["content"]

    def test_truncate_skips_user_messages(self) -> None:
        """User messages NE are truncated, dazhe if dlinnye."""
        from swarmline.runtime.ports.base import truncate_long_args

        messages = [{"role": "user", "content": "x" * 5000}]
        result = truncate_long_args(messages, max_chars=2000)
        assert len(result[0]["content"]) == 5000

    def test_truncate_skips_assistant_messages(self) -> None:
        """Assistant messages NE are truncated."""
        from swarmline.runtime.ports.base import truncate_long_args

        messages = [{"role": "assistant", "content": "x" * 5000}]
        result = truncate_long_args(messages, max_chars=2000)
        assert len(result[0]["content"]) == 5000

    @pytest.mark.asyncio
    async def test_summarizer_receives_truncated_messages(self) -> None:
        """_maybe_summarize() passes truncated messages in summarizer."""
        mock_summarizer = MagicMock()
        mock_summarizer.asummarize = AsyncMock(return_value="summary")

        port = BaseRuntimePort(
            system_prompt="test",
            summarizer=mock_summarizer,
            compaction_trigger=("messages", 3),
        )
        port._append_to_history("user", "q")
        port._append_to_history("tool", "x" * 5000)
        port._append_to_history("assistant", "ok")

        await port._maybe_summarize()
        mock_summarizer.asummarize.assert_called_once()
        # Check the messages passed to summarizer have truncated content
        call_args = mock_summarizer.asummarize.call_args[0][0]
        tool_msg = [m for m in call_args if m.role == "tool"][0]
        assert len(tool_msg.content) <= 2050


class TestMemoryInjectionInBuildSystemPrompt:
    """BaseRuntimePort._build_system_prompt() inzhektit memory."""

    def test_memory_injected_when_sources_provided(self, tmp_path) -> None:
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("Use snake_case")

        port = BaseRuntimePort(
            system_prompt="You are helpful",
            memory_sources=[str(agents_md)],
        )
        prompt = port._build_system_prompt()
        assert "<agent_memory>" in prompt
        assert "snake_case" in prompt

    def test_no_memory_without_sources(self) -> None:
        port = BaseRuntimePort(system_prompt="You are helpful")
        prompt = port._build_system_prompt()
        assert "<agent_memory>" not in prompt
        assert prompt == "You are helpful"

    def test_missing_memory_file_no_block(self) -> None:
        port = BaseRuntimePort(
            system_prompt="You are helpful",
            memory_sources=["/nonexistent/AGENTS.md"],
        )
        prompt = port._build_system_prompt()
        assert "<agent_memory>" not in prompt
