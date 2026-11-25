"""Stage 6 (context-engineering-manus-parity) — cross-cutting compaction
invariants that must hold across EVERY tier (Ступень A, Tier 1/2/3):

1. Cut-point never splits a tool_use/tool_result pair — property test on
   random synthetic histories (stdlib ``random``; ``hypothesis`` is not an
   installed dependency and this project avoids adding new libraries for
   what a seeded PRNG loop already covers).
2. History is append-only — compaction COLLAPSES (returns a new list),
   it never mutates the caller's original ``messages`` list in place.
"""

from __future__ import annotations

import copy
import random

import pytest

from swarmline.compaction import CompactionConfig, ConversationCompactionFilter
from swarmline.domain_types import Message

_TOOL_NAMES = ["read_file", "grep", "bash", "write_file", "list_dir"]


def _msg(
    role: str,
    content: str,
    name: str | None = None,
    metadata: dict | None = None,
    tool_calls: list[dict] | None = None,
) -> Message:
    return Message(
        role=role, content=content, name=name, metadata=metadata, tool_calls=tool_calls
    )


_PRIOR_SUMMARY_MARKER = "[Conversation summary]: an earlier compaction pass"


def _random_history(
    rng: random.Random, length: int, *, seed_prior_summary: bool = False
) -> list[Message]:
    """Build a synthetic history mixing plain turns and tool call/result
    pairs, with randomized sizes, duplicate content, and non_compactable
    tags — deliberately messy input for the cascade to chew through.

    ``seed_prior_summary`` occasionally inserts a pre-existing
    ``[Conversation summary]`` message near the front (simulating an earlier
    compaction pass aging back into this pass's region), to exercise the
    "no two summary messages end up adjacent" invariant — the iterative
    UPDATE design must MERGE into one, never stack two.
    """
    messages: list[Message] = []
    if seed_prior_summary and rng.random() < 0.5:
        messages.append(_msg("system", _PRIOR_SUMMARY_MARKER))
    shared_blob = "shared duplicate content " * 20  # >= DEDUP_MIN_CHARS
    for _ in range(length):
        kind = rng.choice(["user", "assistant", "tool_pair", "native_tool_group"])
        if kind == "user":
            messages.append(_msg("user", "u " * rng.randint(1, 200)))
        elif kind == "assistant":
            messages.append(_msg("assistant", "a " * rng.randint(1, 200)))
        elif kind == "tool_pair":
            # Legacy text-ReAct shape: assistant metadata["tool_call"] + 1 result.
            tool_name = rng.choice(_TOOL_NAMES)
            content = (
                shared_blob
                if rng.random() < 0.3
                else f"result {rng.randint(0, 10_000)} " * rng.randint(1, 50)
            )
            metadata = {"non_compactable": True} if rng.random() < 0.1 else None
            messages.append(_msg("assistant", "", metadata={"tool_call": tool_name}))
            messages.append(_msg("tool", content, name=tool_name, metadata=metadata))
        else:
            # Native tool-calling shape: ONE assistant with N tool_calls,
            # followed by N tool-role results (REQ: codex R1 [1 CRITICAL]).
            n_calls = rng.randint(1, 3)
            call_names = [rng.choice(_TOOL_NAMES) for _ in range(n_calls)]
            messages.append(
                _msg(
                    "assistant",
                    "",
                    tool_calls=[
                        {"id": f"call-{i}", "name": name, "args": {}}
                        for i, name in enumerate(call_names)
                    ],
                )
            )
            for i, name in enumerate(call_names):
                content = (
                    shared_blob
                    if rng.random() < 0.3
                    else f"result {rng.randint(0, 10_000)} " * rng.randint(1, 50)
                )
                metadata = {"non_compactable": True} if rng.random() < 0.1 else None
                messages.append(_msg("tool", content, name=name, metadata=metadata))
    messages.append(_msg("user", "final question"))
    return messages


