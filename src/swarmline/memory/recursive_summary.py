# Attribution: adapted from aider (Apache-2.0)
# Upstream file: aider/history.py
# Copyright: (c) Paul Gauthier and contributors
# Changes: reimplemented for swarmline; added code-anchor-preserving prompt,
#          bounded depth-3 recursion, context/budget token counting;
#          no verbatim copy of aider source.
"""Recursive history compression — code-aware split-and-summarize.

Design adapted from aider (Apache-2.0) history.py (ChatSummary recursive
split-and-summarize); reimplemented for swarmline with no verbatim copy.

Algorithm:
1. If messages fit within the token budget → return unchanged (no LLM call).
2. Split at ~midpoint: search backward then forward for the nearest assistant-
   message boundary; if none exists, HEAD = all messages (TAIL = []).
   Invariant: messages[split-1].role == 'assistant' OR split == len(messages).
3. Summarize HEAD via one LLM call with a code-aware prompt that instructs
   the model to preserve file paths, stack traces, and symbol names.
4. Combine [summary_message] + TAIL.
5. If still over budget, recurse on the new list — bounded at MAX_DEPTH=3.
   Beyond that, return the best-effort result without further LLM calls.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from swarmline.context.budget import estimate_tokens
from swarmline.memory.types import MemoryMessage

logger = logging.getLogger(__name__)

MAX_DEPTH: int = 3

_CODE_AWARE_SUMMARY_PROMPT: str = """\
Summarise the conversation below concisely (300-600 words).

CRITICAL — you MUST preserve ALL of the following in the summary:
- File paths (e.g. src/foo/bar.py, tests/unit/test_x.py)
- Stack traces and error messages (exact class names, line numbers, exception types)
- Symbol names: class names, function names, variable names, module names

Write in third person. Plain prose only — no bullet lists, no headings.
"""


def _messages_tokens(messages: list[MemoryMessage]) -> int:
    """Estimate total token count for a list of messages via context/budget."""
    return sum(estimate_tokens(m.content) for m in messages)


def _find_assistant_split_point(messages: list[MemoryMessage], midpoint: int) -> int:
    """Return the split index such that messages[:split] is the HEAD.

    Invariant: messages[split - 1].role == 'assistant'  OR  split == len(messages).

    Strategy:
    1. Search backwards from midpoint to 1 — prefer the nearest assistant boundary
       at or before the midpoint (keeps TAIL as large as possible).
    2. If nothing found, search forward from midpoint+1 to len(messages) — accept
       a later assistant boundary (TAIL shrinks but invariant holds).
    3. If no assistant message exists anywhere in the list, return len(messages):
       HEAD = all messages, TAIL = [] — summarise everything and produce a single
       summary; no user/assistant pair is torn.

    Args:
        messages: Conversation messages (oldest first).
        midpoint: Target split index (typically len(messages) // 2).

    Returns:
        Split index i where 1 ≤ i ≤ len(messages).
    """
    # Phase 1: backward from midpoint
    for i in range(midpoint, 0, -1):
        if messages[i - 1].role == "assistant":
            return i
    # Phase 2: forward from midpoint+1
    for i in range(midpoint + 1, len(messages) + 1):
        if messages[i - 1].role == "assistant":
            return i
    # Phase 3: no assistant message anywhere — summarise all, empty tail
    return len(messages)


class RecursiveSummarizer:
    """Recursive history compressor with assistant-boundary split and depth bound.

    Args:
        llm_call: Async callable ``(prompt: str, dialog_text: str) -> str``.
        token_budget: Maximum total token count for the compressed result.
    """

    def __init__(
        self,
        llm_call: Callable[..., Any],
        token_budget: int,
    ) -> None:
        self._llm_call = llm_call
        self._token_budget = token_budget

    async def asummarize(self, messages: list[MemoryMessage]) -> list[MemoryMessage]:
        """Compress *messages* to fit within the token budget.

        Returns the original list unchanged when already within budget.
        Returns a best-effort (possibly still over-budget) list after MAX_DEPTH
        recursion levels without looping unboundedly.
        """
        return await self._compress(messages, depth=0)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _compress(
        self,
        messages: list[MemoryMessage],
        depth: int,
    ) -> list[MemoryMessage]:
        if not messages:
            return messages

        total = _messages_tokens(messages)
        if total <= self._token_budget:
            return messages  # within budget — no LLM call

        if depth >= MAX_DEPTH:
            logger.debug(
                "RecursiveSummarizer: max depth %d reached; returning best-effort result "
                "(%d tokens vs budget %d)",
                MAX_DEPTH,
                total,
                self._token_budget,
            )
            return messages  # bounded recursion — best effort

        # Find assistant-boundary split at ~midpoint
        midpoint = len(messages) // 2
        split = _find_assistant_split_point(messages, midpoint)

        head = messages[:split]
        tail = messages[split:]

        if not head:
            return messages  # safety: cannot split further

        # Build dialog text for HEAD
        dialog_lines: list[str] = []
        for msg in head:
            label = "User" if msg.role == "user" else "Assistant"
            dialog_lines.append(f"{label}: {msg.content}")
        dialog_text = "\n".join(dialog_lines)

        try:
            summary_text = await self._llm_call(_CODE_AWARE_SUMMARY_PROMPT, dialog_text)
        except Exception:
            logger.warning(
                "RecursiveSummarizer: LLM call failed at depth %d; returning unchanged",
                depth,
                exc_info=True,
            )
            return messages  # best-effort on LLM failure

        summary_msg = MemoryMessage(
            role="assistant",
            content=f"[Summary of earlier conversation]\n{summary_text}",
        )

        compressed = [summary_msg, *tail]

        # Recurse if still over budget (bounded by depth check above)
        return await self._compress(compressed, depth=depth + 1)
