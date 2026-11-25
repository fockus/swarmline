"""Human turns of a compaction region and the verbatim-request section.

Which messages are real human requests (recitations and ``<system-reminder>``
meta turns are not), and how the latest one is rendered verbatim — by code,
never by the LLM — as the first section of a compaction summary. The section
is capped at a bounded share of the compaction budget (head + tail kept), so
one huge paste can never keep Tier 3 over budget.
"""

from __future__ import annotations

from collections.abc import Sequence

from swarmline.domain_types import Message

VERBATIM_HEADER = "User Request (verbatim):"
VERBATIM_BUDGET_SHARE = 0.25
MIN_VERBATIM_CHARS = 2_000
_META_TURN_PREFIXES = ("<system-reminder>", "<plan-recitation>")


def is_human_request(message: Message) -> bool:
    if message.role != "user" or (message.metadata or {}).get("recitation"):
        return False
    return not message.content.lstrip().startswith(_META_TURN_PREFIXES)


def latest_human_request_index(messages: Sequence[Message]) -> int | None:
    """Index of the last real human turn — recitations and reminders excluded."""
    return next(
        (i for i in range(len(messages) - 1, -1, -1) if is_human_request(messages[i])),
        None,
    )


def latest_human_request(messages: Sequence[Message]) -> Message | None:
    index = latest_human_request_index(messages)
    return None if index is None else messages[index]


def verbatim_budget_chars(threshold_tokens: int) -> int:
    """Char cap of the verbatim request (~4 chars per token)."""
    return max(MIN_VERBATIM_CHARS, int(threshold_tokens * 4 * VERBATIM_BUDGET_SHARE))


def render_verbatim_request_section(
    text: str | None, max_chars: int | None = None
) -> str:
    """First summary section, filled by code: the request exactly as typed,
    or its head and tail around a ``[truncated N chars]`` marker when over
    ``max_chars``."""
    if text is None:
        return f"{VERBATIM_HEADER} none"
    if max_chars is not None and len(text) > max_chars:
        half = max_chars // 2
        cut = len(text) - 2 * half
        text = f"{text[:half]}\n[truncated {cut} chars]\n{text[len(text) - half :]}"
    return f"{VERBATIM_HEADER}\n{text}"


__all__ = [
    "MIN_VERBATIM_CHARS",
    "VERBATIM_BUDGET_SHARE",
    "VERBATIM_HEADER",
    "is_human_request",
    "latest_human_request",
    "latest_human_request_index",
    "render_verbatim_request_section",
    "verbatim_budget_chars",
]
