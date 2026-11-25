"""Prompt-caching primitives — Anthropic ``cache_control`` breakpoint placement.

Stage 2 (context-engineering-manus-parity): implements the Hermes ``system_and_3``
recipe — one ``cache_control`` breakpoint on the (static portion of the) system
prompt plus one on each of the last 3 eligible non-system messages (Anthropic's
per-request ceiling is 4 ``cache_control`` breakpoints total).

Pure functions only: no network calls, no SDK types. A caller (e.g.
``runtime/thin/llm_providers.py``'s ``AnthropicAdapter``) decides WHEN to apply
these (native Anthropic path only, opt-in flag) — this module only decides WHERE
the breakpoints go, given a system prompt / message list.
"""

from __future__ import annotations

import copy
from typing import Any, Literal, cast

CacheTTL = Literal["5m", "1h"]

_MAX_MESSAGE_BREAKPOINTS = 3

# Fix-cycle 1 (codex round 1, BLOCKER): a host application (e.g. a system-prompt
# builder that splits a flat prompt into a byte-stable STATIC portion and a
# per-turn DYNAMIC portion) may join the two around a literal boundary marker
# string so the LLM still sees one flat system prompt. Caching the WHOLE flat
# string — dynamic portion included — would invalidate the cache on every turn the
# dynamic content changes, defeating the point of caching the static portion at
# all. This is a plain string-literal convention (no import, no coupling to any
# particular host): when the marker is present in ``system_prompt``, split on it
# and cache ONLY the static (pre-marker) side; when absent, fall back to caching
# the whole prompt as one block (valid default for hosts with no static/dynamic
# split at all).
DEFAULT_BOUNDARY_MARKER = "<!-- TASKLOOM_CACHE_BOUNDARY -->"


def _cache_control_block(ttl: CacheTTL) -> dict[str, str]:
    """Build one ``cache_control`` block for the given TTL.

    Fix-cycle 1 (MAJOR-4): ``"5m"`` (default) omits the ``ttl`` key entirely — that
    IS Anthropic's default ephemeral TTL, so the default payload shape is
    byte-identical to before this option existed. ``"1h"`` adds an explicit ``ttl``
    key (Anthropic's extended-cache option).
    """
    if ttl == "1h":
        return {"type": "ephemeral", "ttl": "1h"}
    return {"type": "ephemeral"}


def build_cached_system(
    system_prompt: str,
    *,
    ttl: CacheTTL = "5m",
    boundary_marker: str = DEFAULT_BOUNDARY_MARKER,
) -> str | list[dict[str, Any]]:
    """Wrap ``system_prompt`` in Anthropic's ``cache_control`` block form.

    - Blank/empty prompt: returned UNCHANGED (as ``str``) — Anthropic rejects an
      empty-text ``cache_control`` block, and there is nothing worth caching.
    - ``boundary_marker`` present in ``system_prompt`` (fix-cycle 1 BLOCKER): split
      into ``[static-block WITH cache_control, dynamic-block WITHOUT]`` — only the
      static (pre-marker) side is cached; the dynamic (post-marker) side is sent as
      a plain uncached text block so a changing dynamic portion never invalidates
      the cached static portion. A blank side (e.g. no dynamic content at all) is
      omitted entirely rather than sent as an empty block. If BOTH sides are blank
      (fix-cycle 3, B-1), the marker itself carried no real content on either
      side — the marker-stripped remainder (``static_part + dynamic_part``, i.e.
      whatever surrounding whitespace existed) is returned as a plain ``str``,
      exactly like the blank-prompt case below. The literal marker is NEVER part
      of ANY returned value, in ANY branch — consistency was fix-cycle 3's whole
      point; a fallback that let the marker leak back into the payload here would
      make a cached block's bytes depend on whether the split was degenerate.
      The boundary is the FIRST occurrence of ``boundary_marker`` (static = strictly
      everything before it, so static can never itself contain the marker); a
      REPEATED marker further into the prompt (fix-cycle 4, B-1 counterexample —
      never produced by a well-behaved static/dynamic builder, but this is a
      universal lib with arbitrary input) is treated as garbage and scrubbed
      outright from the dynamic remainder, not split into further blocks.
    - ``boundary_marker`` absent: the whole prompt is cached as ONE block (original
      behaviour — the correct fallback for callers with no static/dynamic split).
    """
    if not system_prompt or not system_prompt.strip():
        return system_prompt

    if boundary_marker and boundary_marker in system_prompt:
        static_part, _, dynamic_part = system_prompt.partition(boundary_marker)
        # Fix-cycle 4 (B-1 counterexample, codex round 4): partition() only removes
        # the FIRST occurrence of the marker. The boundary is defined as that first
        # occurrence (static = everything before it, so static can never itself
        # contain the marker) — any FURTHER occurrence in the remainder is garbage
        # (never produced by a well-behaved static/dynamic builder) and is scrubbed
        # outright, never split further.
        dynamic_part = dynamic_part.replace(boundary_marker, "")
        blocks: list[dict[str, Any]] = []
        if static_part.strip():
            blocks.append(
                {
                    "type": "text",
                    "text": static_part,
                    "cache_control": _cache_control_block(ttl),
                }
            )
        if dynamic_part.strip():
            blocks.append({"type": "text", "text": dynamic_part})
        if blocks:
            return blocks
        return static_part + dynamic_part

    return [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": _cache_control_block(ttl),
        }
    ]