def _assert_no_adjacent_summary_messages(messages: list[Message]) -> None:
    """No two adjacent messages are BOTH a `[Conversation summary]` marker —
    the iterative UPDATE (Ступень C) must MERGE an aged-back-in prior
    summary into the new one, never stack two side by side."""
    for i in range(len(messages) - 1):
        both_summaries = "[Conversation summary]" in messages[i].content and (
            "[Conversation summary]" in messages[i + 1].content
        )
        assert not both_summaries, (
            f"Two adjacent [Conversation summary] messages at indices {i}/{i + 1} "
            "— the iterative UPDATE should have merged them into one"
        )


def _assert_at_most_one_summary_message(messages: list[Message]) -> None:
    """codex R5: regardless of WHERE a prior summary physically sits (the
    compactable region OR the preserved tail -- the cut boundary doesn't
    know or care), the result must carry AT MOST ONE `[Conversation
    summary]` message. Iterative UPDATE must always MERGE into the single
    surviving summary, never leave a stale one stacked alongside a fresh
    one (stronger than adjacency-only: catches the case where a NON-system
    message happens to separate them too, which is still a stack, just not
    a directly-adjacent one)."""
    count = sum(1 for m in messages if "[Conversation summary]" in m.content)
    assert count <= 1, (
        f"expected at most 1 summary message in the result, found {count}"
    )


def _assert_no_adjacent_collapse_placeholder_messages(messages: list[Message]) -> None:
    """No two adjacent Tier-1 collapsed-tool-call placeholder messages --
    `_collapse_tool_results` already merges every RUN of consecutive
    collapsible groups into ONE system message (codex R1 [2 MAJOR]); two
    such placeholders ever appearing back to back would mean that merge
    regressed.

    Narrower than the old blanket "no two adjacent system-role messages
    anywhere" check this replaces (codex R5): a protected (non_compactable)
    system message directly next to the summary is now an ACCEPTED
    exception (fix-cycle 4) -- they are semantically DIFFERENT kinds of
    system content, and the Anthropic API auto-merges consecutive
    same-role messages server-side with no information loss. What must
    still NEVER happen is two summaries stacked (see
    ``_assert_at_most_one_summary_message``/``_assert_no_adjacent_summary_
    messages`` above) or two Tier-1 placeholders stacked (this check)."""
    placeholder_prefix = "[Collapsed tool call:"
    for i in range(len(messages) - 1):
        both_placeholders = messages[i].content.startswith(
            placeholder_prefix
        ) and messages[i + 1].content.startswith(placeholder_prefix)
        assert not both_placeholders, (
            f"Two adjacent Tier-1 collapse-placeholder messages at indices "
            f"{i}/{i + 1} — _collapse_tool_results should have merged them "
            "into one"
        )


def _assert_no_orphaned_tool_pairs(messages: list[Message]) -> None:
    """Every surviving tool-call assistant message (legacy metadata["tool_call"]
    single-result shape, OR native ``tool_calls``-list multi-result shape) is
    immediately followed by ALL of its own tool results, and no tool-role
    message survives without being consumed by a preceding group — the group
    is never split apart, whichever shape produced it."""
    i = 0
    n = len(messages)
    while i < n:
        msg = messages[i]
        if msg.role == "assistant" and msg.tool_calls:
            k = len(msg.tool_calls)
            for j in range(k):
                idx = i + 1 + j
                assert idx < n, (
                    f"Orphaned native tool_calls group at index {i} (result slot "
                    f"{j} missing — only {n - i - 1} messages remain): {msg}"
                )
                assert messages[idx].role == "tool", (
                    f"Native tool_calls group at index {i}: result slot {j} "
                    f"(index {idx}) has role={messages[idx].role!r}, not 'tool' "
                    "— group was split"
                )
            i += 1 + k
            continue
        if msg.role == "assistant" and msg.metadata and "tool_call" in msg.metadata:
            assert i + 1 < n, (
                f"Orphaned tool_call at index {i} (no following message at all): {msg}"
            )
            nxt = messages[i + 1]
            assert nxt.role == "tool", (
                f"tool_call at index {i} is not immediately followed by its tool "
                f"result (found role={nxt.role!r} instead) — pair was split"
            )
            i += 2
            continue
        if msg.role == "tool":
            raise AssertionError(
                f"Orphaned tool result at index {i} — not consumed by any "
                f"preceding tool_call/tool_calls group: {msg}"
            )
        i += 1


