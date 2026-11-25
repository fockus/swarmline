"""Tests for swarmline.context.prompt_caching — Stage 2 (context-engineering-manus-parity).

TDD file: written BEFORE implementation. Covers the Hermes ``system_and_3`` cache_control
breakpoint recipe: a breakpoint on the system prompt + on the last 3 non-system messages
with non-empty content (Anthropic's per-request ceiling is 4 cache_control breakpoints).
"""

from __future__ import annotations

import pytest

from swarmline.context.prompt_caching import (
    DEFAULT_BOUNDARY_MARKER,
    build_cached_system,
    mark_last_message_breakpoints,
)

# ---------------------------------------------------------------------------
# build_cached_system
# ---------------------------------------------------------------------------


class TestBuildCachedSystem:
    def test_non_empty_system_prompt_wrapped_in_cache_control_block(self) -> None:
        result = build_cached_system("You are a helpful assistant.")

        assert result == [
            {
                "type": "text",
                "text": "You are a helpful assistant.",
                "cache_control": {"type": "ephemeral"},
            }
        ]

    def test_empty_system_prompt_passes_through_unchanged(self) -> None:
        """Anthropic rejects an empty cache_control text block — and there is nothing
        worth caching in an empty prompt anyway."""
        assert build_cached_system("") == ""

    def test_blank_system_prompt_passes_through_unchanged(self) -> None:
        assert build_cached_system("   \n  ") == "   \n  "

    def test_does_not_mutate_between_calls(self) -> None:
        """Each call returns an independent list/dict — mutating one result must never
        affect a later call's result."""
        r1 = build_cached_system("same prompt")
        r2 = build_cached_system("same prompt")
        r1[0]["cache_control"]["type"] = "mutated"  # type: ignore[index]

        assert r2[0]["cache_control"] == {"type": "ephemeral"}  # type: ignore[index]


# ---------------------------------------------------------------------------
# mark_last_message_breakpoints (system_and_3 recipe, message side)
# ---------------------------------------------------------------------------


class TestMarkLastMessageBreakpoints:
    def test_no_messages_returns_empty_list(self) -> None:
        assert mark_last_message_breakpoints([]) == []

    def test_single_eligible_message_gets_one_breakpoint(self) -> None:
        messages = [{"role": "user", "content": "hi"}]

        result = mark_last_message_breakpoints(messages)

        assert result[0]["content"] == [
            {"type": "text", "text": "hi", "cache_control": {"type": "ephemeral"}}
        ]

    def test_at_most_three_message_breakpoints_placed(self) -> None:
        """5 eligible messages -> only the LAST 3 get a cache_control breakpoint (Anthropic
        per-request ceiling: 1 system + 3 messages = 4 total)."""
        messages = [
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "two"},
            {"role": "user", "content": "three"},
            {"role": "assistant", "content": "four"},
            {"role": "user", "content": "five"},
        ]

        result = mark_last_message_breakpoints(messages)

        marked = [
            i
            for i, m in enumerate(result)
            if isinstance(m["content"], list)
            and any("cache_control" in b for b in m["content"])
        ]
        assert marked == [2, 3, 4]

    def test_exactly_three_eligible_messages_all_marked(self) -> None:
        messages = [
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "two"},
            {"role": "user", "content": "three"},
        ]

        result = mark_last_message_breakpoints(messages)

        for m in result:
            assert isinstance(m["content"], list)
            assert m["content"][-1]["cache_control"] == {"type": "ephemeral"}

    def test_empty_string_content_message_never_gets_a_breakpoint(self) -> None:
        """Anthropic rejects an empty-text cache_control block — an empty/blank message
        must never be chosen as a breakpoint, even if it is one of the last 3."""
        messages = [
            {"role": "user", "content": "keep me 1"},
            {"role": "assistant", "content": "keep me 2"},
            {"role": "user", "content": "keep me 3"},
            {"role": "assistant", "content": "   "},
        ]

        result = mark_last_message_breakpoints(messages)

        assert result[-1]["content"] == "   "  # untouched: blank, ineligible
        marked = [
            i for i, m in enumerate(result[:-1]) if isinstance(m["content"], list)
        ]
        assert marked == [0, 1, 2]

    def test_empty_content_list_message_never_gets_a_breakpoint(self) -> None:
        messages = [
            {"role": "user", "content": "keep me"},
            {"role": "assistant", "content": []},
        ]

        result = mark_last_message_breakpoints(messages)

        assert result[1]["content"] == []
        assert result[0]["content"] == [
            {"type": "text", "text": "keep me", "cache_control": {"type": "ephemeral"}}
        ]

    def test_system_role_messages_are_never_eligible_breakpoints(self) -> None:
        """system is handled separately by build_cached_system — a stray system-role
        entry inside the messages list (should not normally happen) must never itself
        become one of the 3 message breakpoints."""
        messages = [
            {"role": "system", "content": "ignored here"},
            {"role": "user", "content": "hi"},
        ]

        result = mark_last_message_breakpoints(messages)

        assert result[0]["content"] == "ignored here"
        assert isinstance(result[1]["content"], list)

    def test_content_blocks_list_only_last_block_gets_cache_control(self) -> None:
        """A message whose content is ALREADY a list of blocks (e.g. image + text, or a
        tool_use/tool_result pair folded into one message) must keep every block, in
        order, with cache_control added ONLY to the last one — never split/reordered."""
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": "abc",
                        },
                    },
                    {"type": "text", "text": "describe this"},
                ],
            }
        ]

        result = mark_last_message_breakpoints(messages)

        blocks = result[0]["content"]
        assert len(blocks) == 2
        assert blocks[0] == {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": "abc"},
        }
        assert blocks[1]["cache_control"] == {"type": "ephemeral"}
        assert blocks[1]["text"] == "describe this"

    def test_does_not_mutate_input_messages(self) -> None:
        messages = [{"role": "user", "content": "hi"}]

        mark_last_message_breakpoints(messages)

        assert messages[0]["content"] == "hi"

    def test_idempotent_across_repeated_calls_on_the_same_raw_messages(self) -> None:
        """Retries call this again on the SAME original (unmarked) messages, not on the
        previous call's output — so byte-identical results across calls is the actual
        idempotency contract that matters for retry-safety."""
        messages = [
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "two"},
        ]

        r1 = mark_last_message_breakpoints(messages)
        r2 = mark_last_message_breakpoints(messages)

        assert r1 == r2


