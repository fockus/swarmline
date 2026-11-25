"""Изображение текущего запроса переживает текстовую компакцию истории."""

from __future__ import annotations

import pytest

from _compaction_fakes import long_history, scripted_summarizer, structured_summary

from swarmline.compaction import CompactionConfig, ConversationCompactionFilter
from swarmline.domain_types import ImageBlock, Message, TextBlock


@pytest.mark.parametrize("summary", [structured_summary(), "invalid summary"])
async def test_current_image_request_after_tool_rounds_survives_compaction(
    summary: str,
) -> None:
    request = Message(
        role="user",
        content="Inspect this diagram",
        content_blocks=[
            TextBlock(text="Inspect this diagram"),
            ImageBlock(data="AA==", media_type="image/png"),
        ],
    )
    messages = [request]
    for i in range(8):
        messages.extend(
            [
                Message(
                    role="assistant",
                    content="step",
                    tool_calls=[{"id": str(i), "name": "probe", "args": {}}],
                ),
                Message(
                    role="tool",
                    content=(f"distinct report {i} " * 400),
                    name="probe",
                ),
            ]
        )
    compaction = ConversationCompactionFilter(
        config=CompactionConfig(
            threshold_tokens=3_000,
            tier_1_enabled=False,
            preserve_recent_pairs=1,
        ),
        llm_call=scripted_summarizer(summary),
    )

    result, _ = await compaction.filter(messages, "")

    assert any(message is request for message in result)
    assert any(
        (m.metadata or {}).get("compaction_artifact") == "summary" for m in result
    )
    assert len(result) < len(messages)
    for index, message in enumerate(result):
        if message.role == "tool":
            assert index > 0 and result[index - 1].tool_calls


async def test_old_image_request_with_newer_human_turn_can_be_compacted() -> None:
    old_request = Message(
        role="user",
        content="Inspect this old diagram",
        content_blocks=[ImageBlock(data="AA==", media_type="image/png")],
    )
    messages = [old_request, *long_history()]
    compaction = ConversationCompactionFilter(
        config=CompactionConfig(
            threshold_tokens=3_000,
            tier_1_enabled=False,
            preserve_recent_pairs=1,
        ),
        llm_call=scripted_summarizer(structured_summary()),
    )

    result, _ = await compaction.filter(messages, "")

    assert all(message is not old_request for message in result)
    assert len(result) < len(messages)
