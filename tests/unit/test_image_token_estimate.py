"""Unit: an image part counts as ``IMAGE_TOKEN_ESTIMATE`` tokens (taskloom Sprint 7i S1).

Its base64 length says nothing about what a provider bills, so it is neither ignored nor
counted as characters / 4 — in compaction, per-round budgeting and the estimated usage.
"""

from __future__ import annotations

from typing import Any

import pytest

from swarmline.compaction import CompactionConfig, ConversationCompactionFilter
from swarmline.context.budget import (
    IMAGE_TOKEN_ESTIMATE,
    estimate_image_tokens,
    estimate_message_tokens,
    estimate_tokens,
)
from swarmline.domain_types import ImageBlock, Message, TextBlock
from swarmline.runtime.thin.finalization import _estimate_tokens_for_prompt
from swarmline.runtime.thin.round_context import RoundContextRefresher

IMAGE = ImageBlock(data="A" * 40_000, media_type="image/png")


@pytest.mark.parametrize(
    ("blocks", "expected"),
    [
        (None, 0),
        ("not-a-list", 0),
        ([], 0),
        ([TextBlock(text="hello")], 0),
        ([TextBlock(text="hello"), IMAGE], IMAGE_TOKEN_ESTIMATE),
        ([IMAGE, IMAGE], 2 * IMAGE_TOKEN_ESTIMATE),
        ([{"type": "text", "text": "x"}, IMAGE.to_dict()], IMAGE_TOKEN_ESTIMATE),
    ],
)
def test_estimate_image_tokens_counts_image_parts_only(
    blocks: Any, expected: int
) -> None:
    assert estimate_image_tokens(blocks) == expected


def test_estimate_message_tokens_adds_images_to_text() -> None:
    plain = Message(role="user", content="describe this picture")
    with_image = Message(
        role="user",
        content="describe this picture",
        content_blocks=[TextBlock(text="describe this picture"), IMAGE],
    )

    assert estimate_message_tokens(plain) == estimate_tokens(plain.content)
    assert (
        estimate_message_tokens(with_image)
        == estimate_tokens(plain.content) + IMAGE_TOKEN_ESTIMATE
    )


def test_round_budget_counts_image_parts_of_the_lm_projection() -> None:
    refresher = RoundContextRefresher()
    text_only = [{"role": "user", "content": "look"}]
    with_image = [
        {"role": "user", "content": "look", "content_blocks": [IMAGE.to_dict()]}
    ]

    delta = refresher.estimate_budget(with_image, "sys") - refresher.estimate_budget(
        text_only, "sys"
    )

    assert delta == IMAGE_TOKEN_ESTIMATE


def test_estimated_usage_counts_image_parts() -> None:
    text_only = [{"role": "user", "content": "look"}]
    with_image = [
        {"role": "user", "content": "look", "content_blocks": [IMAGE.to_dict()]}
    ]

    delta = _estimate_tokens_for_prompt(
        with_image, "sys"
    ) - _estimate_tokens_for_prompt(text_only, "sys")

    assert delta == IMAGE_TOKEN_ESTIMATE


def test_compaction_total_counts_image_parts() -> None:
    compaction = ConversationCompactionFilter(config=CompactionConfig())
    plain = [Message(role="user", content="look")]
    with_image = [
        Message(
            role="user", content="look", content_blocks=[TextBlock(text="look"), IMAGE]
        )
    ]

    delta = compaction._estimate_total(with_image, "sys") - compaction._estimate_total(
        plain, "sys"
    )

    assert delta == IMAGE_TOKEN_ESTIMATE