@pytest.mark.parametrize("eligible_count", [0, 1, 2, 3, 4])
def test_breakpoint_count_never_exceeds_three_or_available_eligible_messages(
    eligible_count: int,
) -> None:
    messages = [{"role": "user", "content": f"msg-{i}"} for i in range(eligible_count)]

    result = mark_last_message_breakpoints(messages)

    marked = sum(
        1
        for m in result
        if isinstance(m["content"], list)
        and any("cache_control" in b for b in m["content"])
    )
    assert marked == min(eligible_count, 3)


# ---------------------------------------------------------------------------
# Fix-cycle 1 BLOCKER: build_cached_system splits on the boundary marker so it
# never caches a per-turn dynamic suffix
# ---------------------------------------------------------------------------


def _assert_marker_absent(
    result: object, marker: str = DEFAULT_BOUNDARY_MARKER
) -> None:
    """Fix-cycle 3 (B-1) property assertion: the literal boundary marker must NEVER
    appear anywhere in build_cached_system's output, regardless of shape (a plain
    str, or a list of blocks) or branch (normal split, degenerate both-blank, or
    no-marker fallback) — consistency across all of them is the whole point."""
    if isinstance(result, str):
        assert marker not in result, (
            f"marker literal leaked into str output: {result!r}"
        )
        return
    for block in result:
        assert marker not in block.get("text", ""), (
            f"marker literal leaked into block: {block!r}"
        )


