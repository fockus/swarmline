"""Integration tests for Phase 13: Conversation Compaction.

Covers:
- CMPCT-04: Compaction configurable via RuntimeConfig
- Filter pipeline integration (compaction + instructions + reminders)
- Backward compatibility (no compaction config = no change)
- End-to-end compaction with realistic message history
"""

from __future__ import annotations

import pytest

from swarmline.compaction import CompactionConfig, ConversationCompactionFilter
from swarmline.input_filters import InputFilter, MaxTokensFilter
from swarmline.runtime.types import Message, RuntimeConfig


def _msg(
    role: str, content: str, name: str | None = None, metadata: dict | None = None
) -> Message:
    return Message(role=role, content=content, name=name, metadata=metadata)


def _tool_pair(tool_name: str, result: str) -> list[Message]:
    return [
        _msg("assistant", "", metadata={"tool_call": tool_name}),
        _msg("tool", result, name=tool_name),
    ]


# ---------------------------------------------------------------------------
# RuntimeConfig integration
# ---------------------------------------------------------------------------


class TestRuntimeConfigCompaction:
    def test_compaction_config_default_none(self) -> None:
        """RuntimeConfig.compaction defaults to None."""
        config = RuntimeConfig(runtime_name="thin")
        assert config.compaction is None

    def test_compaction_config_accepted(self) -> None:
        """RuntimeConfig accepts CompactionConfig instance."""
        cc = CompactionConfig(threshold_tokens=50_000, preserve_recent_pairs=2)
        config = RuntimeConfig(runtime_name="thin", compaction=cc)
        assert config.compaction is cc
        assert config.compaction.threshold_tokens == 50_000


# ---------------------------------------------------------------------------
# InputFilter pipeline integration
# ---------------------------------------------------------------------------


class TestCompactionFilterPipeline:
    @pytest.mark.asyncio
    async def test_compaction_implements_input_filter(self) -> None:
        """ConversationCompactionFilter implements InputFilter protocol."""
        f = ConversationCompactionFilter()
        assert isinstance(f, InputFilter)

    @pytest.mark.asyncio
    async def test_compaction_in_filter_chain(self) -> None:
        """Compaction works correctly in a sequential filter chain."""
        # Build a large conversation that triggers compaction
        msgs: list[Message] = [_msg("user", "start")]
        for i in range(20):
            msgs.extend(_tool_pair(f"tool_{i}", "x" * 20_000))
        msgs.append(_msg("user", "final question"))

        compaction = ConversationCompactionFilter(
            config=CompactionConfig(
                threshold_tokens=10_000,
                preserve_recent_pairs=2,
                tier_2_enabled=False,  # skip LLM, test tier 1 + 3
            ),
        )

        result_msgs, result_prompt = await compaction.filter(msgs, "system prompt")

        # Should be significantly shorter
        assert len(result_msgs) < len(msgs)
        # Last message preserved
        assert result_msgs[-1].content == "final question"

    @pytest.mark.asyncio
    async def test_compaction_and_max_tokens_filter_coexist(self) -> None:
        """Compaction filter and MaxTokensFilter can work together."""
        msgs = [_msg("user", "x" * 1000) for _ in range(10)]

        compaction = ConversationCompactionFilter(
            config=CompactionConfig(threshold_tokens=500, tier_2_enabled=False)
        )
        max_tokens = MaxTokensFilter(max_tokens=200)

        # Chain: compaction first, then MaxTokensFilter
        msgs1, prompt1 = await compaction.filter(msgs, "sys")
        msgs2, prompt2 = await max_tokens.filter(msgs1, prompt1)

        assert len(msgs2) <= len(msgs1) <= len(msgs)

    @pytest.mark.asyncio
    async def test_backward_compat_no_compaction(self) -> None:
        """No compaction configured = messages unchanged."""
        msgs = [_msg("user", "hello"), _msg("assistant", "hi")]

        compaction = ConversationCompactionFilter(
            config=CompactionConfig(enabled=False)
        )
        result_msgs, result_prompt = await compaction.filter(msgs, "system")

        assert result_msgs == msgs
        assert result_prompt == "system"