class TestCutPointNeverSplitsToolPairs:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("seed", range(25))
    async def test_random_histories_never_split_a_tool_pair(self, seed: int) -> None:
        rng = random.Random(seed)
        messages = _random_history(
            rng, length=rng.randint(3, 30), seed_prior_summary=True
        )

        async def mock_llm(prompt: str, dialog_text: str) -> str:
            return "Random-history summary."

        config = CompactionConfig(
            threshold_tokens=rng.choice([5, 20, 50, 200]),
            preserve_recent_pairs=rng.choice([0, 1, 2, 3]),
            dedup_enabled=True,
            compactable_tool_names=frozenset({"read_file", "list_dir"}),
        )
        f = ConversationCompactionFilter(config=config, llm_call=mock_llm)

        result_msgs, _ = await f.filter(messages, "sys")
        _assert_no_orphaned_tool_pairs(result_msgs)
        _assert_no_adjacent_summary_messages(result_msgs)
        _assert_at_most_one_summary_message(result_msgs)
        _assert_no_adjacent_collapse_placeholder_messages(result_msgs)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("seed", range(10))
    async def test_random_histories_survive_llm_failure_fallback(
        self, seed: int
    ) -> None:
        """Same property, but forcing the Ступень C local-fallback path
        (LLM raises a generic error) — the fallback must not corrupt pairs
        either."""
        rng = random.Random(seed + 1000)
        messages = _random_history(
            rng, length=rng.randint(3, 20), seed_prior_summary=True
        )

        async def failing_llm(prompt: str, dialog_text: str) -> str:
            raise ValueError("simulated bad output")

        config = CompactionConfig(
            threshold_tokens=rng.choice([5, 20, 50]),
            preserve_recent_pairs=rng.choice([0, 1, 2]),
        )
        f = ConversationCompactionFilter(config=config, llm_call=failing_llm)

        result_msgs, _ = await f.filter(messages, "sys")
        _assert_no_orphaned_tool_pairs(result_msgs)
        _assert_no_adjacent_summary_messages(result_msgs)
        _assert_at_most_one_summary_message(result_msgs)
        _assert_no_adjacent_collapse_placeholder_messages(result_msgs)


class TestHistoryAppendOnly:
    """Compaction COLLAPSES (returns a new list) — it never mutates the
    caller's original messages list or its Message objects in place."""

    @pytest.mark.asyncio
    async def test_original_list_untouched_by_dedup(self) -> None:
        content = "x" * 250
        original = [
            _msg("assistant", "", metadata={"tool_call": "a"}),
            _msg("tool", content, name="a"),
            _msg("assistant", "", metadata={"tool_call": "b"}),
            _msg("tool", content, name="b"),
            _msg("user", "q"),
        ]
        snapshot = copy.deepcopy(original)
        config = CompactionConfig(
            threshold_tokens=10,
            preserve_recent_pairs=0,
            dedup_enabled=True,
            tier_1_enabled=False,
            tier_2_enabled=False,
            tier_3_enabled=False,
        )
        f = ConversationCompactionFilter(config=config)

        result = await f.filter(original, "sys")

        assert original == snapshot, "dedup mutated the caller's original list in place"
        assert result[0] != original  # sanity: the result IS actually different

    @pytest.mark.asyncio
    async def test_original_list_untouched_by_full_cascade(self) -> None:
        rng = random.Random(42)
        original = _random_history(rng, length=15)
        snapshot = copy.deepcopy(original)

        async def mock_llm(prompt: str, dialog_text: str) -> str:
            return "Summary of the old conversation segment."

        config = CompactionConfig(threshold_tokens=20, preserve_recent_pairs=1)
        f = ConversationCompactionFilter(config=config, llm_call=mock_llm)

        await f.filter(original, "sys")

        assert original == snapshot, (
            "cascade mutated the caller's original list in place"
        )
