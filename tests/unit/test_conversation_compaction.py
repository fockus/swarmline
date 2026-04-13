"""Tests for ConversationCompactionFilter — 3-tier conversation compaction (Phase 13).

Tier 1: Collapse old tool call/result pairs into summaries.
Tier 2: LLM summarization of oldest messages (Task 2).
Tier 3: Emergency truncation (Task 2).
"""

from __future__ import annotations

import pytest

from swarmline.compaction import CompactionConfig, ConversationCompactionFilter
from swarmline.domain_types import Message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msg(
    role: str,
    content: str,
    name: str | None = None,
    metadata: dict | None = None,
) -> Message:
    return Message(role=role, content=content, name=name, metadata=metadata)


def _tool_pair(tool_name: str, result: str) -> list[Message]:
    """Create a consecutive assistant tool-call + tool result pair."""
    return [
        _msg("assistant", "", metadata={"tool_call": tool_name}),
        _msg("tool", result, name=tool_name),
    ]


# ---------------------------------------------------------------------------
# CompactionConfig defaults
# ---------------------------------------------------------------------------


class TestCompactionConfig:
    def test_compaction_config_defaults(self) -> None:
        config = CompactionConfig()
        assert config.enabled is True
        assert config.threshold_tokens == 80_000
        assert config.preserve_recent_pairs == 3
        assert config.tier_1_enabled is True
        assert config.tier_2_enabled is True
        assert config.tier_3_enabled is True

    def test_compaction_config_frozen(self) -> None:
        config = CompactionConfig()
        with pytest.raises(AttributeError):
            config.enabled = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Disabled / below threshold — passthrough
# ---------------------------------------------------------------------------


class TestCompactionPassthrough:
    @pytest.mark.asyncio
    async def test_compaction_disabled_returns_unchanged(self) -> None:
        config = CompactionConfig(enabled=False)
        f = ConversationCompactionFilter(config=config)
        msgs = [_msg("user", "hello")]
        result_msgs, result_prompt = await f.filter(msgs, "system")
        assert result_msgs is msgs
        assert result_prompt == "system"

    @pytest.mark.asyncio
    async def test_compaction_below_threshold_returns_unchanged(self) -> None:
        config = CompactionConfig(threshold_tokens=10_000)
        f = ConversationCompactionFilter(config=config)
        msgs = [_msg("user", "short message")]
        result_msgs, result_prompt = await f.filter(msgs, "sys")
        assert result_msgs is msgs
        assert result_prompt == "sys"

    @pytest.mark.asyncio
    async def test_compaction_empty_messages_returns_unchanged(self) -> None:
        f = ConversationCompactionFilter()
        result_msgs, result_prompt = await f.filter([], "sys")
        assert result_msgs == []
        assert result_prompt == "sys"


# ---------------------------------------------------------------------------
# Tier 1 — tool result collapsing
# ---------------------------------------------------------------------------


