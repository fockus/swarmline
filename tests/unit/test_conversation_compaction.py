"""Tests for ConversationCompactionFilter — 3-tier conversation compaction (Phase 13).

Tier 1: Collapse old tool call/result pairs into summaries.
Tier 2: LLM summarization of oldest messages (Task 2).
Tier 3: Emergency truncation (Task 2).
"""

from __future__ import annotations

import pytest

from swarmline.compaction import (
    DUPLICATE_TOOL_OUTPUT_MARKER,
    CompactionConfig,
    ConversationCompactionFilter,
)
from swarmline.domain_types import Message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Sprint 1ce CE-15/19: the acceptance gate only takes a summary carrying all
# seven fixed sections (Next Steps last) — prose-only mock summaries now route
# to the local fallback, so tests about an ACCEPTED LLM summary use this one.
# Labels count only at a line start (a label mid-line is content).
_VALID_SUMMARY = (
    "Goal: g.\nConstraints: c.\nProgress: p.\nKey Decisions: k.\n"
    "Errors: none.\nFiles: none.\nNext Steps: n."
)
_WHITESPACE_SUMMARY = _VALID_SUMMARY + "   \n  "


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


def _native_tool_group(calls: list[tuple[str, str]]) -> list[Message]:
    """Create a native tool-calling group: ONE assistant message with
    ``tool_calls`` (N entries), followed by N tool-role results in order —
    the shape ``react_strategy.py``'s native path actually produces
    (``Message(role="assistant", tool_calls=[...])`` + one ``Message(role=
    "tool", ...)`` per call), distinct from the legacy single-call
    ``metadata["tool_call"]`` shape used by ``_tool_pair`` (codex R1 [1
    CRITICAL])."""
    messages: list[Message] = [
        Message(
            role="assistant",
            content="",
            tool_calls=[
                {"id": f"call-{i}", "name": name, "args": {}}
                for i, (name, _result) in enumerate(calls)
            ],
        )
    ]
    for name, result in calls:
        messages.append(_msg("tool", result, name=name))
    return messages


def _no_adjacent_same_role_system_pair(messages: list[Message]) -> bool:
    """True when no two adjacent messages are BOTH role=='system'."""
    return all(
        not (messages[i].role == "system" and messages[i + 1].role == "system")
        for i in range(len(messages) - 1)
    )


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
        # codex R1 [4 MAJOR]: Ступень A is opt-in — a caller who only ever
        # set threshold_tokens/preserve_recent_pairs keeps byte-identical
        # pre-Stage-6 Tier 1/2/3 behaviour, not a silently-added new tier.
        assert config.dedup_enabled is False
        assert config.compactable_tool_names == frozenset()

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
        """Old tool pairs are collapsed; recent pairs + trailing msgs preserved.

        codex R1 [2 MAJOR]: 3 CONSECUTIVE collapsible pairs merge into ONE
        system message (never several adjacent system-role markers back to
        back) — one line per collapsed pair inside it."""
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
        # 1 merged collapsed system message + 1 preserved pair + 1 user = 4
        assert len(result_msgs) == 4
        assert len(result_msgs) < len(msgs)
        collapsed = result_msgs[0]
        assert collapsed.role == "system"
        for name in ("read_file", "grep", "write"):
            assert name in collapsed.content
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
# codex R2 [2] — errors survive Tier 1 -> Tier 2 fully verbatim (no cap at
# all, not just a bigger one) since Tier 2 reads Tier 1's OUTPUT, not the
# original raw messages.
# ---------------------------------------------------------------------------


