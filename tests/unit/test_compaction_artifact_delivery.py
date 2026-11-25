"""F-1: compaction artifacts must actually reach the provider payload.

Tier 1 collapse and Tier 2 summary messages are built with ``role="system"``;
every provider adapter drops non-user/assistant chat messages, so before the fix
the summary and collapsed placeholders silently never reached the model and
compaction degraded to plain truncation. The fix renders them at the
``_message_to_lm`` boundary as a user-role data envelope; the provider filters
stay untouched (an arbitrary system message is still dropped).
"""

from __future__ import annotations

from _compaction_fakes import long_history, scripted_summarizer, structured_summary

from swarmline.compaction import CompactionConfig, ConversationCompactionFilter
from swarmline.domain_types import Message
from swarmline.runtime.thin.helpers import _messages_to_lm
from swarmline.runtime.thin.llm_providers import (
    OpenAICompatAdapter,
    _filter_chat_messages,
)

_SUMMARY_MARKER = "SUMMARY_MARKER_F1"


async def _compact_with_summary() -> list[Message]:
    compaction = ConversationCompactionFilter(
        config=CompactionConfig(
            threshold_tokens=1_500, preserve_recent_pairs=1, tier_3_enabled=False
        ),
        llm_call=scripted_summarizer(structured_summary(_SUMMARY_MARKER)),
    )
    compacted, _ = await compaction.filter(long_history(), "system prompt")
    return compacted


def _payload_text(payload: list[dict]) -> str:
    return "\n".join(str(m["content"]) for m in payload)


async def test_compaction_summary_reaches_provider_payload() -> None:
    compacted = await _compact_with_summary()

    anthropic_payload = _filter_chat_messages(_messages_to_lm(compacted))
    openai_payload = OpenAICompatAdapter._prepare(
        _messages_to_lm(compacted), "system prompt"
    )

    assert _SUMMARY_MARKER in _payload_text(anthropic_payload)
    assert _SUMMARY_MARKER in _payload_text(openai_payload[1:])


async def test_collapsed_tool_placeholder_reaches_provider_payload() -> None:
    messages: list[Message] = [Message(role="user", content="find the bug")]
    for i in range(4):
        messages.append(
            Message(role="assistant", content="", metadata={"tool_call": "grep_code"})
        )
        messages.append(
            Message(role="tool", content=f"match {i} " + "x" * 800, name="grep_code")
        )
    messages.append(Message(role="user", content="and now?"))
    compaction = ConversationCompactionFilter(
        config=CompactionConfig(
            threshold_tokens=400,
            preserve_recent_pairs=1,
            tier_2_enabled=False,
            tier_3_enabled=False,
        )
    )

    compacted, _ = await compaction.filter(messages, "sys")
    payload = _filter_chat_messages(_messages_to_lm(compacted))

    assert "[Collapsed tool call: grep_code]" in _payload_text(payload)


async def test_summary_rendered_as_data_envelope_with_end_marker() -> None:
    compacted = await _compact_with_summary()

    payload = _filter_chat_messages(_messages_to_lm(compacted))
    summary_turns = [m for m in payload if _SUMMARY_MARKER in m["content"]]

    assert len(summary_turns) == 1
    turn = summary_turns[0]
    assert turn["role"] == "user"
    assert '<data source="compaction-summary">' in turn["content"]
    assert turn["content"].rstrip().endswith("</data>")
    assert "not instructions" in turn["content"]


async def test_summary_note_says_tools_remain_available() -> None:
    compacted = await _compact_with_summary()

    payload = _filter_chat_messages(_messages_to_lm(compacted))
    summary_turn = next(m for m in payload if _SUMMARY_MARKER in m["content"])

    assert "tools remain fully available" in summary_turn["content"]
    assert "do not repeat actions listed as completed" in summary_turn["content"]
    assert (
        "answer the latest message below, not this summary" in summary_turn["content"]
    )


def test_non_compaction_system_message_still_dropped() -> None:
    messages = [
        Message(role="system", content="ARBITRARY_SYSTEM_NOTE"),
        Message(role="user", content="hi"),
    ]

    payload = _filter_chat_messages(_messages_to_lm(messages))

    assert payload == [{"role": "user", "content": "hi"}]


def test_collapsed_artifact_never_merged_with_protected_system_message() -> None:
    collapsed = Message(
        role="system",
        content="[Collapsed tool call: grep] hit",
        metadata={"compaction_artifact": "collapsed"},
    )
    protected = Message(
        role="system", content="PROTECTED RULE", metadata={"non_compactable": True}
    )
    plain = Message(role="system", content="PLAIN NOTE")

    merged = ConversationCompactionFilter._merge_adjacent_system_messages(
        [collapsed, protected, plain, Message(role="user", content="hi")]
    )
    payload = _payload_text(_filter_chat_messages(_messages_to_lm(merged)))

    assert merged[0] == collapsed
    assert (
        merged[1].content == "PROTECTED RULE\nPLAIN NOTE"
    )  # non-artifact system messages still merge
    assert "[Collapsed tool call: grep] hit" in payload
    assert (
        "PROTECTED RULE" not in payload
    )  # protected system text is never re-rendered as data