class TestTier1ToolCollapse:
    """Tier 1 tests run with Tier 2/3 disabled for isolation."""

    @pytest.mark.asyncio
    async def test_tier1_collapses_old_tool_pairs(self) -> None:
        """Old tool pairs are collapsed; recent pairs + trailing msgs preserved."""
        config = CompactionConfig(
            threshold_tokens=50,
            preserve_recent_pairs=1,
            tier_2_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        msgs = (
            _tool_pair("read_file", "x" * 200)  # pair 0 — collapsed
            + _tool_pair("grep", "y" * 200)  # pair 1 — collapsed
            + _tool_pair("write", "z" * 200)  # pair 2 — collapsed
            + _tool_pair("bash", "w" * 100)  # pair 3 — preserved (recent)
            + [_msg("user", "done")]
        )
        result_msgs, _ = await f.filter(msgs, "sys")
        # 3 collapsed + 2 preserved pair + 1 user = 6
        assert len(result_msgs) == 6
        assert len(result_msgs) < len(msgs)
        # Last pair (bash) preserved intact
        assert result_msgs[-3].role == "assistant"
        assert result_msgs[-3].metadata == {"tool_call": "bash"}
        assert result_msgs[-2].role == "tool"
        assert result_msgs[-2].name == "bash"
        # User message at end
        assert result_msgs[-1].role == "user"
        assert result_msgs[-1].content == "done"

    @pytest.mark.asyncio
    async def test_tier1_preserves_recent_pairs(self) -> None:
        """The last N tool pairs are kept intact."""
        config = CompactionConfig(
            threshold_tokens=50,
            preserve_recent_pairs=2,
            tier_2_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        msgs = (
            _tool_pair("old_tool", "x" * 200)  # collapsed
            + _tool_pair("recent1", "y" * 100)  # preserved
            + _tool_pair("recent2", "z" * 100)  # preserved
            + [_msg("user", "go")]
        )
        result_msgs, _ = await f.filter(msgs, "sys")
        # 1 collapsed + 2*2 preserved + 1 user = 6
        assert len(result_msgs) == 6
        tool_msgs = [m for m in result_msgs if m.role == "tool"]
        assert len(tool_msgs) == 2
        tool_names = {m.name for m in tool_msgs}
        assert tool_names == {"recent1", "recent2"}

    @pytest.mark.asyncio
    async def test_tier1_collapsed_message_contains_tool_name(self) -> None:
        """Collapsed summary mentions the tool name."""
        config = CompactionConfig(
            threshold_tokens=1,
            preserve_recent_pairs=0,
            tier_2_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        msgs = _tool_pair("my_special_tool", "result data") + [_msg("user", "q")]
        result_msgs, _ = await f.filter(msgs, "sys")
        collapsed = [m for m in result_msgs if m.role == "system"]
        assert len(collapsed) == 1
        assert "my_special_tool" in collapsed[0].content

    @pytest.mark.asyncio
    async def test_tier1_collapsed_message_contains_result_snippet(self) -> None:
        """Collapsed summary includes the beginning of the tool result."""
        config = CompactionConfig(
            threshold_tokens=10,
            preserve_recent_pairs=0,
            tier_2_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        result_text = "ImportantResult_12345 and more data here"
        msgs = _tool_pair("tool_x", result_text) + [_msg("user", "q")]
        result_msgs, _ = await f.filter(msgs, "sys")
        collapsed = [m for m in result_msgs if m.role == "system"]
        assert len(collapsed) == 1
        assert "ImportantResult_12345" in collapsed[0].content

    @pytest.mark.asyncio
    async def test_tier1_no_tool_pairs_skips(self) -> None:
        """Messages without tool pairs pass through Tier 1 unchanged."""
        config = CompactionConfig(
            threshold_tokens=10,
            preserve_recent_pairs=1,
            tier_2_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        msgs = [
            _msg("user", "hello " * 50),
            _msg("assistant", "world " * 50),
            _msg("user", "again " * 50),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")
        # No tool pairs -> Tier 1 can't help; messages returned as-is
        assert result_msgs == msgs

    @pytest.mark.asyncio
    async def test_tier1_only_collapses_when_over_threshold(self) -> None:
        """Under threshold -> no collapsing even with tool pairs."""
        config = CompactionConfig(threshold_tokens=10_000, preserve_recent_pairs=1)
        f = ConversationCompactionFilter(config=config)
        msgs = (
            _tool_pair("tool1", "short")
            + _tool_pair("tool2", "data")
            + [_msg("user", "hi")]
        )
        result_msgs, _ = await f.filter(msgs, "sys")
        assert result_msgs is msgs

    @pytest.mark.asyncio
    async def test_tier1_system_prompt_counted_in_budget(self) -> None:
        """System prompt tokens are included in the total token estimate."""
        config = CompactionConfig(
            threshold_tokens=50,
            preserve_recent_pairs=0,
            tier_2_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        big_system = "x" * 200  # 200//4+1 = 51 tokens
        msgs = _tool_pair("tool1", "data" * 10) + [_msg("user", "q")]
        result_msgs, _ = await f.filter(msgs, big_system)
        # Should trigger compaction: 1 tool pair collapsed
        assert len(result_msgs) < len(msgs)
        collapsed = [m for m in result_msgs if m.role == "system"]
        assert len(collapsed) == 1
        assert "tool1" in collapsed[0].content

    @pytest.mark.asyncio
    async def test_tier1_all_pairs_recent_no_collapse(self) -> None:
        """If preserve_recent_pairs >= number of pairs, nothing is collapsed."""
        config = CompactionConfig(
            threshold_tokens=10,
            preserve_recent_pairs=5,
            tier_2_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        msgs = (
            _tool_pair("a", "x" * 100)
            + _tool_pair("b", "y" * 100)
            + [_msg("user", "q")]
        )
        result_msgs, _ = await f.filter(msgs, "sys")
        # 2 pairs <= preserve_recent_pairs(5), so nothing collapsed
        # Messages pass through unchanged
        assert result_msgs == msgs

    @pytest.mark.asyncio
    async def test_tier1_interleaved_non_tool_messages_preserved(self) -> None:
        """Non-tool messages between tool pairs are preserved."""
        config = CompactionConfig(
            threshold_tokens=10,
            preserve_recent_pairs=0,
            tier_2_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        msgs = [
            _msg("user", "start"),
            *_tool_pair("tool_a", "result_a" * 20),
            _msg("assistant", "thinking..."),
            *_tool_pair("tool_b", "result_b" * 20),
            _msg("user", "end"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")
        # Both pairs collapsed; non-tool messages preserved
        user_msgs = [m for m in result_msgs if m.role == "user"]
        assert len(user_msgs) == 2
        assert user_msgs[0].content == "start"
        assert user_msgs[1].content == "end"
        assistant_msgs = [m for m in result_msgs if m.role == "assistant"]
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0].content == "thinking..."


# ---------------------------------------------------------------------------
# Tier 2 — LLM summarization
# ---------------------------------------------------------------------------


class TestTier2LlmSummarization:
    @pytest.mark.asyncio
    async def test_tier2_summarizes_oldest_messages(self) -> None:
        """Oldest messages are replaced by an LLM-generated summary."""

        async def mock_llm(prompt: str, dialog_text: str) -> str:
            return "Summary: discussed project setup and tool usage."

        config = CompactionConfig(
            threshold_tokens=20, preserve_recent_pairs=0, tier_1_enabled=False
        )
        f = ConversationCompactionFilter(config=config, llm_call=mock_llm)
        msgs = [
            _msg("user", "hello " * 30),
            _msg("assistant", "I can help " * 30),
            _msg("user", "what about X " * 30),
            _msg("assistant", "X is great " * 30),
            _msg("user", "latest question"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")
        assert len(result_msgs) < len(msgs)
        assert result_msgs[-1].content == "latest question"

    @pytest.mark.asyncio
    async def test_tier2_preserves_recent_messages(self) -> None:
        """The last message is always preserved by Tier 2."""

        async def mock_llm(prompt: str, dialog_text: str) -> str:
            return "Summary of old conversation."

        config = CompactionConfig(
            threshold_tokens=20, preserve_recent_pairs=0, tier_1_enabled=False
        )
        f = ConversationCompactionFilter(config=config, llm_call=mock_llm)
        msgs = [
            _msg("user", "old msg " * 30),
            _msg("assistant", "old reply " * 30),
            _msg("user", "current question"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")
        assert result_msgs[-1].content == "current question"
        assert result_msgs[-1].role == "user"

    @pytest.mark.asyncio
    async def test_tier2_summary_message_has_compaction_marker(self) -> None:
        """Summary message contains the [Conversation summary] marker."""

        async def mock_llm(prompt: str, dialog_text: str) -> str:
            return "The user discussed important topics."

        config = CompactionConfig(
            threshold_tokens=20, preserve_recent_pairs=0, tier_1_enabled=False
        )
        f = ConversationCompactionFilter(config=config, llm_call=mock_llm)
        msgs = [
            _msg("user", "first msg " * 30),
            _msg("assistant", "response " * 30),
            _msg("user", "last"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")
        summary_msgs = [
            m for m in result_msgs if "[Conversation summary]" in m.content
        ]
        assert len(summary_msgs) == 1
        assert summary_msgs[0].role == "system"

    @pytest.mark.asyncio
    async def test_tier2_skipped_when_no_llm_call(self) -> None:
        """Without llm_call, Tier 2 is skipped and Tier 3 runs instead."""
        config = CompactionConfig(
            threshold_tokens=20, preserve_recent_pairs=0, tier_1_enabled=False
        )
        f = ConversationCompactionFilter(config=config, llm_call=None)
        msgs = [
            _msg("user", "msg " * 50),
            _msg("assistant", "reply " * 50),
            _msg("user", "last"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")
        # Tier 2 skipped, Tier 3 truncates; last message preserved
        assert result_msgs[-1].content == "last"
        assert len(result_msgs) < len(msgs)

    @pytest.mark.asyncio
    async def test_tier2_fallback_to_tier3_on_llm_failure(self) -> None:
        """If llm_call raises, Tier 3 handles truncation."""

        async def failing_llm(prompt: str, dialog_text: str) -> str:
            raise RuntimeError("LLM unavailable")

        config = CompactionConfig(
            threshold_tokens=20, preserve_recent_pairs=0, tier_1_enabled=False
        )
        f = ConversationCompactionFilter(config=config, llm_call=failing_llm)
        msgs = [
            _msg("user", "msg " * 50),
            _msg("assistant", "reply " * 50),
            _msg("user", "latest"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")
        # LLM failed -> Tier 3 truncates
        assert result_msgs[-1].content == "latest"
        assert len(result_msgs) < len(msgs)


# ---------------------------------------------------------------------------
# Tier 3 — emergency truncation
# ---------------------------------------------------------------------------


class TestTier3EmergencyTruncation:
    @pytest.mark.asyncio
    async def test_tier3_drops_oldest_messages(self) -> None:
        """Tier 3 drops oldest messages until under budget."""
        config = CompactionConfig(
            threshold_tokens=20,
            preserve_recent_pairs=0,
            tier_1_enabled=False,
            tier_2_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        msgs = [
            _msg("user", "old1 " * 50),
            _msg("assistant", "old2 " * 50),
            _msg("user", "old3 " * 50),
            _msg("user", "recent"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")
        assert len(result_msgs) < len(msgs)
        assert result_msgs[-1].content == "recent"

    @pytest.mark.asyncio
    async def test_tier3_preserves_last_message(self) -> None:
        """Even with extreme budget pressure, the last message survives."""
        config = CompactionConfig(
            threshold_tokens=5,
            preserve_recent_pairs=0,
            tier_1_enabled=False,
            tier_2_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        msgs = [
            _msg("user", "very long " * 100),
            _msg("assistant", "very long " * 100),
            _msg("user", "last msg"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")
        assert len(result_msgs) >= 1
        assert result_msgs[-1].content == "last msg"

    @pytest.mark.asyncio
    async def test_tier3_preserves_system_prompt(self) -> None:
        """System prompt is never modified by Tier 3."""
        config = CompactionConfig(
            threshold_tokens=20,
            preserve_recent_pairs=0,
            tier_1_enabled=False,
            tier_2_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        msgs = [
            _msg("user", "msg " * 50),
            _msg("user", "last"),
        ]
        _, result_prompt = await f.filter(msgs, "my system prompt")
        assert result_prompt == "my system prompt"


# ---------------------------------------------------------------------------
# Full cascade — Tier 1 -> Tier 2 -> Tier 3
# ---------------------------------------------------------------------------


class TestCascade:
    @pytest.mark.asyncio
    async def test_cascade_tier1_then_tier2(self) -> None:
        """Tier 1 collapses tool pairs, but non-tool messages remain large → Tier 2 summarizes."""

        async def mock_llm(prompt: str, dialog_text: str) -> str:
            return "Short summary."

        # Lots of non-tool messages that Tier 1 can't collapse
        config = CompactionConfig(
            threshold_tokens=100, preserve_recent_pairs=0, tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config, llm_call=mock_llm)
        msgs = [
            _msg("user", "long message " * 100),
            _msg("assistant", "long response " * 100),
            _msg("user", "more context " * 100),
            _msg("assistant", "another reply " * 100),
        ] + _tool_pair("tool1", "data " * 50) + [
            _msg("user", "question"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")
        assert result_msgs[-1].content == "question"
        assert len(result_msgs) < len(msgs)
        # Should have a summary message from Tier 2
        summary_msgs = [
            m for m in result_msgs if "[Conversation summary]" in m.content
        ]
        assert len(summary_msgs) == 1

    @pytest.mark.asyncio
    async def test_cascade_tier1_then_tier3_when_no_llm(self) -> None:
        """Tier 1 -> no LLM -> Tier 3 truncates."""
        config = CompactionConfig(threshold_tokens=30, preserve_recent_pairs=1)
        f = ConversationCompactionFilter(config=config, llm_call=None)
        msgs = (
            _tool_pair("tool1", "data " * 100)
            + _tool_pair("tool2", "info " * 100)
            + _tool_pair("tool3", "res " * 50)
            + [_msg("user", "question")]
        )
        result_msgs, _ = await f.filter(msgs, "sys")
        assert result_msgs[-1].content == "question"
        assert len(result_msgs) < len(msgs)

    @pytest.mark.asyncio
    async def test_full_cascade_all_three_tiers(self) -> None:
        """Tier 1 -> Tier 2 (too verbose) -> Tier 3 emergency truncation."""

        async def verbose_llm(prompt: str, dialog_text: str) -> str:
            return "Very detailed summary " * 100  # ~2200 chars, won't fit

        config = CompactionConfig(threshold_tokens=20, preserve_recent_pairs=1)
        f = ConversationCompactionFilter(config=config, llm_call=verbose_llm)
        msgs = (
            _tool_pair("tool1", "data " * 200)
            + _tool_pair("tool2", "info " * 200)
            + _tool_pair("tool3", "res " * 100)
            + [_msg("user", "q")]
        )
        result_msgs, _ = await f.filter(msgs, "sys")
        # All 3 tiers fire: collapse -> summarize (too big) -> truncate
        assert result_msgs[-1].content == "q"


# ---------------------------------------------------------------------------
# InputFilter protocol conformance
# ---------------------------------------------------------------------------


class TestInputFilterProtocol:
    def test_conforms_to_input_filter_protocol(self) -> None:
        from swarmline.input_filters import InputFilter

        f = ConversationCompactionFilter()
        assert isinstance(f, InputFilter)