# ---------------------------------------------------------------------------
# Project instructions preservation
# ---------------------------------------------------------------------------


class TestCompactionPreservesInstructions:
    @pytest.mark.asyncio
    async def test_compaction_preserves_system_prompt(self) -> None:
        """Compaction never modifies system_prompt (instructions live there)."""
        long_prompt = "Project instructions: " + "x" * 10_000

        msgs = [_msg("user", "x" * 50_000)]
        for _ in range(5):
            msgs.extend(_tool_pair("read_file", "y" * 50_000))
        msgs.append(_msg("user", "question"))

        compaction = ConversationCompactionFilter(
            config=CompactionConfig(threshold_tokens=5000, tier_2_enabled=False)
        )
        result_msgs, result_prompt = await compaction.filter(msgs, long_prompt)

        # System prompt MUST be unchanged
        assert result_prompt == long_prompt
        # Messages should be reduced
        assert len(result_msgs) < len(msgs)


# ---------------------------------------------------------------------------
# Realistic scenario
# ---------------------------------------------------------------------------


class TestCompactionRealisticScenario:
    @pytest.mark.asyncio
    async def test_compaction_with_real_message_history(self) -> None:
        """Simulate realistic agent conversation with tool calls."""
        msgs: list[Message] = []

        # User asks a question
        msgs.append(_msg("user", "Read the config file and tell me the database URL"))

        # Agent reads file (tool call + result)
        msgs.extend(
            _tool_pair("read_file", '{"database_url": "postgres://localhost/mydb"}')
        )

        # Agent responds
        msgs.append(_msg("assistant", "The database URL is postgres://localhost/mydb"))

        # User asks for another file
        msgs.append(_msg("user", "Now read the environment variables file"))

        # Agent reads another file (large result)
        msgs.extend(_tool_pair("read_file", "ENV_VAR=value\n" * 5000))

        # Agent responds
        msgs.append(_msg("assistant", "I found the environment variables"))

        # More tool calls to push over budget
        for i in range(10):
            msgs.extend(_tool_pair(f"grep_{i}", f"match_{i}: " + "data " * 500))

        msgs.append(_msg("user", "What patterns did you find?"))

        # Threshold high enough that Tier 1 collapse suffices (no Tier 3 drop)
        compaction = ConversationCompactionFilter(
            config=CompactionConfig(
                threshold_tokens=5000,
                preserve_recent_pairs=2,
                tier_2_enabled=False,
            ),
        )
        result_msgs, _ = await compaction.filter(msgs, "You are a helpful assistant")

        # Result should be shorter (collapsed tool pairs)
        assert len(result_msgs) < len(msgs)
        # Last message preserved
        assert result_msgs[-1].content == "What patterns did you find?"
        # Some collapsed messages should contain tool names
        collapsed = [m for m in result_msgs if "[Collapsed tool call:" in m.content]
        assert len(collapsed) > 0

    @pytest.mark.asyncio
    async def test_compaction_with_llm_summarization(self) -> None:
        """Test Tier 2 with mock LLM call — non-tool messages force summarization."""
        # Lots of user/assistant messages that Tier 1 can't collapse
        msgs: list[Message] = []
        for i in range(10):
            msgs.append(_msg("user", f"question {i} " * 200))
            msgs.append(_msg("assistant", f"answer {i} " * 200))
        msgs.append(_msg("user", "final"))

        async def mock_llm(prompt: str, text: str) -> str:
            return "The user asked about X and the agent found Y."

        compaction = ConversationCompactionFilter(
            config=CompactionConfig(
                threshold_tokens=500,
                preserve_recent_pairs=0,
                tier_3_enabled=False,  # Only test Tier 1 + 2
            ),
            llm_call=mock_llm,
        )
        result_msgs, _ = await compaction.filter(msgs, "sys")

        # Should have summary + preserved messages
        assert len(result_msgs) < len(msgs)
        summary_msgs = [m for m in result_msgs if "[Conversation summary]" in m.content]
        assert len(summary_msgs) >= 1