class TestBuildCachedSystemBoundarySplit:
    def test_marker_present_splits_into_cached_static_and_uncached_dynamic_blocks(
        self,
    ) -> None:
        prompt = f"Static rules here.{DEFAULT_BOUNDARY_MARKER}Dynamic plan status here."

        result = build_cached_system(prompt)

        assert result == [
            {
                "type": "text",
                "text": "Static rules here.",
                "cache_control": {"type": "ephemeral"},
            },
            {"type": "text", "text": "Dynamic plan status here."},
        ]
        _assert_marker_absent(result)

    def test_static_block_byte_identical_across_two_builds_with_different_dynamic_suffix(
        self,
    ) -> None:
        """Two-turn payload test (lead's requirement): same static, different dynamic
        -> the CACHED block is byte-identical; only the uncached block differs."""
        turn1 = f"Static rules here.{DEFAULT_BOUNDARY_MARKER}Plan: step 1 pending."
        turn2 = f"Static rules here.{DEFAULT_BOUNDARY_MARKER}Plan: step 1 done, step 2 pending."

        result1 = build_cached_system(turn1)
        result2 = build_cached_system(turn2)

        assert result1[0] == result2[0]  # static+cache_control block unchanged
        assert result1[1] != result2[1]  # dynamic block differs
        assert "cache_control" not in result1[1]
        assert "cache_control" not in result2[1]
        _assert_marker_absent(result1)
        _assert_marker_absent(result2)

    def test_no_marker_falls_back_to_whole_prompt_cached_as_one_block(self) -> None:
        """A host with no static/dynamic split (e.g. a non-taskloom swarmline user)
        gets the ORIGINAL single-cached-block behaviour."""
        result = build_cached_system("Just a plain system prompt, no marker at all.")

        assert result == [
            {
                "type": "text",
                "text": "Just a plain system prompt, no marker at all.",
                "cache_control": {"type": "ephemeral"},
            }
        ]
        _assert_marker_absent(result)

    def test_marker_with_blank_dynamic_side_omits_the_dynamic_block(self) -> None:
        prompt = f"Static only.{DEFAULT_BOUNDARY_MARKER}   "

        result = build_cached_system(prompt)

        assert result == [
            {
                "type": "text",
                "text": "Static only.",
                "cache_control": {"type": "ephemeral"},
            }
        ]
        _assert_marker_absent(result)

    def test_marker_with_blank_static_side_omits_the_static_block(self) -> None:
        prompt = f"   {DEFAULT_BOUNDARY_MARKER}Dynamic only."

        result = build_cached_system(prompt)

        assert result == [{"type": "text", "text": "Dynamic only."}]
        _assert_marker_absent(result)

    def test_marker_present_but_both_sides_blank_returns_marker_stripped_remainder(
        self,
    ) -> None:
        """Fix-cycle 3 (B-1): the degenerate both-blank case used to fall back to the
        RAW ``system_prompt`` (marker included) — inconsistent with every other
        branch, which never lets the marker leak into the output. Now returns the
        marker-stripped remainder (whatever whitespace surrounded the marker), same
        type (``str``) as the "nothing worth caching" contract elsewhere."""
        prompt = f"  {DEFAULT_BOUNDARY_MARKER}  "

        result = build_cached_system(prompt)

        assert result == "    "  # static_part ("  ") + dynamic_part ("  "), marker gone
        _assert_marker_absent(result)

    def test_marker_present_both_sides_fully_empty_returns_empty_string(self) -> None:
        """Edge of the edge: no surrounding whitespace at all -> empty remainder."""
        prompt = DEFAULT_BOUNDARY_MARKER

        result = build_cached_system(prompt)

        assert result == ""
        _assert_marker_absent(result)

    def test_custom_boundary_marker_is_respected(self) -> None:
        result = build_cached_system("static<SPLIT>dynamic", boundary_marker="<SPLIT>")

        assert result == [
            {"type": "text", "text": "static", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "dynamic"},
        ]
        _assert_marker_absent(result, marker="<SPLIT>")

    def test_repeated_marker_back_to_back_leaves_no_marker_in_output(self) -> None:
        """Fix-cycle 4 (B-1 counterexample, codex round 4): ``partition()`` only
        removes the FIRST occurrence — a second (or later) occurrence used to survive
        untouched inside the dynamic side. Repeated markers are garbage input (never
        produced by a well-behaved static/dynamic builder) and must be scrubbed."""
        prompt = f"{DEFAULT_BOUNDARY_MARKER}{DEFAULT_BOUNDARY_MARKER}"

        result = build_cached_system(prompt)

        _assert_marker_absent(result)
        assert result == ""

    def test_repeated_marker_with_static_and_dynamic_content_leaves_no_marker(
        self,
    ) -> None:
        prompt = f"static{DEFAULT_BOUNDARY_MARKER}mid{DEFAULT_BOUNDARY_MARKER}tail"

        result = build_cached_system(prompt)

        _assert_marker_absent(result)
        assert result == [
            {"type": "text", "text": "static", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "midtail"},
        ]

    def test_marker_repeated_three_times_leaves_no_marker_in_output(self) -> None:
        prompt = DEFAULT_BOUNDARY_MARKER * 3

        result = build_cached_system(prompt)

        _assert_marker_absent(result)
        assert result == ""


# ---------------------------------------------------------------------------
# Fix-cycle 1 MAJOR-4: TTL 5m (default, no ttl key) / 1h (explicit ttl key)
# ---------------------------------------------------------------------------


