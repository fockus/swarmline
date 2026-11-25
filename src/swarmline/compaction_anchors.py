"""Deterministic appendices to a compaction summary — no LLM involved.

A summarizer paraphrases; exact identifiers (URLs, paths, commit SHAs, ids,
error lines) and the user's own words are exactly what a paraphrase loses. So
these sections are extracted by code from the compacted region and appended
after the LLM part: every human turn verbatim (budgeted), a regex anchor
index, and — only when the host configures one — a context-recovery hint.
Output is byte-deterministic for the same input (prompt-cache friendly).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence

USER_MESSAGES_HEADER = "## User Messages (verbatim, newest first)"
ANCHOR_INDEX_HEADER = "## Anchor Index (mechanically extracted, exact)"
RECOVERY_HEADER = "## Context Recovery"
USER_MESSAGES_BUDGET_CHARS = 8_000
USER_MESSAGE_MAX_CHARS = 2_000
ANCHOR_BUDGET_CHARS = 4_000
_ERROR_LINE_MAX_CHARS = 300

# Extraction order matters: each matched span is blanked out before the next
# pattern runs, so a UUID is never re-read as two SHAs and a URL's path part
# is never re-read as a file path.
_URL = re.compile(r"https?://[^\s<>\"'`)\]]+")
_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_PREFIXED_ID = re.compile(r"\b(?:run|task|call|toolu|msg|req)_[0-9A-Za-z-]{4,}\b")
_SHA = re.compile(r"\b(?=[0-9a-f]*[0-9])(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b")
_PATH = re.compile(
    r"(?<![\w/.:~-])(?:(?:~|\.{1,2})?/(?:[\w.-]+/)*[\w.-]*[A-Za-z][\w.-]*|(?:[\w.-]+/)+[\w-]+\.[A-Za-z0-9]{1,8})(?![\w/])"
)
_ERROR_LINE = re.compile(r"Error:|Traceback|exit code \d+")


def _truncated(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]} [truncated {len(text) - limit} chars]"


def render_user_messages_section(
    messages_newest_first: Sequence[str], omitted_earlier: int = 0
) -> str:
    """Human turns verbatim, newest first: 2 000 chars each, 8 000 in total.

    A message cut at its own cap carries ``[truncated N chars]``; messages
    that no longer fit the total budget are omitted and counted in one final
    ``[truncated N chars]`` marker; human turns dropped earlier (past the
    carry cap) are counted in ``[N earlier user messages omitted]``. Empty
    input renders no section at all.
    """
    if not messages_newest_first and not omitted_earlier:
        return ""
    blocks: list[str] = []
    used = 0
    omitted = 0
    for index, text in enumerate(messages_newest_first, start=1):
        remaining = USER_MESSAGES_BUDGET_CHARS - used
        if remaining <= 0:
            omitted += len(text)
            continue
        limit = min(USER_MESSAGE_MAX_CHARS, remaining)
        blocks.append(f"[{index}]\n{_truncated(text, limit)}")
        used += min(len(text), limit)
    if omitted:
        blocks.append(f"[truncated {omitted} chars]")
    if omitted_earlier:
        blocks.append(f"[{omitted_earlier} earlier user messages omitted]")
    return "\n".join([USER_MESSAGES_HEADER, *blocks])


def extract_anchors(texts: Sequence[str]) -> list[tuple[str, int]]:
    """Exact anchors with their frequency, most frequent first, then by bytes."""
    counts: Counter[str] = Counter()
    for text in texts:
        for line in text.splitlines():
            if _ERROR_LINE.search(line):
                counts[line.strip()[:_ERROR_LINE_MAX_CHARS]] += 1
        remaining = text
        for pattern in (_URL, _UUID, _PREFIXED_ID, _SHA, _PATH):
            found = pattern.findall(remaining)
            counts.update(found)
            remaining = pattern.sub(" ", remaining)
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def render_anchor_index(texts: Sequence[str]) -> str:
    """``- <anchor> (xN)`` lines within ``ANCHOR_BUDGET_CHARS`` (header included)."""
    lines = [ANCHOR_INDEX_HEADER]
    size = len(ANCHOR_INDEX_HEADER)
    for anchor, count in extract_anchors(texts):
        line = f"- {anchor} (x{count})"
        if size + 1 + len(line) > ANCHOR_BUDGET_CHARS:
            break
        lines.append(line)
        size += 1 + len(line)
    return "\n".join(lines) if len(lines) > 1 else ""


def render_recovery_section(hint: str | None) -> str:
    """Rendered only when the host has a recovery tool to point at."""
    return f"{RECOVERY_HEADER}\n{hint}" if hint else ""


def render_appendix(
    user_messages_newest_first: Sequence[str],
    anchor_texts: Sequence[str],
    recovery_hint: str | None,
    omitted_earlier: int = 0,
) -> str:
    """All non-empty deterministic sections, each preceded by a blank line."""
    sections = (
        render_user_messages_section(user_messages_newest_first, omitted_earlier),
        render_anchor_index(anchor_texts),
        render_recovery_section(recovery_hint),
    )
    return "".join(f"\n\n{section}" for section in sections if section)


__all__ = [
    "ANCHOR_BUDGET_CHARS",
    "USER_MESSAGES_BUDGET_CHARS",
    "extract_anchors",
    "render_anchor_index",
    "render_appendix",
    "render_recovery_section",
    "render_user_messages_section",
]