class TestTier1ErrorsFullyVerbatim:
    @pytest.mark.asyncio
    async def test_error_over_500_chars_survives_tier1_collapse_uncapped(self) -> None:
        long_error = "Error: " + ("x" * 800) + " END_MARKER"
        config = CompactionConfig(
            threshold_tokens=1,
            preserve_recent_pairs=0,
            tier_2_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        msgs = _tool_pair("bash", long_error) + [_msg("user", "q")]
        result_msgs, _ = await f.filter(msgs, "sys")
        collapsed = next(m for m in result_msgs if m.role == "system")
        assert long_error in collapsed.content  # fully verbatim, not truncated
        assert "END_MARKER" in collapsed.content

    @pytest.mark.asyncio
    async def test_error_survives_tier1_then_tier2_summarization_verbatim(
        self,
    ) -> None:
        """The full point: Tier 2 (real LLM or local fallback) reads Tier 1's
        OUTPUT, so an error truncated by Tier 1 would never be seen in full
        by Tier 2's own "Errors: verbatim" section either."""
        long_error = "Error: " + ("y" * 800) + " END_MARKER_2"
        captured_dialogs: list[str] = []

        async def capture_llm(prompt: str, dialog_text: str) -> str:
            captured_dialogs.append(dialog_text)
            return "Goal: test. Errors: see dialog. Next Steps: none."

        config = CompactionConfig(threshold_tokens=20, preserve_recent_pairs=0)
        f = ConversationCompactionFilter(config=config, llm_call=capture_llm)
        msgs = _tool_pair("bash", long_error) + [_msg("user", "q")]
        await f.filter(msgs, "sys")
        assert captured_dialogs, "LLM should have been called"
        assert long_error in captured_dialogs[0]

    @pytest.mark.asyncio
    async def test_ordinary_non_error_content_still_capped_at_100(self) -> None:
        """Only error-bearing content is exempt — ordinary results still get
        the tight cap (Tier 1 must still actually shrink normal content)."""
        ordinary = "d" * 500
        config = CompactionConfig(
            threshold_tokens=1,
            preserve_recent_pairs=0,
            tier_2_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        msgs = _tool_pair("bash", ordinary) + [_msg("user", "q")]
        result_msgs, _ = await f.filter(msgs, "sys")
        collapsed = next(m for m in result_msgs if m.role == "system")
        assert ordinary not in collapsed.content
        assert len(collapsed.content) < len(ordinary)


# ---------------------------------------------------------------------------
# codex R1 [1 CRITICAL] — native multi-tool-call groups (Message.tool_calls,
# distinct from the legacy metadata["tool_call"] single-call shape).
# ---------------------------------------------------------------------------


class TestNativeMultiToolCallGroups:
    @pytest.mark.asyncio
    async def test_tier1_collapses_native_group_as_one_unit(self) -> None:
        """A native 3-call group collapses into exactly ONE system message
        (not 3), naming every tool call — never split, never stacked."""
        config = CompactionConfig(
            threshold_tokens=1,
            preserve_recent_pairs=0,
            tier_2_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        msgs = _native_tool_group(
            [("read_file", "content A"), ("grep", "content B"), ("bash", "content C")]
        ) + [_msg("user", "q")]
        result_msgs, _ = await f.filter(msgs, "sys")
        collapsed = [m for m in result_msgs if m.role == "system"]
        assert len(collapsed) == 1
        for name in ("read_file", "grep", "bash"):
            assert name in collapsed[0].content

    @pytest.mark.asyncio
    async def test_native_group_never_split_by_tier3_truncation(self) -> None:
        """Tier 3 emergency truncation drops/keeps a native group as ONE
        unit -- never orphans a subset of its results."""
        config = CompactionConfig(
            threshold_tokens=5,
            preserve_recent_pairs=0,
            tier_1_enabled=False,
            tier_2_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        msgs = (
            [_msg("user", "start " * 50)]
            + _native_tool_group(
                [("read_file", "x" * 500), ("grep", "y" * 500), ("bash", "z" * 500)]
            )
            + [_msg("user", "final")]
        )
        result_msgs, _ = await f.filter(msgs, "sys")
        tool_msgs = [m for m in result_msgs if m.role == "tool"]
        # All-or-nothing: never 1 or 2 out of the 3-call group survives alone.
        assert len(tool_msgs) in (0, 3)
        assert result_msgs[-1].content == "final"

    @pytest.mark.asyncio
    async def test_native_group_never_split_by_tier2_summarization(self) -> None:
        """Tier 2's preserve_count boundary never cuts a native group in
        half (pair-safe-preserve-boundary generalized to N-result groups)."""

        async def mock_llm(prompt: str, dialog_text: str) -> str:
            return "Summary of the old conversation segment."

        config = CompactionConfig(
            threshold_tokens=20, preserve_recent_pairs=0, tier_1_enabled=False
        )
        f = ConversationCompactionFilter(config=config, llm_call=mock_llm)
        msgs = [_msg("user", "old " * 50)] + _native_tool_group(
            [("a", "data " * 30), ("b", "data " * 30)]
        )
        result_msgs, _ = await f.filter(msgs, "sys")
        tool_msgs = [m for m in result_msgs if m.role == "tool"]
        assert len(tool_msgs) in (0, 2)

    @pytest.mark.asyncio
    async def test_mixed_dedup_and_template_within_one_native_group(self) -> None:
        """codex adversarial: within ONE native group, one result gets
        templated (compactable tool, takes priority over dedup) while its
        siblings get deduped (identical content between THEMSELVES) -- the
        group must stay structurally intact (3 results, in order), only
        CONTENT differs per result."""
        shared = "x" * 250
        config = CompactionConfig(
            threshold_tokens=1,
            preserve_recent_pairs=0,
            dedup_enabled=True,
            compactable_tool_names=frozenset({"read_file"}),
            tier_1_enabled=False,
            tier_2_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        msgs = _native_tool_group(
            [("read_file", shared), ("grep", shared), ("bash", shared)]
        ) + [_msg("user", "q")]
        result_msgs, _ = await f.filter(msgs, "sys")
        tool_msgs = [m for m in result_msgs if m.role == "tool"]
        assert len(tool_msgs) == 3  # group never split/dropped
        # read_file is templated (compactable), takes priority over dedup —
        # its content never registers a hash, so grep (next occurrence of
        # `shared`) is the FIRST the dedup pass actually sees.
        assert "read_file result collapsed" in tool_msgs[0].content
        assert tool_msgs[1].content == shared  # grep: first dedup-hash occurrence
        assert tool_msgs[2].content == DUPLICATE_TOOL_OUTPUT_MARKER  # bash: duplicate

    @pytest.mark.asyncio
    async def test_summary_never_lands_between_an_ordinary_pairs_two_halves(
        self,
    ) -> None:
        """codex adversarial "summary между парой": an UNTAGGED (ordinary,
        non-protected) tool pair inside the compactable region is fully
        FOLDED INTO the summary (both halves vanish together) -- the
        summary can never end up sitting structurally between a pair's
        tool_use and tool_result."""

        async def mock_llm(prompt: str, dialog_text: str) -> str:
            return "Summary of the old tool call."

        config = CompactionConfig(
            threshold_tokens=20, preserve_recent_pairs=0, tier_1_enabled=False
        )
        f = ConversationCompactionFilter(config=config, llm_call=mock_llm)
        msgs = (
            _tool_pair("ordinary_tool", "some result " * 30)
            + [_msg("user", "old context " * 30)]
            + [_msg("user", "latest")]
        )
        result_msgs, _ = await f.filter(msgs, "sys")
        # The ordinary pair is gone entirely (folded into the summary) —
        # never left half-orphaned around a summary message.
        tool_msgs = [m for m in result_msgs if m.role == "tool"]
        assert tool_msgs == []
        assistant_tool_call_msgs = [
            m
            for m in result_msgs
            if m.role == "assistant" and m.metadata and "tool_call" in m.metadata
        ]
        assert assistant_tool_call_msgs == []


# ---------------------------------------------------------------------------
# codex R2 [1] — a PARTIAL/malformed native group (declared N tool_calls but
# fewer than N tool-role messages actually follow) is correctly UNGROUPED by
# the strict _find_tool_groups (dedup/template semantics need exact
# attribution) — but that must NOT leave its assistant unprotected from
# orphaning the tool-role messages that DID survive. Cut/drop atomicity
# (Tier 3, protected_indices, preserve-boundary) uses a BROADER contiguous
# unit concept for this reason.
# ---------------------------------------------------------------------------


class TestPartialNativeGroupNeverOrphans:
    @pytest.mark.asyncio
    async def test_tier3_never_orphans_a_partial_native_groups_survivors(self) -> None:
        """assistant declares 3 tool_calls but only 2 tool-role messages
        actually follow (the 3rd is missing/malformed) -- strict grouping
        correctly refuses to call this a valid 3-result group, but Tier 3
        must still never drop the assistant while keeping either surviving
        tool-role message."""
        config = CompactionConfig(
            # threshold sized so Tier 3 drops SOME but not ALL units (not a
            # blanket "nuke everything but the last message" threshold) —
            # this is exactly the "one tool-result survives alone" orphan
            # window: drop start+assistant+tool(a), tool(b) then fits.
            threshold_tokens=200,
            preserve_recent_pairs=0,
            tier_1_enabled=False,
            tier_2_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        malformed_assistant = Message(
            role="assistant",
            content="",
            tool_calls=[
                {"id": "call-0", "name": "a", "args": {}},
                {"id": "call-1", "name": "b", "args": {}},
                {"id": "call-2", "name": "c", "args": {}},
            ],
        )
        msgs = [
            _msg("user", "start " * 50),
            malformed_assistant,
            _msg("tool", "x" * 500, name="a"),
            _msg("tool", "y" * 500, name="b"),
            # 3rd result missing entirely -- next message is NOT tool-role.
            _msg("user", "final"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")
        tool_msgs = [m for m in result_msgs if m.role == "tool"]
        has_assistant_initiator = any(
            m.role == "assistant" and m.tool_calls for m in result_msgs
        )
        # Never: tool-role survivors present WITHOUT their producing assistant.
        assert not (tool_msgs and not has_assistant_initiator)
        assert result_msgs[-1].content == "final"

    @pytest.mark.asyncio
    async def test_tier2_split_never_orphans_a_partial_native_groups_survivors(
        self,
    ) -> None:
        """Same malformed-group idea, but exercised via Tier 2's preserve-
        boundary: the boundary cuts BETWEEN the malformed assistant (region
        -> folded into the summary, vanishes) and its lone surviving tool
        result (preserved -> kept verbatim) -- an orphan by a DIFFERENT
        mechanism than Tier 3's drop loop."""

        async def mock_llm(prompt: str, dialog_text: str) -> str:
            return "Goal: test. Next Steps: none."

        config = CompactionConfig(
            threshold_tokens=20, preserve_recent_pairs=1, tier_1_enabled=False
        )
        f = ConversationCompactionFilter(config=config, llm_call=mock_llm)
        malformed_assistant = Message(
            role="assistant",
            content="",
            tool_calls=[
                {"id": "call-0", "name": "a", "args": {}},
                {"id": "call-1", "name": "b", "args": {}},
            ],
        )
        msgs = [
            _msg("user", "old " * 30),
            malformed_assistant,
            _msg("tool", "x" * 50, name="a"),
            # 2nd result missing -- next is NOT tool-role.
            _msg("user", "penultimate"),
            _msg("user", "final"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")
        tool_msgs = [m for m in result_msgs if m.role == "tool"]
        has_assistant_initiator = any(
            m.role == "assistant" and m.tool_calls for m in result_msgs
        )
        assert not (tool_msgs and not has_assistant_initiator)


# ---------------------------------------------------------------------------
# codex R1 [2 MAJOR] — Tier 1 never produces adjacent system-role messages.
# ---------------------------------------------------------------------------


class TestTier1NeverProducesAdjacentSystemMessages:
    @pytest.mark.asyncio
    async def test_many_consecutive_collapsible_groups_merge_into_one(self) -> None:
        config = CompactionConfig(
            threshold_tokens=1,
            preserve_recent_pairs=0,
            tier_2_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        msgs = (
            _tool_pair("t1", "a" * 50)
            + _native_tool_group([("t2", "b" * 50), ("t3", "c" * 50)])
            + _tool_pair("t4", "d" * 50)
            + [_msg("user", "q")]
        )
        result_msgs, _ = await f.filter(msgs, "sys")
        assert _no_adjacent_same_role_system_pair(result_msgs)
        collapsed = [m for m in result_msgs if m.role == "system"]
        assert len(collapsed) == 1


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
            return _VALID_SUMMARY

        config = CompactionConfig(
            threshold_tokens=20, preserve_recent_pairs=0, tier_1_enabled=False
        )
        f = ConversationCompactionFilter(config=config, llm_call=mock_llm)
        msgs = [
            _msg("user", "first msg " * 30),
            _msg("assistant", "response " * 300),
            _msg("user", "last"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")
        summary_msgs = [m for m in result_msgs if "[Conversation summary]" in m.content]
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
            threshold_tokens=100,
            preserve_recent_pairs=0,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config, llm_call=mock_llm)
        msgs = (
            [
                _msg("user", "long message " * 100),
                _msg("assistant", "long response " * 100),
                _msg("user", "more context " * 100),
                _msg("assistant", "another reply " * 100),
            ]
            + _tool_pair("tool1", "data " * 50)
            + [
                _msg("user", "question"),
            ]
        )
        result_msgs, _ = await f.filter(msgs, "sys")
        assert result_msgs[-1].content == "question"
        assert len(result_msgs) < len(msgs)
        # Should have a summary message from Tier 2
        summary_msgs = [m for m in result_msgs if "[Conversation summary]" in m.content]
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
# Non-compactable message preservation (Phase 15 — Thinking Events)
# ---------------------------------------------------------------------------


class TestNonCompactableTier2:
    """Tier 2: non_compactable messages survive LLM summarization."""

    @pytest.mark.asyncio
    async def test_non_compactable_survives_tier2(self) -> None:
        """Messages with metadata.non_compactable=True skip summarization."""

        async def mock_llm(prompt: str, dialog_text: str) -> str:
            return "Summarized conversation."

        config = CompactionConfig(
            threshold_tokens=20,
            preserve_recent_pairs=0,
            tier_1_enabled=False,
        )
        f = ConversationCompactionFilter(config=config, llm_call=mock_llm)
        msgs = [
            _msg("user", "old msg " * 30),
            _msg("assistant", "thinking content", metadata={"non_compactable": True}),
            _msg("assistant", "old reply " * 30),
            _msg("user", "latest"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")
        # non_compactable message must survive
        nc_msgs = [
            m for m in result_msgs if m.metadata and m.metadata.get("non_compactable")
        ]
        assert len(nc_msgs) == 1
        assert nc_msgs[0].content == "thinking content"
        # last message preserved
        assert result_msgs[-1].content == "latest"

    @pytest.mark.asyncio
    async def test_non_compactable_before_compactable_run_keeps_original_order(
        self,
    ) -> None:
        """codex R1 [5 MAJOR]: a non_compactable message positioned BEFORE
        the compactable run must stay BEFORE the summary in the result —
        not get shoved after it just because the old code always emitted
        `[summary, *non_compactable, *preserved]` regardless of original
        position."""

        async def mock_llm(prompt: str, dialog_text: str) -> str:
            return _VALID_SUMMARY

        config = CompactionConfig(
            threshold_tokens=20,
            preserve_recent_pairs=0,
            tier_1_enabled=False,
        )
        f = ConversationCompactionFilter(config=config, llm_call=mock_llm)
        msgs = [
            _msg(
                "assistant", "EARLY_MARKER", metadata={"non_compactable": True}
            ),  # comes BEFORE the compactable run
            _msg("user", "old msg " * 30),
            _msg("assistant", "old reply " * 300),
            _msg("user", "latest"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")
        early_idx = next(
            i for i, m in enumerate(result_msgs) if m.content == "EARLY_MARKER"
        )
        summary_idx = next(
            i
            for i, m in enumerate(result_msgs)
            if "[Conversation summary]" in m.content
        )
        assert early_idx < summary_idx

    @pytest.mark.asyncio
    async def test_protected_system_message_may_be_adjacent_to_summary_but_both_survive_separately(
        self,
    ) -> None:
        """codex R4: position-preserving reassembly can place a protected
        (non_compactable) SYSTEM-role message directly next to the
        newly-inserted summary (also system-role). Fix-cycle 3's [4] MERGED
        them together (forcing ``non_compactable=True`` on the result) to
        avoid same-role adjacency -- but that broke the Stage C
        iterative-UPDATE contract: the merged message was classified as
        protected FIRST by ``_split_for_summarization``, so the summary
        text was never extracted as ``previous_summary`` on a LATER pass
        (codex R4 finding).

        The DoD invariant "no same-role adjacency" is narrowed to mean "no
        two collapsed-placeholder/summary messages stacked back to back" --
        NOT "a protected system message can never sit next to the
        summary". These are semantically DIFFERENT kinds of system content
        (a fixed protected instruction vs. a rolling digest); the Anthropic
        API auto-merges consecutive same-role messages server-side with no
        information loss (same as it does for consecutive user-role
        messages), so leaving them as two adjacent, SEPARATE messages is
        safe -- and is exactly what keeps the summary independently
        extractable for iterative UPDATE."""

        async def mock_llm(prompt: str, dialog_text: str) -> str:
            return _VALID_SUMMARY

        config = CompactionConfig(
            threshold_tokens=20,
            preserve_recent_pairs=0,
            tier_1_enabled=False,
            tier_3_enabled=False,  # isolate Tier 2's own reassembly output
        )
        f = ConversationCompactionFilter(config=config, llm_call=mock_llm)
        protected_system = _msg(
            "system", "PROTECTED_SYSTEM_MARKER", metadata={"non_compactable": True}
        )
        msgs = [
            protected_system,  # immediately before the compactable run
            _msg("user", "old msg " * 30),
            _msg("assistant", "old reply " * 300),
            _msg("user", "latest"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")
        protected_msgs = [
            m for m in result_msgs if "PROTECTED_SYSTEM_MARKER" in m.content
        ]
        summary_msgs = [m for m in result_msgs if "[Conversation summary]" in m.content]
        # Both pieces of content survive, as TWO SEPARATE messages -- never
        # merged into one (that's precisely what broke iterative UPDATE).
        assert len(protected_msgs) == 1
        assert len(summary_msgs) == 1
        assert protected_msgs[0] is not summary_msgs[0]
        assert protected_msgs[0].metadata is not None
        assert protected_msgs[0].metadata.get("non_compactable") is True
        # The summary itself must carry NO non_compactable tag -- it has to
        # stay extractable as `previous_summary` on a later pass.
        assert not (
            summary_msgs[0].metadata and summary_msgs[0].metadata.get("non_compactable")
        )

    def test_merge_adjacent_protected_system_messages_preserves_metadata(
        self,
    ) -> None:
        """codex R3 [4] (still valid for THIS case): two adjacent protected
        system messages (neither is the summary) are merged together, and
        the merge must not drop ``non_compactable`` metadata."""
        protected_a = _msg("system", "PROTECTED_A", metadata={"non_compactable": True})
        protected_b = _msg("system", "PROTECTED_B", metadata={"non_compactable": True})
        merged = ConversationCompactionFilter._merge_adjacent_system_messages(
            [protected_a, protected_b]
        )
        assert len(merged) == 1
        assert merged[0].metadata is not None
        assert merged[0].metadata.get("non_compactable") is True
        assert "PROTECTED_A" in merged[0].content
        assert "PROTECTED_B" in merged[0].content

    def test_merge_never_merges_summary_message_with_neighboring_system_message(
        self,
    ) -> None:
        """codex R4: the summary message (role=system, content starting
        with the ``[Conversation summary]`` marker) must NEVER be merged
        into a neighboring system message -- merging it made
        ``_split_for_summarization`` unable to extract it as
        ``previous_summary`` on a later pass (breaks the Stage C iterative
        UPDATE contract)."""
        protected = _msg(
            "system", "PROTECTED_SYSTEM_MARKER", metadata={"non_compactable": True}
        )
        summary = _msg("system", "[Conversation summary]: stuff")
        merged = ConversationCompactionFilter._merge_adjacent_system_messages(
            [protected, summary]
        )
        assert len(merged) == 2
        assert merged[0].content == "PROTECTED_SYSTEM_MARKER"
        assert merged[1].content == "[Conversation summary]: stuff"
        assert not (merged[1].metadata and merged[1].metadata.get("non_compactable"))

    @pytest.mark.asyncio
    async def test_iterative_update_and_protection_coexist_across_two_passes(
        self,
    ) -> None:
        """codex R4 regression probe: a protected system message adjacent
        to the summary must NOT break the Stage C iterative-UPDATE contract
        on a LATER pass. Two invariants must hold SIMULTANEOUSLY on the
        second pass: (a) the prior summary IS extracted and threaded as
        ``<previous-summary>`` (exactly ONE ``[Conversation summary]``
        message results -- never two stacked); (b) the protected content is
        still NEVER fed into the LLM dialog."""
        seen_prompts: list[str] = []
        seen_dialogs: list[str] = []

        async def mock_llm(prompt: str, dialog_text: str) -> str:
            seen_prompts.append(prompt)
            seen_dialogs.append(dialog_text)
            return _VALID_SUMMARY

        config = CompactionConfig(
            threshold_tokens=20,
            preserve_recent_pairs=0,
            tier_1_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config, llm_call=mock_llm)
        protected_system = _msg(
            "system", "PROTECTED_SYSTEM_MARKER", metadata={"non_compactable": True}
        )
        msgs = [
            protected_system,
            _msg("user", "old msg " * 30),
            _msg("assistant", "old reply " * 300),
            _msg("user", "latest"),
        ]
        first_pass, _ = await f.filter(msgs, "sys")

        second_input = [
            *first_pass[:-1],
            _msg("user", "more old msg " * 30),
            _msg("assistant", "more old reply " * 300),
            first_pass[-1],
        ]
        second_pass, _ = await f.filter(second_input, "sys")

        second_prompt_has_previous_summary = "<previous-summary>" in seen_prompts[-1]
        assert second_prompt_has_previous_summary, (
            "prior summary was not threaded for iterative UPDATE on the "
            "second pass -- protected+summary merge must have made the "
            "summary unextractable"
        )
        summary_count = sum(
            1 for m in second_pass if "[Conversation summary]" in m.content
        )
        assert summary_count == 1, (
            f"expected exactly 1 summary (UPDATE, not stacked), got {summary_count}"
        )
        for dialog in seen_dialogs:
            assert "PROTECTED_SYSTEM_MARKER" not in dialog, (
                "protected content leaked into LLM dialog on a later pass"
            )

    @pytest.mark.asyncio
    async def test_non_compactable_excluded_from_summary_text(self) -> None:
        """Non-compactable messages are NOT included in the summarization dialog."""
        captured_dialog: list[str] = []

        async def capture_llm(prompt: str, dialog_text: str) -> str:
            captured_dialog.append(dialog_text)
            return "Summary of the old conversation segment."

        config = CompactionConfig(
            threshold_tokens=20,
            preserve_recent_pairs=0,
            tier_1_enabled=False,
        )
        f = ConversationCompactionFilter(config=config, llm_call=capture_llm)
        msgs = [
            _msg("user", "old msg " * 30),
            _msg("assistant", "SECRET_THINKING", metadata={"non_compactable": True}),
            _msg("assistant", "old reply " * 30),
            _msg("user", "latest"),
        ]
        await f.filter(msgs, "sys")
        assert captured_dialog, "LLM should have been called"
        assert "SECRET_THINKING" not in captured_dialog[0]


class TestNonCompactableTier3:
    """Tier 3: non_compactable messages survive emergency truncation."""

    @pytest.mark.asyncio
    async def test_non_compactable_survives_tier3(self) -> None:
        """Messages with metadata.non_compactable=True are kept during truncation."""
        config = CompactionConfig(
            threshold_tokens=20,
            preserve_recent_pairs=0,
            tier_1_enabled=False,
            tier_2_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        msgs = [
            _msg("user", "old1 " * 50),
            _msg("assistant", "thinking", metadata={"non_compactable": True}),
            _msg("assistant", "old2 " * 50),
            _msg("user", "old3 " * 50),
            _msg("user", "recent"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")
        # non_compactable must survive
        nc_msgs = [
            m for m in result_msgs if m.metadata and m.metadata.get("non_compactable")
        ]
        assert len(nc_msgs) == 1
        assert nc_msgs[0].content == "thinking"
        # last message always preserved
        assert result_msgs[-1].content == "recent"
        # normal old messages should have been dropped
        assert len(result_msgs) < len(msgs)

    @pytest.mark.asyncio
    async def test_normal_messages_still_truncated(self) -> None:
        """Backward compat: messages without non_compactable are truncated normally."""
        config = CompactionConfig(
            threshold_tokens=10,
            preserve_recent_pairs=0,
            tier_1_enabled=False,
            tier_2_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        msgs = [
            _msg("user", "old " * 100),
            _msg("assistant", "old " * 100),
            _msg("user", "last"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")
        assert result_msgs[-1].content == "last"
        assert len(result_msgs) < len(msgs)


# ---------------------------------------------------------------------------
# InputFilter protocol conformance
# ---------------------------------------------------------------------------


class TestInputFilterProtocol:
    def test_conforms_to_input_filter_protocol(self) -> None:
        from swarmline.input_filters import InputFilter

        f = ConversationCompactionFilter()
        assert isinstance(f, InputFilter)


# ---------------------------------------------------------------------------
# Stage 6 Ступень A — no-LLM dedup + templated one-liners (Tier 0, cheapest)
# ---------------------------------------------------------------------------


class TestStageADedup:
    """Hash-based dedup of tool results >= 200 chars (Hermes Pass 1 pattern)."""

    @pytest.mark.asyncio
    async def test_dedup_collapses_exact_duplicate_over_200_chars(self) -> None:
        """Second occurrence of an identical >=200-char tool result is
        replaced by the duplicate marker; first occurrence stays intact."""
        config = CompactionConfig(
            threshold_tokens=10,
            preserve_recent_pairs=0,
            dedup_enabled=True,
            tier_1_enabled=False,
            tier_2_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        content = "x" * 250
        msgs = _tool_pair("tool_a", content) + _tool_pair("tool_b", content)
        result_msgs, _ = await f.filter(msgs, "sys")
        tool_msgs = [m for m in result_msgs if m.role == "tool"]
        assert tool_msgs[0].content == content  # first occurrence untouched
        assert tool_msgs[1].content == "[Duplicate tool output]"

    @pytest.mark.asyncio
    async def test_dedup_ignores_content_under_200_chars(self) -> None:
        """Identical content below the 200-char floor is never collapsed."""
        config = CompactionConfig(
            threshold_tokens=1,
            preserve_recent_pairs=0,
            tier_1_enabled=False,
            tier_2_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        content = "y" * 100
        msgs = _tool_pair("tool_a", content) + _tool_pair("tool_b", content)
        result_msgs, _ = await f.filter(msgs, "sys")
        tool_msgs = [m for m in result_msgs if m.role == "tool"]
        assert tool_msgs[0].content == content
        assert tool_msgs[1].content == content

    @pytest.mark.asyncio
    async def test_dedup_skips_recent_preserved_pairs(self) -> None:
        """A duplicate inside the preserve_recent_pairs window is left alone,
        even though an identical earlier result exists further back."""
        config = CompactionConfig(
            threshold_tokens=10,
            preserve_recent_pairs=1,
            dedup_enabled=True,
            tier_1_enabled=False,
            tier_2_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        content = "z" * 250
        msgs = (
            _tool_pair("older", content)  # eligible — first occurrence, kept
            + _tool_pair("also_old", content)  # eligible — duplicate, collapsed
            + _tool_pair("recent", content)  # preserved — duplicate but untouched
        )
        result_msgs, _ = await f.filter(msgs, "sys")
        tool_msgs = [m for m in result_msgs if m.role == "tool"]
        assert tool_msgs[0].content == content
        assert tool_msgs[1].content == "[Duplicate tool output]"
        assert tool_msgs[2].content == content  # recent — never touched

    @pytest.mark.asyncio
    async def test_dedup_respects_non_compactable_metadata(self) -> None:
        """non_compactable=True survives dedup even with duplicate content."""
        config = CompactionConfig(
            threshold_tokens=10,
            preserve_recent_pairs=0,
            tier_1_enabled=False,
            tier_2_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        content = "w" * 250
        msgs = _tool_pair("tool_a", content) + [
            _msg("assistant", "", metadata={"tool_call": "tool_b"}),
            _msg("tool", content, name="tool_b", metadata={"non_compactable": True}),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")
        tool_msgs = [m for m in result_msgs if m.role == "tool"]
        assert tool_msgs[0].content == content
        assert tool_msgs[1].content == content  # protected, never collapsed

    @pytest.mark.asyncio
    async def test_dedup_disabled_flag_is_a_hard_no_op(self) -> None:
        config = CompactionConfig(
            threshold_tokens=10,
            preserve_recent_pairs=0,
            dedup_enabled=False,
            tier_1_enabled=False,
            tier_2_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        content = "v" * 250
        msgs = _tool_pair("tool_a", content) + _tool_pair("tool_b", content)
        result_msgs, _ = await f.filter(msgs, "sys")
        tool_msgs = [m for m in result_msgs if m.role == "tool"]
        assert tool_msgs[1].content == content  # untouched — dedup off


class TestStageATemplatedOneLiners:
    """Templated one-liners ONLY for tools declared reproducible/compactable."""

    @pytest.mark.asyncio
    async def test_compactable_tool_result_becomes_one_liner(self) -> None:
        config = CompactionConfig(
            threshold_tokens=10,
            preserve_recent_pairs=0,
            dedup_enabled=True,
            compactable_tool_names=frozenset({"read_file"}),
            tier_1_enabled=False,
            tier_2_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        content = "line one\nline two\n" * 20
        msgs = _tool_pair("read_file", content) + [_msg("user", "q")]
        result_msgs, _ = await f.filter(msgs, "sys")
        tool_msgs = [m for m in result_msgs if m.role == "tool"]
        assert tool_msgs[0].content != content
        assert "read_file" in tool_msgs[0].content
        assert str(len(content)) in tool_msgs[0].content

    @pytest.mark.asyncio
    async def test_non_compactable_tool_name_left_untouched(self) -> None:
        """Only tools in compactable_tool_names get templated — other unique,
        non-duplicate tool output is left byte-identical."""
        config = CompactionConfig(
            threshold_tokens=10,
            preserve_recent_pairs=0,
            compactable_tool_names=frozenset({"read_file"}),
            tier_1_enabled=False,
            tier_2_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        content = "unique bash output " * 20
        msgs = _tool_pair("bash", content) + [_msg("user", "q")]
        result_msgs, _ = await f.filter(msgs, "sys")
        tool_msgs = [m for m in result_msgs if m.role == "tool"]
        assert tool_msgs[0].content == content

    @pytest.mark.asyncio
    async def test_compactable_tool_preserved_when_recent(self) -> None:
        config = CompactionConfig(
            threshold_tokens=10,
            preserve_recent_pairs=1,
            compactable_tool_names=frozenset({"read_file"}),
            tier_1_enabled=False,
            tier_2_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)
        content = "recent file contents " * 20
        msgs = _tool_pair("read_file", content) + [_msg("user", "q")]
        result_msgs, _ = await f.filter(msgs, "sys")
        tool_msgs = [m for m in result_msgs if m.role == "tool"]
        assert tool_msgs[0].content == content  # only pair — inside recent window


class TestStageAOrderingCheapBeforeExpensive:
    """Ступень A runs first; if it alone satisfies the budget, Tier 1/2/3 never fire."""

    @pytest.mark.asyncio
    async def test_dedup_alone_satisfies_budget_tier1_never_fires(self) -> None:
        content = "d" * 500
        config = CompactionConfig(
            threshold_tokens=100,
            preserve_recent_pairs=0,
            dedup_enabled=True,
            compactable_tool_names=frozenset({"tool_a", "tool_b", "tool_c"}),
            tier_3_enabled=False,  # isolate: dedup alone must satisfy the budget
        )
        f = ConversationCompactionFilter(config=config)
        msgs = (
            _tool_pair("tool_a", content)
            + _tool_pair("tool_b", content)
            + _tool_pair("tool_c", content)
            + [_msg("user", "q")]
        )
        result_msgs, _ = await f.filter(msgs, "sys")
        # No Tier 1 "[Collapsed tool call" markers — templated one-liners covered it
        collapsed = [m for m in result_msgs if "[Collapsed tool call" in m.content]
        assert collapsed == []
        summary = [m for m in result_msgs if "[Conversation summary]" in m.content]
        assert summary == []
        # All 3 results survive as tool-role messages (templated, not dropped)
        assert len([m for m in result_msgs if m.role == "tool"]) == 3


# ---------------------------------------------------------------------------
# Stage 6 — threshold arithmetic: effective = window - max_output_reserve,
# floored for small windows (OpenClaw 16k-model infinite-loop regression).
# ---------------------------------------------------------------------------


class TestEffectiveThresholdArithmetic:
    def test_defaults_to_threshold_tokens_when_window_unset(self) -> None:
        """context_window_tokens is opt-in (None default) — byte-identical to
        pre-Stage-6 behaviour for every existing caller/test."""
        config = CompactionConfig(threshold_tokens=12_345)
        assert config.effective_threshold_tokens == 12_345

    def test_uses_window_minus_reserve_when_smaller_than_threshold(self) -> None:
        config = CompactionConfig(
            threshold_tokens=80_000,
            context_window_tokens=50_000,
            max_output_reserve_tokens=8_000,
        )
        assert config.effective_threshold_tokens == 42_000

    def test_threshold_tokens_still_wins_when_smaller(self) -> None:
        """A tight explicit threshold_tokens is never widened by window math."""
        config = CompactionConfig(
            threshold_tokens=1_000,
            context_window_tokens=200_000,
            max_output_reserve_tokens=8_000,
        )
        assert config.effective_threshold_tokens == 1_000

    def test_floors_for_tiny_windows(self) -> None:
        """Reserve nearly consuming the whole window never drives the
        effective threshold below MIN_EFFECTIVE_THRESHOLD_TOKENS."""
        from swarmline.compaction import MIN_EFFECTIVE_THRESHOLD_TOKENS

        config = CompactionConfig(
            threshold_tokens=80_000,
            context_window_tokens=16_000,
            max_output_reserve_tokens=15_000,
        )
        assert config.effective_threshold_tokens == MIN_EFFECTIVE_THRESHOLD_TOKENS

    @pytest.mark.asyncio
    async def test_small_window_compaction_stabilizes_not_infinite_loop(self) -> None:
        """Regression: a tiny effective window must still terminate cleanly and
        not grow/oscillate when compaction is re-applied across turns.

        codex R1: the original fixture (~755 tokens) never actually EXCEEDED
        the 2000-token floor, so ``filter()`` returned at the very first
        check without compacting anything at all — a vacuous "regression"
        test that could never have caught a real infinite-loop/churn defect.
        Content here is deliberately well ABOVE the floor so the cascade
        genuinely engages.
        """
        from swarmline.compaction import MIN_EFFECTIVE_THRESHOLD_TOKENS

        config = CompactionConfig(
            context_window_tokens=16_000,
            max_output_reserve_tokens=15_000,  # -> floors to MIN_EFFECTIVE_THRESHOLD_TOKENS
            preserve_recent_pairs=0,
        )
        assert config.effective_threshold_tokens == MIN_EFFECTIVE_THRESHOLD_TOKENS

        f = ConversationCompactionFilter(config=config)
        big_content = "hello " * 3000  # ~4500 tokens, well over the 2000 floor
        msgs = [_msg("user", big_content), _msg("user", "latest turn")]
        total_before = f._estimate_total(msgs, "sys")
        assert (
            total_before > MIN_EFFECTIVE_THRESHOLD_TOKENS
        )  # sanity: cascade WILL fire

        first_msgs, _ = await f.filter(msgs, "sys")
        assert len(first_msgs) < len(msgs)  # the cascade actually did something
        assert first_msgs[-1].content == "latest turn"

        f2 = ConversationCompactionFilter(config=config)
        second_msgs, _ = await f2.filter(first_msgs, "sys")
        # Stable — re-compacting an already-compacted, budget-fitting result
        # must not shrink it further (no perpetual churn / no infinite loop).
        assert len(second_msgs) == len(first_msgs)
        assert second_msgs[-1].content == "latest turn"


# ---------------------------------------------------------------------------
# Stage 6 — anti-thrashing cooldown (in-run analog of taskloom's
# compression_history / ANTI_THRASHING_WINDOW=2, MIN_SAVINGS_RATIO=0.10).
# ---------------------------------------------------------------------------


class TestAntiThrashingCooldown:
    @pytest.mark.asyncio
    async def test_tier2_skipped_when_last_two_savings_below_10_percent(self) -> None:
        calls: list[str] = []

        async def mock_llm(prompt: str, dialog_text: str) -> str:
            calls.append(dialog_text)
            return "Summary of the old conversation segment."

        config = CompactionConfig(
            threshold_tokens=20, preserve_recent_pairs=0, tier_1_enabled=False
        )
        history = [
            {"tokens_before": 1_000, "tokens_after": 950},  # 5% savings
            {"tokens_before": 1_000, "tokens_after": 960},  # 4% savings
        ]
        f = ConversationCompactionFilter(
            config=config, llm_call=mock_llm, compression_history=history
        )
        msgs = [
            _msg("user", "msg " * 50),
            _msg("assistant", "reply " * 50),
            _msg("user", "latest"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")
        assert calls == []  # Tier 2 (LLM) never invoked — cooldown active
        assert result_msgs[-1].content == "latest"  # Tier 3 still ran as safety net

    @pytest.mark.asyncio
    async def test_tier2_proceeds_with_only_one_prior_attempt(self) -> None:
        async def mock_llm(prompt: str, dialog_text: str) -> str:
            return _VALID_SUMMARY

        config = CompactionConfig(
            threshold_tokens=20, preserve_recent_pairs=0, tier_1_enabled=False
        )
        history = [{"tokens_before": 1_000, "tokens_after": 950}]  # only 1 entry
        f = ConversationCompactionFilter(
            config=config, llm_call=mock_llm, compression_history=history
        )
        msgs = [
            _msg("user", "msg " * 50),
            _msg("assistant", "reply " * 500),
            _msg("user", "latest"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")
        summary = [m for m in result_msgs if "[Conversation summary]" in m.content]
        assert len(summary) == 1

    @pytest.mark.asyncio
    async def test_tier2_proceeds_when_savings_good(self) -> None:
        async def mock_llm(prompt: str, dialog_text: str) -> str:
            return _VALID_SUMMARY

        config = CompactionConfig(
            threshold_tokens=20, preserve_recent_pairs=0, tier_1_enabled=False
        )
        history = [
            {"tokens_before": 1_000, "tokens_after": 500},
            {"tokens_before": 1_000, "tokens_after": 500},
        ]
        f = ConversationCompactionFilter(
            config=config, llm_call=mock_llm, compression_history=history
        )
        msgs = [
            _msg("user", "msg " * 50),
            _msg("assistant", "reply " * 500),
            _msg("user", "latest"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")
        summary = [m for m in result_msgs if "[Conversation summary]" in m.content]
        assert len(summary) == 1

    @pytest.mark.asyncio
    async def test_successful_tier2_appends_to_compression_history(self) -> None:
        async def mock_llm(prompt: str, dialog_text: str) -> str:
            return _VALID_SUMMARY

        config = CompactionConfig(
            threshold_tokens=20, preserve_recent_pairs=0, tier_1_enabled=False
        )
        f = ConversationCompactionFilter(config=config, llm_call=mock_llm)
        msgs = [
            _msg("user", "msg " * 50),
            _msg("assistant", "reply " * 500),
            _msg("user", "latest"),
        ]
        assert f.compression_history == []
        await f.filter(msgs, "sys")
        assert len(f.compression_history) == 1
        entry = f.compression_history[0]
        assert entry["tokens_before"] > entry["tokens_after"]

    @pytest.mark.asyncio
    async def test_compression_history_capped_to_window_size(self) -> None:
        from swarmline.compaction import ANTI_THRASHING_WINDOW

        async def mock_llm(prompt: str, dialog_text: str) -> str:
            return "Summary of the old conversation segment."

        config = CompactionConfig(
            threshold_tokens=20, preserve_recent_pairs=0, tier_1_enabled=False
        )
        history: list[dict[str, int]] = []
        for _ in range(ANTI_THRASHING_WINDOW + 3):
            f = ConversationCompactionFilter(
                config=config, llm_call=mock_llm, compression_history=history
            )
            msgs = [
                _msg("user", "msg " * 50),
                _msg("assistant", "reply " * 50),
                _msg("user", "latest"),
            ]
            await f.filter(msgs, "sys")
            history = f.compression_history
        assert len(history) == ANTI_THRASHING_WINDOW


# ---------------------------------------------------------------------------
# Stage 6 — safe-fail: ABORT on auth/network, deterministic local fallback
# summary on any other summarizer failure.
# ---------------------------------------------------------------------------


class TestSafeFailAbortVsLocalFallback:
    @pytest.mark.asyncio
    async def test_summarizer_abort_error_returns_true_original_untouched(
        self,
    ) -> None:
        """codex R2 [3a]: ABORT must return the TRUE ORIGINAL input (from
        BEFORE Tier 0/1 ran too), not whatever Tier 0/1 already transformed.
        Tier 0 (dedup) and Tier 1 (collapse) are deliberately left ENABLED
        here, with dedup-eligible duplicate content included, so isolating
        them away can't mask a "returns post-Tier-0/1 state" regression."""
        from swarmline.compaction import SummarizerAbortError

        async def auth_failing_llm(prompt: str, dialog_text: str) -> str:
            raise SummarizerAbortError("401 unauthorized")

        duplicate_content = "x" * 250  # >= DEDUP_MIN_CHARS -- Tier 0 WOULD collapse it
        config = CompactionConfig(
            threshold_tokens=20,
            preserve_recent_pairs=0,
            dedup_enabled=True,
            # tier_1/tier_3 left at their DEFAULTS (enabled) -- NOT isolated
            # away, so Tier 0/1 genuinely run before Tier 2's abort fires.
        )
        f = ConversationCompactionFilter(config=config, llm_call=auth_failing_llm)
        msgs = (
            _tool_pair("tool_a", duplicate_content)
            + _tool_pair("tool_b", duplicate_content)
            + [_msg("user", "latest")]
        )
        result_msgs, result_prompt = await f.filter(msgs, "sys")  # must NOT raise
        assert result_msgs == msgs  # byte-identical to the TRUE original
        assert result_prompt == "sys"
        assert f.compression_history == []  # nothing recorded on abort

    @pytest.mark.asyncio
    async def test_timeout_error_also_aborts_uncompacted(self) -> None:
        async def timeout_llm(prompt: str, dialog_text: str) -> str:
            raise TimeoutError("upstream timed out")

        config = CompactionConfig(
            threshold_tokens=20, preserve_recent_pairs=0, tier_1_enabled=False
        )
        f = ConversationCompactionFilter(config=config, llm_call=timeout_llm)
        msgs = [
            _msg("user", "msg " * 50),
            _msg("assistant", "reply " * 50),
            _msg("user", "latest"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")  # must NOT raise
        assert result_msgs == msgs

    @pytest.mark.asyncio
    async def test_connection_error_also_aborts_uncompacted(self) -> None:
        async def network_llm(prompt: str, dialog_text: str) -> str:
            raise ConnectionError("DNS resolution failed")

        config = CompactionConfig(
            threshold_tokens=20, preserve_recent_pairs=0, tier_1_enabled=False
        )
        f = ConversationCompactionFilter(config=config, llm_call=network_llm)
        msgs = [
            _msg("user", "msg " * 50),
            _msg("assistant", "reply " * 50),
            _msg("user", "latest"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")  # must NOT raise
        assert result_msgs == msgs

    @pytest.mark.asyncio
    async def test_generic_llm_failure_uses_local_fallback_not_abort(self) -> None:
        """A non-auth/network failure (e.g. bad JSON) must NOT abort — it gets
        a deterministic local (non-LLM) fallback summary instead."""

        async def bad_output_llm(prompt: str, dialog_text: str) -> str:
            raise ValueError("malformed model output")

        # threshold small enough to trigger the cascade, Tier 3 disabled so
        # this test isolates Tier 2's fallback behaviour from Tier 3's
        # separate "still too big" truncation path.
        config = CompactionConfig(
            threshold_tokens=20,
            preserve_recent_pairs=0,
            tier_1_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config, llm_call=bad_output_llm)
        msgs = [
            _msg("user", "msg " * 50),
            _msg("assistant", "reply " * 500),
            _msg("user", "latest"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")  # must NOT raise
        summary = [m for m in result_msgs if "[Conversation summary]" in m.content]
        assert len(summary) == 1
        assert "local fallback" in summary[0].content.lower()
        assert result_msgs[-1].content == "latest"

    @pytest.mark.asyncio
    async def test_empty_llm_output_falls_back_to_local_summary(self) -> None:
        """codex R1 [3 MAJOR]: an empty/blank summarizer response is treated
        as a failure (routes to local fallback), never silently embedded."""

        async def empty_llm(prompt: str, dialog_text: str) -> str:
            return "   "

        config = CompactionConfig(
            threshold_tokens=20,
            preserve_recent_pairs=0,
            tier_1_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config, llm_call=empty_llm)
        msgs = [
            _msg("user", "msg " * 50),
            _msg("assistant", "reply " * 500),
            _msg("user", "latest"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")  # must NOT raise
        summary = [m for m in result_msgs if "[Conversation summary]" in m.content]
        assert len(summary) == 1
        assert "local fallback" in summary[0].content.lower()

    @pytest.mark.asyncio
    async def test_degenerate_nonempty_llm_output_falls_back_to_local_summary(
        self,
    ) -> None:
        """codex R2 [3b]: "Summary." is non-empty but still degenerate — no
        section labels, way too short to be a real structured digest. Must
        be treated as a failure (local fallback), not silently accepted
        just because ``str.strip()`` is truthy."""

        async def degenerate_llm(prompt: str, dialog_text: str) -> str:
            return "Summary."

        config = CompactionConfig(
            threshold_tokens=20,
            preserve_recent_pairs=0,
            tier_1_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config, llm_call=degenerate_llm)
        msgs = [
            _msg("user", "msg " * 50),
            _msg("assistant", "reply " * 500),
            _msg("user", "latest"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")  # must NOT raise
        summary = [m for m in result_msgs if "[Conversation summary]" in m.content]
        assert len(summary) == 1
        assert "local fallback" in summary[0].content.lower()
        assert "Summary." not in summary[0].content  # degenerate output discarded

    @pytest.mark.asyncio
    async def test_substantive_prose_without_section_labels_falls_back_to_local_summary(
        self,
    ) -> None:
        """Sprint 1ce CE-15/19 (supersedes the old backward-compat rule): a
        plain-prose summary lacks the fixed sections, so the acceptance gate
        rejects it and the deterministic local fallback is used instead."""

        async def prose_llm(prompt: str, dialog_text: str) -> str:
            return "The user discussed a bug and the agent found the root cause."

        config = CompactionConfig(
            threshold_tokens=20,
            preserve_recent_pairs=0,
            tier_1_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config, llm_call=prose_llm)
        msgs = [
            _msg("user", "msg " * 50),
            _msg("assistant", "reply " * 500),
            _msg("user", "latest"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")  # must NOT raise
        summary = [m for m in result_msgs if "[Conversation summary]" in m.content]
        assert len(summary) == 1
        assert "root cause" not in summary[0].content
        assert "local fallback" in summary[0].content.lower()

    @pytest.mark.asyncio
    async def test_pure_punctuation_output_of_sufficient_length_is_rejected(
        self,
    ) -> None:
        """codex R3 [3]: a length-based-only threshold lets pure punctuation
        of sufficient LENGTH slip through (``"."*20`` has 20 chars but zero
        real words) -- must be treated as degenerate, same as any other
        invalid summarizer output."""

        async def punctuation_llm(prompt: str, dialog_text: str) -> str:
            return "." * 20

        config = CompactionConfig(
            threshold_tokens=20,
            preserve_recent_pairs=0,
            tier_1_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config, llm_call=punctuation_llm)
        msgs = [
            _msg("user", "msg " * 50),
            _msg("assistant", "reply " * 500),
            _msg("user", "latest"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")  # must NOT raise
        summary = [m for m in result_msgs if "[Conversation summary]" in m.content]
        assert len(summary) == 1
        assert "local fallback" in summary[0].content.lower()
        assert "." * 20 not in summary[0].content  # degenerate output discarded

    @pytest.mark.asyncio
    async def test_bare_section_label_with_no_content_is_rejected(self) -> None:
        """codex R3 [3]: a bare fixed-section label with NOTHING after it
        (``"Goal:"``) must not be accepted just because SOME recognized
        label substring is present -- there has to be actual content after
        the label(s), not just the label token itself."""

        async def bare_label_llm(prompt: str, dialog_text: str) -> str:
            return "Goal:"

        config = CompactionConfig(
            threshold_tokens=20,
            preserve_recent_pairs=0,
            tier_1_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config, llm_call=bare_label_llm)
        msgs = [
            _msg("user", "msg " * 50),
            _msg("assistant", "reply " * 500),
            _msg("user", "latest"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")  # must NOT raise
        summary = [m for m in result_msgs if "[Conversation summary]" in m.content]
        assert len(summary) == 1
        assert "local fallback" in summary[0].content.lower()

    @pytest.mark.asyncio
    async def test_local_fallback_preserves_previous_summary_verbatim(self) -> None:
        """codex R1 [3 MAJOR]: when the summarizer fails on a pass where a
        prior summary aged back into the region, the local fallback must
        PRESERVE its real content verbatim — not discard it with a generic
        "updated" note."""

        async def working_llm(prompt: str, dialog_text: str) -> str:
            return _VALID_SUMMARY.replace(
                "Goal: g.", "Goal: first pass goal UNIQUE_MARKER_XYZ."
            )

        config = CompactionConfig(
            threshold_tokens=20,
            preserve_recent_pairs=0,
            tier_1_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config, llm_call=working_llm)
        msgs = [
            _msg("user", "old segment " * 50),
            _msg("assistant", "old reply " * 500),
            _msg("user", "latest one"),
        ]
        first_msgs, _ = await f.filter(msgs, "sys")
        assert any("UNIQUE_MARKER_XYZ" in m.content for m in first_msgs)

        async def failing_llm(prompt: str, dialog_text: str) -> str:
            raise ValueError("bad output")

        f2 = ConversationCompactionFilter(config=config, llm_call=failing_llm)
        grown_msgs = (
            first_msgs[:-1]
            + [_msg("user", "new segment " * 50), _msg("assistant", "new reply " * 500)]
            + first_msgs[-1:]
        )
        result_msgs, _ = await f2.filter(grown_msgs, "sys")
        summary = next(m for m in result_msgs if "[Conversation summary]" in m.content)
        assert "UNIQUE_MARKER_XYZ" in summary.content

    @pytest.mark.asyncio
    async def test_local_fallback_preserves_previous_summary_exactly_no_strip(
        self,
    ) -> None:
        """codex R2 [3c]: the previous summary must be preserved EXACTLY as
        it was persisted — no ``.strip()`` (or any other transformation).
        codex wants true verbatim, not "verbatim modulo whitespace"."""

        async def working_llm(prompt: str, dialog_text: str) -> str:
            return _WHITESPACE_SUMMARY

        config = CompactionConfig(
            threshold_tokens=20,
            preserve_recent_pairs=0,
            tier_1_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config, llm_call=working_llm)
        msgs = [
            _msg("user", "old segment " * 50),
            _msg("assistant", "old reply " * 500),
            _msg("user", "latest one"),
        ]
        first_msgs, _ = await f.filter(msgs, "sys")
        prior_summary_msg = next(
            m for m in first_msgs if "[Conversation summary]" in m.content
        )
        # Sprint 1ce: the body now opens with the code-rendered verbatim request;
        # what an UPDATE/fallback carries forward is the LLM-written part.
        prior_summary_text = _WHITESPACE_SUMMARY
        assert prior_summary_text in prior_summary_msg.content  # sanity: un-stripped

        async def failing_llm(prompt: str, dialog_text: str) -> str:
            raise ValueError("bad output")

        f2 = ConversationCompactionFilter(config=config, llm_call=failing_llm)
        grown_msgs = (
            first_msgs[:-1]
            + [_msg("user", "new segment " * 50), _msg("assistant", "new reply " * 500)]
            + first_msgs[-1:]
        )
        result_msgs, _ = await f2.filter(grown_msgs, "sys")
        summary = next(m for m in result_msgs if "[Conversation summary]" in m.content)
        assert prior_summary_text in summary.content  # exact, un-stripped substring

    @pytest.mark.asyncio
    async def test_local_fallback_does_not_cap_errors(self) -> None:
        """codex R1 [3 MAJOR]: no arbitrary 5-line cap on preserved error
        lines — errors are the whole point of the safe-fail contract."""

        async def failing_llm(prompt: str, dialog_text: str) -> str:
            raise ValueError("bad output")

        config = CompactionConfig(
            threshold_tokens=20,
            preserve_recent_pairs=0,
            tier_1_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config, llm_call=failing_llm)
        error_msgs = [
            _msg("assistant", f"Error: failure number {i} occurred") for i in range(8)
        ]
        # Sprint 1ce: bulk the region up with non-error content so the digest
        # is shorter than what it replaces (acceptance gate).
        msgs = [
            _msg("assistant", "context " * 500),
            *error_msgs,
            _msg("user", "latest"),
        ]
        result_msgs, _ = await f.filter(msgs, "sys")
        summary = next(m for m in result_msgs if "[Conversation summary]" in m.content)
        for i in range(8):
            assert f"failure number {i}" in summary.content


# ---------------------------------------------------------------------------
# Stage 6 Ступень C — structured summary (fixed sections) + iterative UPDATE.
# ---------------------------------------------------------------------------


class TestStructuredSummarySections:
    @pytest.mark.asyncio
    async def test_prompt_requests_all_fixed_sections(self) -> None:
        captured_prompts: list[str] = []

        async def capture_llm(prompt: str, dialog_text: str) -> str:
            captured_prompts.append(prompt)
            return "Summary of the old conversation segment."

        config = CompactionConfig(
            threshold_tokens=20, preserve_recent_pairs=0, tier_1_enabled=False
        )
        f = ConversationCompactionFilter(config=config, llm_call=capture_llm)
        msgs = [
            _msg("user", "msg " * 50),
            _msg("assistant", "reply " * 50),
            _msg("user", "latest"),
        ]
        await f.filter(msgs, "sys")
        assert captured_prompts, "LLM should have been called"
        prompt = captured_prompts[0]
        for section in (
            "Goal:",
            "Constraints:",
            "Progress:",
            "Key Decisions:",
            "Errors:",
            "Files:",
            "Next Steps:",
        ):
            assert section in prompt

    @pytest.mark.asyncio
    async def test_fresh_prompt_has_no_previous_summary_tag(self) -> None:
        captured_prompts: list[str] = []

        async def capture_llm(prompt: str, dialog_text: str) -> str:
            captured_prompts.append(prompt)
            return "Summary of the old conversation segment."

        config = CompactionConfig(
            threshold_tokens=20, preserve_recent_pairs=0, tier_1_enabled=False
        )
        f = ConversationCompactionFilter(config=config, llm_call=capture_llm)
        msgs = [
            _msg("user", "msg " * 50),
            _msg("assistant", "reply " * 50),
            _msg("user", "latest"),
        ]
        await f.filter(msgs, "sys")
        assert "<previous-summary>" not in captured_prompts[0]

    @pytest.mark.asyncio
    async def test_second_compaction_pass_feeds_previous_summary_for_update(
        self,
    ) -> None:
        """A prior [Conversation summary] message aging back into the
        compaction region is extracted and threaded as <previous-summary>
        with PRESERVE/ADD/UPDATE instructions, not re-quoted as raw dialog."""
        captured_prompts: list[str] = []
        captured_dialogs: list[str] = []

        async def capture_llm(prompt: str, dialog_text: str) -> str:
            captured_prompts.append(prompt)
            captured_dialogs.append(dialog_text)
            # codex R3 [3]: needs >= 3 real words after stripping the "Goal:"
            # label to pass the (now word-count-based, not just
            # char-count-based) summary validator -- a bare "Goal: updated
            # goal" (2 words) would be rejected as degenerate and route to
            # local fallback, which isn't what this test is about. Kept
            # short so it still fits the tiny threshold_tokens=20 budget
            # alongside the always-preserved last message.
            return _VALID_SUMMARY

        config = CompactionConfig(
            threshold_tokens=20, preserve_recent_pairs=0, tier_1_enabled=False
        )
        f = ConversationCompactionFilter(config=config, llm_call=capture_llm)
        msgs = [
            _msg("user", "old segment " * 50),
            _msg("assistant", "old reply " * 500),
            _msg("user", "latest one"),
        ]
        first_msgs, _ = await f.filter(msgs, "sys")
        prior_summary_msg = next(
            m for m in first_msgs if "[Conversation summary]" in m.content
        )
        # Sprint 1ce: only the LLM-written part is fed back for UPDATE (the
        # verbatim request and appendices are re-rendered by code each pass).
        assert _VALID_SUMMARY in prior_summary_msg.content
        prior_summary_text = _VALID_SUMMARY

        f2 = ConversationCompactionFilter(config=config, llm_call=capture_llm)
        grown_msgs = (
            first_msgs[:-1]
            + [_msg("user", "new segment " * 50), _msg("assistant", "new reply " * 500)]
            + first_msgs[-1:]
        )
        await f2.filter(grown_msgs, "sys")

        second_prompt = captured_prompts[-1]
        assert "<previous-summary>" in second_prompt
        assert prior_summary_text in second_prompt
        # The previous summary itself must not be re-quoted inside the raw
        # dialog handed to the LLM as if it were a normal turn.
        assert prior_summary_text not in captured_dialogs[-1]

    @pytest.mark.asyncio
    async def test_prior_summary_in_preserved_tail_still_feeds_iterative_update(
        self,
    ) -> None:
        """codex R5: ``_split_for_summarization`` only searched the
        COMPACTABLE region for a prior summary to thread into iterative
        UPDATE -- but the cut boundary (``preserve_recent_pairs``) can just
        as easily land the prior summary INSIDE the preserved tail instead
        of the region. If so, UPDATE silently fails to find it, a FRESH
        (not updated) summary gets built, and the STALE prior summary
        (still sitting untouched in the tail) ends up directly adjacent to
        the fresh one -- exactly the "two summaries stacked" case the whole
        cascade must prevent. Regardless of WHERE the prior summary
        physically sits, the result must always carry exactly ONE summary,
        never two, and iterative UPDATE must still fire."""
        captured_prompts: list[str] = []

        async def capture_llm(prompt: str, dialog_text: str) -> str:
            captured_prompts.append(prompt)
            return _VALID_SUMMARY

        # Pass 1: preserve_count=1 -- a summary is produced normally.
        pass1_config = CompactionConfig(
            threshold_tokens=20,
            preserve_recent_pairs=0,
            tier_1_enabled=False,
            tier_3_enabled=False,
        )
        f1 = ConversationCompactionFilter(config=pass1_config, llm_call=capture_llm)
        msgs = [
            _msg("user", "old segment " * 50),
            _msg("assistant", "old reply " * 500),
            _msg("user", "latest one"),
        ]
        first_msgs, _ = await f1.filter(msgs, "sys")
        assert any("[Conversation summary]" in m.content for m in first_msgs)

        # Pass 2: preserve_count=3 (preserve_recent_pairs=1) -- large enough
        # that, once 2 NEW messages are prepended in FRONT, the prior
        # summary (currently at the FRONT of first_msgs) falls inside the
        # last-3-messages tail instead of the compactable region.
        pass2_config = CompactionConfig(
            threshold_tokens=20,
            preserve_recent_pairs=1,
            tier_1_enabled=False,
            tier_3_enabled=False,
        )
        f2 = ConversationCompactionFilter(config=pass2_config, llm_call=capture_llm)
        second_input = [
            _msg("user", "brand new old content " * 50),
            _msg("assistant", "short filler " * 300),
            *first_msgs,
        ]
        # Sanity: the prior summary really is inside the tail region, not
        # the compactable front, for THIS cut boundary.
        preserve_count = 3
        assert any(
            "[Conversation summary]" in m.content
            for m in second_input[-preserve_count:]
        )

        second_result, _ = await f2.filter(second_input, "sys")

        second_prompt = captured_prompts[-1]
        assert "<previous-summary>" in second_prompt, (
            "prior summary aged into the preserved TAIL was never found "
            "for iterative UPDATE"
        )
        summary_count = sum(
            1 for m in second_result if "[Conversation summary]" in m.content
        )
        assert summary_count == 1, (
            f"expected exactly 1 summary (UPDATE, not stacked), got {summary_count}"
        )

    @pytest.mark.asyncio
    async def test_non_compactable_summary_in_preserved_tail_survives_and_stays_unique(
        self,
    ) -> None:
        """codex R6: the preserved-tail prior-summary search (R5 fix) must
        NEVER remove a summary message that is itself tagged
        ``metadata.non_compactable=True`` -- that would violate the
        "protected messages are never removed/rewritten" contract just to
        satisfy the "at most one summary" invariant. But simply skipping
        the deletion isn't enough either: a FRESH competing summary would
        still get built for the compactable region and end up sitting
        alongside the (correctly un-removed) protected one, violating "at
        most one summary" from the OTHER direction. Both must hold at
        once: the protected summary survives untouched, AND no competing
        summary is created this pass (in normal flow a summary is never
        tagged non_compactable -- this covers the pathological externally-
        protected case; the protected one is treated as authoritative)."""

        async def mock_llm(prompt: str, dialog_text: str) -> str:
            return "Goal: goal is updated"

        config = CompactionConfig(
            threshold_tokens=20,
            preserve_recent_pairs=1,  # preserve_count=3
            tier_1_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config, llm_call=mock_llm)
        protected_summary = _msg(
            "system",
            "[Conversation summary]: OLD_PROTECTED_MARKER",
            metadata={"non_compactable": True},
        )
        msgs = [
            _msg("user", "old content " * 50),
            _msg("assistant", "short filler"),
            protected_summary,  # lands in the preserved tail (last 3)
            _msg("user", "latest"),
        ]
        # Sanity: protected_summary really is inside the tail for this cut.
        preserve_count = 3
        assert protected_summary in msgs[-preserve_count:]

        result_msgs, _ = await f.filter(msgs, "sys")

        assert any("OLD_PROTECTED_MARKER" in m.content for m in result_msgs), (
            "the non_compactable prior summary was removed from the tail "
            "-- protected-message contract violated"
        )
        summary_count = sum(
            1 for m in result_msgs if "[Conversation summary]" in m.content
        )
        assert summary_count == 1, (
            "expected exactly 1 summary (the protected one, no competing "
            f"fresh summary created), got {summary_count}"
        )

    @pytest.mark.asyncio
    async def test_non_compactable_summary_in_region_survives_and_stays_unique(
        self,
    ) -> None:
        """codex R6b: symmetric to the tail case above, but with the
        protected (non_compactable) prior summary physically sitting in the
        COMPACTABLE REGION instead of the preserved tail. The region path's
        ``protected_indices`` check already correctly keeps this message
        out of ``compactable`` (it is never removed/rewritten -- the
        contract holds structurally, ``non_compactable_with_pos`` never
        drops anything). But that alone is NOT enough: a FRESH summary
        still gets built from the rest of the region's compactable
        content, and ``_reassemble_region`` places it at
        ``summary_insert_pos`` -- which, when the protected summary sits
        right before the first ordinary compactable message, lands the
        fresh summary DIRECTLY ADJACENT to the protected one (both exempt
        from ``_merge_adjacent_system_messages``, per fix-cycle 4), so BOTH
        survive side by side -- violating "at most one summary" exactly
        like the tail case did before its own guard."""

        async def mock_llm(prompt: str, dialog_text: str) -> str:
            return "Goal: goal is updated"

        config = CompactionConfig(
            threshold_tokens=20,
            preserve_recent_pairs=0,  # preserve_count=1
            tier_1_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config, llm_call=mock_llm)
        protected_summary = _msg(
            "system",
            "[Conversation summary]: OLD_PROTECTED_MARKER",
            metadata={"non_compactable": True},
        )
        msgs = [
            protected_summary,  # in the compactable REGION, not the tail
            _msg("user", "old content " * 50),
            _msg("assistant", "old reply " * 50),
            _msg("user", "latest"),
        ]
        # Sanity: protected_summary really is inside the region for this
        # cut, NOT the preserved tail.
        preserve_count = 1
        assert protected_summary not in msgs[-preserve_count:]
        assert protected_summary in msgs[:-preserve_count]

        result_msgs, _ = await f.filter(msgs, "sys")

        assert any("OLD_PROTECTED_MARKER" in m.content for m in result_msgs), (
            "the non_compactable prior summary was removed/rewritten from "
            "the region -- protected-message contract violated"
        )
        summary_count = sum(
            1 for m in result_msgs if "[Conversation summary]" in m.content
        )
        assert summary_count == 1, (
            "expected exactly 1 summary (the protected one, no competing "
            f"fresh summary created), got {summary_count}"
        )