class TestCacheControlTTL:
    def test_default_ttl_is_5m_and_omits_ttl_key(self) -> None:
        result = build_cached_system("prompt")
        assert result[0]["cache_control"] == {"type": "ephemeral"}
        assert "ttl" not in result[0]["cache_control"]

    def test_explicit_1h_ttl_adds_ttl_key(self) -> None:
        result = build_cached_system("prompt", ttl="1h")
        assert result[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}

    def test_message_breakpoints_respect_ttl_too(self) -> None:
        messages = [{"role": "user", "content": "hi"}]
        result = mark_last_message_breakpoints(messages, ttl="1h")
        assert result[0]["content"][-1]["cache_control"] == {
            "type": "ephemeral",
            "ttl": "1h",
        }


# ---------------------------------------------------------------------------
# Fix-cycle 1 MAJOR-1: pre-existing cache_control in input messages is
# stripped, never inflating the total breakpoint count past 3 new ones
# ---------------------------------------------------------------------------


class TestExistingCacheControlStripped:
    def test_pre_existing_cache_control_on_non_selected_message_is_stripped(
        self,
    ) -> None:
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "old",
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            },
            {"role": "assistant", "content": "a"},
            {"role": "user", "content": "b"},
            {"role": "assistant", "content": "c"},
        ]

        result = mark_last_message_breakpoints(messages)

        # message 0 is NOT one of the last 3 (indices 1,2,3 are) -> its stray
        # cache_control must be stripped, not left in place.
        assert "cache_control" not in result[0]["content"][0]

    def test_total_breakpoints_never_exceed_three_even_with_pre_existing_ones(
        self,
    ) -> None:
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "old1",
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            },
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "old2",
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            },
            {"role": "user", "content": "c"},
            {"role": "assistant", "content": "d"},
            {"role": "user", "content": "e"},
        ]

        result = mark_last_message_breakpoints(messages)

        total = sum(
            1
            for m in result
            if isinstance(m["content"], list)
            for block in m["content"]
            if isinstance(block, dict) and "cache_control" in block
        )
        assert total == 3

    def test_pre_existing_cache_control_on_a_selected_messages_own_earlier_block_is_stripped(
        self,
    ) -> None:
        """A message that IS selected, but has a stray cache_control on a block
        OTHER than the last one, must not keep two cache_control blocks."""
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "first block",
                        "cache_control": {"type": "ephemeral"},
                    },
                    {"type": "text", "text": "last block"},
                ],
            }
        ]

        result = mark_last_message_breakpoints(messages)

        blocks = result[0]["content"]
        assert "cache_control" not in blocks[0]
        assert blocks[1]["cache_control"] == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# Fix-cycle 1 MAJOR-2: eligibility checks the LAST block specifically
# ---------------------------------------------------------------------------


class TestLastBlockCacheabilityEligibility:
    def test_trailing_empty_text_block_after_real_text_is_never_marked(self) -> None:
        """codex's exact repro: [{text:"real"},{text:""}] -> last block is empty text
        -> message must be skipped (not marked), even though the block LIST itself
        is non-empty."""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "real"},
                    {"type": "text", "text": ""},
                ],
            }
        ]

        result = mark_last_message_breakpoints(messages)

        for block in result[0]["content"]:
            assert "cache_control" not in block

    def test_message_with_empty_last_block_does_not_consume_a_breakpoint_slot(
        self,
    ) -> None:
        """An ineligible trailing-empty-block message must not push an otherwise-
        eligible earlier message out of the last-3 window."""
        messages = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "d"},
                    {"type": "text", "text": ""},
                ],
            },
        ]

        result = mark_last_message_breakpoints(messages)

        marked = [
            i
            for i, m in enumerate(result)
            if isinstance(m["content"], list)
            and any("cache_control" in b for b in m["content"])
        ]
        assert marked == [0, 1, 2]

    def test_tool_result_only_message_is_eligible(self) -> None:
        """A message whose ONLY content is a tool_result block (the normal native
        tool-calling shape right after a tool call) must be eligible — Anthropic
        supports cache_control on any non-text block, not just text."""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "call_1", "content": "42"}
                ],
            }
        ]

        result = mark_last_message_breakpoints(messages)

        assert result[0]["content"][0]["cache_control"] == {"type": "ephemeral"}

    def test_real_tool_use_then_tool_result_exchange_both_eligible(self) -> None:
        """Realistic native tool-calling exchange: assistant tool_use -> user
        tool_result -> assistant follow-up text. Last 3 messages all get breakpoints."""
        messages = [
            {"role": "user", "content": "What's 2+2?"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call_1",
                        "name": "add",
                        "input": {"a": 2, "b": 2},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "call_1", "content": "4"}
                ],
            },
        ]

        result = mark_last_message_breakpoints(messages)

        for m in result:
            assert isinstance(m["content"], list)
            assert m["content"][-1]["cache_control"] == {"type": "ephemeral"}

    def test_consecutive_assistant_messages_are_each_independently_eligible(
        self,
    ) -> None:
        messages = [
            {"role": "assistant", "content": "first"},
            {"role": "assistant", "content": "second"},
        ]

        result = mark_last_message_breakpoints(messages)

        assert result[0]["content"][-1]["cache_control"] == {"type": "ephemeral"}
        assert result[1]["content"][-1]["cache_control"] == {"type": "ephemeral"}

    def test_all_system_messages_yield_no_breakpoints(self) -> None:
        messages = [
            {"role": "system", "content": "a"},
            {"role": "system", "content": "b"},
        ]

        result = mark_last_message_breakpoints(messages)

        assert result[0]["content"] == "a"
        assert result[1]["content"] == "b"