def _strip_cache_control(block: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``block`` without any ``cache_control`` key."""
    if "cache_control" not in block:
        return block
    return {k: v for k, v in block.items() if k != "cache_control"}


def _as_content_blocks(content: object) -> list[dict[str, Any]] | None:
    """Normalize a message's ``content`` into a list of content blocks.

    Returns ``None`` for content that cannot be a cache_control target: a blank
    string, an empty list, any other (non-str, non-list) shape, OR (fix-cycle 1
    MAJOR-5, fail-open) a list containing a non-dict element — malformed content
    is treated as ineligible rather than raised on, so a caching decoration
    failure can never break the underlying LLM call.

    Any PRE-EXISTING ``cache_control`` key on a block is stripped here (fix-cycle 1
    MAJOR-1) — this function is the single place raw message content is normalized
    before either (a) being marked with a new breakpoint or (b) passed through
    untouched, so stripping here guarantees the FINAL total breakpoint count is
    controlled entirely by ``mark_last_message_breakpoints``, never inflated by
    breakpoints a caller's input happened to already carry.
    """
    if isinstance(content, str):
        if not content.strip():
            return None
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        if not content:
            return None
        blocks: list[dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict):
                return None
            # ty narrows `isinstance(block, dict)` to `dict[Unknown, Unknown]` (key/value
            # types cannot be recovered from a runtime isinstance check); cast to the
            # declared shape, matching the established pattern elsewhere in this codebase
            # (e.g. context/stable_prefix.py's tool-name extraction).
            copied = cast("dict[str, Any]", copy.deepcopy(block))
            blocks.append(_strip_cache_control(copied))
        return blocks
    return None


def _last_block_is_cacheable(blocks: list[dict[str, Any]]) -> bool:
    """Fix-cycle 1 (MAJOR-2): the block that would actually RECEIVE the
    ``cache_control`` key (the last one) must itself be a valid cache target.

    Anthropic rejects ``cache_control`` on an empty/blank TEXT block. Every other
    block type (image, tool_use, tool_result, ...) is a valid cache_control target
    as-is — including a message whose ONLY content is a ``tool_result`` block
    (native tool-calling's normal shape for the message right after a tool call),
    which must be eligible, not skipped.
    """
    last = blocks[-1]
    if last.get("type") == "text":
        text = last.get("text", "")
        return bool(text) and bool(str(text).strip())
    return True


def _is_eligible_message(message: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Return normalized content blocks if ``message`` is breakpoint-eligible, else None."""
    if message.get("role") == "system":
        return None
    blocks = _as_content_blocks(message.get("content"))
    if blocks is None or not _last_block_is_cacheable(blocks):
        return None
    return blocks


def mark_last_message_breakpoints(
    messages: list[dict[str, Any]],
    *,
    ttl: CacheTTL = "5m",
) -> list[dict[str, Any]]:
    """Mark the last up-to-3 ELIGIBLE non-system messages with a ``cache_control``
    breakpoint on their final content block (Hermes ``system_and_3``, message half —
    pair with ``build_cached_system`` for the system-prompt half).

    Eligibility: ``role != "system"``, normalized content is non-empty, AND the
    block that would receive the breakpoint (the last one) is itself a valid
    cache_control target — an empty/blank trailing TEXT block is never chosen
    (fix-cycle 1 MAJOR-2), even if the message would otherwise be one of the last 3.

    ANY pre-existing ``cache_control`` key already present on ANY message's content
    blocks — selected for a new breakpoint or not — is stripped (fix-cycle 1
    MAJOR-1), so the total breakpoint count in the returned messages is controlled
    entirely by this function (≤3), never inflated by stray input state.

    Returns a NEW list; neither ``messages`` nor its dicts/content lists (including
    nested structures, e.g. an image block's ``source`` dict) are ever mutated —
    every block is deep-copied (fix-cycle 1 MINOR-1). Pure function of ``messages``
    — calling this again on the SAME input list always reproduces byte-identical
    output (retry-safety: a retried LLM call re-applies this to the original
    messages, not to a previous call's output).
    """
    eligible_indices = [
        idx
        for idx, message in enumerate(messages)
        if _is_eligible_message(message) is not None
    ]
    breakpoint_indices = set(eligible_indices[-_MAX_MESSAGE_BREAKPOINTS:])

    result: list[dict[str, Any]] = []
    for idx, message in enumerate(messages):
        if idx in breakpoint_indices:
            blocks = _as_content_blocks(message.get("content"))
            assert blocks is not None  # eligibility above already required this
            blocks[-1] = {**blocks[-1], "cache_control": _cache_control_block(ttl)}
            result.append({**message, "content": blocks})
            continue

        # Not selected for a NEW breakpoint: only reshape when content is ALREADY
        # list-form — every other message (plain string, or anything else) passes
        # through with its original content type/shape untouched (minimal
        # footprint; strings are immutable, so no aliasing risk there).
        #
        # Fix-cycle 3 (B-8): ALWAYS deep-copy list-form content here, regardless of
        # whether it happens to carry a pre-existing cache_control to strip. The
        # single unified deep-copy contract applies to every message in the output
        # (selected or not) — a shallow ``dict(message)`` would still alias nested
        # structures (e.g. an image block's ``source`` dict) with the caller's
        # original message, corrupting a later retry's source if the caller ever
        # mutates the returned block in place.
        content = message.get("content")
        if isinstance(content, list):
            deep_copied = [
                _strip_cache_control(cast("dict[str, Any]", copy.deepcopy(block)))
                if isinstance(block, dict)
                else copy.deepcopy(block)
                for block in content
            ]
            result.append({**message, "content": deep_copied})
        else:
            result.append(dict(message))
    return result


__all__ = [
    "CacheTTL",
    "DEFAULT_BOUNDARY_MARKER",
    "build_cached_system",
    "mark_last_message_breakpoints",
]
