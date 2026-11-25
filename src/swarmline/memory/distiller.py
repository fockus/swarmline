"""Conversation distiller — compress long message history into summary + recent tail.

ConversationDistiller keeps the last K messages verbatim and produces a
structured summary of the older portion.  Compression is purely deterministic
by default (template-based, no LLM call).  An optional ``summarizer`` callable
can be injected for richer summaries.

All types are stdlib-only.  Zero product coupling.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from swarmline.memory.types import MemoryMessage


@dataclass(frozen=True)
class DistillationResult:
    """Output of a :class:`ConversationDistiller` run.

    Args:
        recent_messages:    The last ``keep_last`` messages verbatim, in
                            chronological order (oldest first).
        summary:            Structured summary of the older portion.
                            Empty string when the conversation was not long
                            enough to trigger compression.
        total_input:        Total number of messages passed to ``distill()``.
        messages_summarized: Number of messages folded into ``summary``.
    """

    recent_messages: tuple[MemoryMessage, ...]
    summary: str
    total_input: int
    messages_summarized: int


def _default_summarizer(messages: list[MemoryMessage]) -> str:
    """Template-based deterministic summarizer (no LLM, no external deps).

    Produces a compact bullet list of role + truncated content for each message.
    Suitable for tests and contexts where an LLM is unavailable.
    """
    if not messages:
        return ""
    max_chars = 120
    lines: list[str] = ["[Conversation summary]"]
    for msg in messages:
        content = msg.content
        if len(content) > max_chars:
            content = content[:max_chars] + "..."
        lines.append(f"- [{msg.role}]: {content}")
    return "\n".join(lines)


class ConversationDistiller:
    """Compress a message list into a structured summary + a recent verbatim tail.

    Strategy
    --------
    1. If ``len(messages) < min_messages``, return all messages unchanged
       (``summary=""``).
    2. Otherwise split: ``tail = messages[-keep_last:]`` and
       ``older = messages[:-keep_last]``.
    3. Pass ``older`` to the summarizer (default: template-based, injected for
       richer LLM-based compression).
    4. Return a frozen :class:`DistillationResult`.

    Args:
        min_messages: Minimum conversation length before compression kicks in.
                      Conversations shorter than this are returned verbatim.
        keep_last:    Number of most-recent messages to preserve verbatim.
        summarizer:   Optional ``Callable[[list[MemoryMessage]], str]``.
                      When ``None``, the built-in template summarizer is used.
    """

    def __init__(
        self,
        min_messages: int = 10,
        keep_last: int = 5,
        summarizer: Callable[[list[MemoryMessage]], str] | None = None,
    ) -> None:
        if min_messages < 1:
            raise ValueError("min_messages must be >= 1")
        if keep_last < 0:
            raise ValueError("keep_last must be >= 0")
        self._min_messages = min_messages
        self._keep_last = keep_last
        self._summarizer: Callable[[list[MemoryMessage]], str] = (
            summarizer if summarizer is not None else _default_summarizer
        )

    def distill(self, messages: list[MemoryMessage]) -> DistillationResult:
        """Compress *messages* and return a :class:`DistillationResult`.

        The method is synchronous and deterministic (given a deterministic
        summarizer).  No I/O, no LLM calls are made by default.
        """
        total = len(messages)

        # Below threshold — return unchanged
        if total < self._min_messages:
            return DistillationResult(
                recent_messages=tuple(messages),
                summary="",
                total_input=total,
                messages_summarized=0,
            )

        # Split into older (to summarize) and recent tail (to keep verbatim)
        tail = messages[-self._keep_last :] if self._keep_last > 0 else []
        older = messages[: total - self._keep_last] if self._keep_last > 0 else messages

        summary = self._summarizer(older)

        return DistillationResult(
            recent_messages=tuple(tail),
            summary=summary,
            total_input=total,
            messages_summarized=len(older),
        )