# ---------------------------------------------------------------------------
# Fix-cycle 1 MAJOR-5: fail-open on malformed (non-dict) content blocks
# ---------------------------------------------------------------------------


class TestFailOpenOnMalformedBlocks:
    def test_non_dict_block_in_content_list_makes_message_ineligible_not_raise(
        self,
    ) -> None:
        messages = [{"role": "user", "content": ["not-a-dict", "still-not-a-dict"]}]

        result = mark_last_message_breakpoints(messages)  # must not raise

        assert result[0]["content"] == ["not-a-dict", "still-not-a-dict"]

    def test_non_dict_block_does_not_block_other_eligible_messages(self) -> None:
        messages = [
            {"role": "user", "content": "fine"},
            {"role": "assistant", "content": ["broken", 123]},
        ]

        result = mark_last_message_breakpoints(messages)  # must not raise

        assert result[0]["content"][-1]["cache_control"] == {"type": "ephemeral"}
        assert result[1]["content"] == ["broken", 123]


# ---------------------------------------------------------------------------
# Fix-cycle 1 MINOR-1: deep copy — no aliasing of nested block structures
# ---------------------------------------------------------------------------


class TestDeepCopyNoNestedAliasing:
    def test_mutating_returned_image_source_does_not_affect_original_input(
        self,
    ) -> None:
        original_source = {"type": "base64", "media_type": "image/png", "data": "abc"}
        messages = [
            {"role": "user", "content": [{"type": "image", "source": original_source}]}
        ]

        result = mark_last_message_breakpoints(messages)
        result[0]["content"][0]["source"]["data"] = "MUTATED"

        assert original_source["data"] == "abc"
        assert messages[0]["content"][0]["source"]["data"] == "abc"

    def test_retrying_after_a_mutated_previous_result_still_reproduces_original(
        self,
    ) -> None:
        """Simulates the real retry hazard MINOR-1 flags: even if a caller mutates a
        PREVIOUS call's returned blocks, re-calling on the SAME original messages
        must still reproduce the untouched original."""
        original_source = {"type": "base64", "media_type": "image/png", "data": "abc"}
        messages = [
            {"role": "user", "content": [{"type": "image", "source": original_source}]}
        ]

        first = mark_last_message_breakpoints(messages)
        first[0]["content"][0]["source"]["data"] = "MUTATED-BY-CALLER"
        second = mark_last_message_breakpoints(messages)

        assert second[0]["content"][0]["source"]["data"] == "abc"

    def test_mutating_a_non_selected_messages_nested_source_does_not_affect_original(
        self,
    ) -> None:
        """Fix-cycle 3 (B-8): the earlier deep-copy tests above only ever exercised a
        SELECTED (breakpoint-marked) message — a message with list-form content that
        is NOT one of the last 3 (never selected) used to pass through via a shallow
        ``dict(message)``, aliasing its nested ``source`` dict with the original
        input. Four eligible messages here -> the FIRST (the image one) is NOT among
        the last 3 selected."""
        original_source = {"type": "base64", "media_type": "image/png", "data": "abc"}
        messages = [
            {"role": "user", "content": [{"type": "image", "source": original_source}]},
            {"role": "assistant", "content": "a"},
            {"role": "user", "content": "b"},
            {"role": "assistant", "content": "c"},
        ]

        result = mark_last_message_breakpoints(messages)
        assert "cache_control" not in result[0]["content"][0]  # confirms NOT selected

        result[0]["content"][0]["source"]["data"] = "MUTATED"

        assert original_source["data"] == "abc"
        assert messages[0]["content"][0]["source"]["data"] == "abc"
