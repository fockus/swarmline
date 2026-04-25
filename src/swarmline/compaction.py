"""3-tier conversation compaction via InputFilter protocol.

Tier 1: Collapse old tool call/result pairs into compact summaries.
Tier 2: LLM summarization of oldest conversation segments.
Tier 3: Emergency truncation (drop oldest messages until under budget).

Usage::

    from swarmline.compaction import CompactionConfig, ConversationCompactionFilter

    config = CompactionConfig(threshold_tokens=80_000, preserve_recent_pairs=3)
    compaction = ConversationCompactionFilter(config=config)
    messages, system_prompt = await compaction.filter(messages, system_prompt)
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from swarmline.context.budget import estimate_tokens
from swarmline.domain_types import Message

logger = logging.getLogger(__name__)

# Max chars of tool result to include in collapsed summary
_SNIPPET_MAX_CHARS = 100

_SUMMARIZE_PROMPT = """\
Summarize this conversation segment concisely (max 500 tokens).
Preserve: key decisions, tool call results, project instructions, task state.
Format: continuous text, third person.
"""


@dataclass(frozen=True)
class CompactionConfig:
    """Configuration for conversation compaction pipeline."""

    enabled: bool = True
    threshold_tokens: int = 80_000
    preserve_recent_pairs: int = 3
    tier_1_enabled: bool = True
    tier_2_enabled: bool = True
    tier_3_enabled: bool = True


class ConversationCompactionFilter:
    """3-tier conversation compaction implementing the InputFilter protocol.

    Tier 1 — collapse old tool call/result pairs into single summary messages.
    Tier 2 — LLM-based summarization of oldest conversation segment (Task 2).
    Tier 3 — emergency truncation: drop oldest messages (Task 2).
    """

    def __init__(
        self,
        config: CompactionConfig | None = None,
        llm_call: Callable[[str, str], Awaitable[str]] | None = None,
    ) -> None:
        self._config = config or CompactionConfig()
        self._llm_call = llm_call

    async def filter(
        self, messages: list[Message], system_prompt: str
    ) -> tuple[list[Message], str]:
        """Apply compaction tiers until messages fit within token budget."""
        if not self._config.enabled or not messages:
            return messages, system_prompt

        total = self._estimate_total(messages, system_prompt)
        if total <= self._config.threshold_tokens:
            return messages, system_prompt

        # Tier 1: collapse old tool call/result pairs
        if self._config.tier_1_enabled:
            messages = self._collapse_tool_results(messages)
            total = self._estimate_total(messages, system_prompt)
            if total <= self._config.threshold_tokens:
                return messages, system_prompt

        # Tier 2: LLM summarization of oldest messages
        if self._config.tier_2_enabled and self._llm_call is not None:
            try:
                messages = await self._summarize_oldest(messages)
                total = self._estimate_total(messages, system_prompt)
                if total <= self._config.threshold_tokens:
                    return messages, system_prompt
            except Exception:
                logger.warning(
                    "Tier 2 LLM summarization failed, falling through to Tier 3",
                    exc_info=True,
                )

        # Tier 3: emergency truncation — drop oldest until under budget
        if self._config.tier_3_enabled:
            messages = self._emergency_truncate(messages, system_prompt)

        return messages, system_prompt

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _estimate_total(self, messages: list[Message], system_prompt: str) -> int:
        """Estimate total tokens for system prompt + all messages."""
        total = estimate_tokens(system_prompt)
        for m in messages:
            total += estimate_tokens(m.content)
        return total

    def _find_tool_pairs(self, messages: list[Message]) -> list[tuple[int, int]]:
        """Find consecutive (assistant tool-call, tool result) index pairs."""
        pairs: list[tuple[int, int]] = []
        i = 0
        while i < len(messages) - 1:
            a_msg = messages[i]
            t_msg = messages[i + 1]
            if (
                a_msg.role == "assistant"
                and a_msg.metadata
                and "tool_call" in a_msg.metadata
                and t_msg.role == "tool"
            ):
                pairs.append((i, i + 1))
                i += 2
            else:
                i += 1
        return pairs

    async def _summarize_oldest(self, messages: list[Message]) -> list[Message]:
        """Tier 2: Summarize oldest messages via LLM call.

        Replaces oldest messages with a single summary system message.
        Preserves the last ``preserve_recent_pairs * 2 + 1`` messages
        (recent tool pairs + at least 1 trailing message).
        Messages with ``metadata.non_compactable=True`` skip summarization
        and are preserved in their original position.
        Raises on LLM failure (caller catches).
        """
        # Preserve at least last message, plus recent tool pairs worth of messages
        preserve_count = max(1, self._config.preserve_recent_pairs * 2 + 1)
        if len(messages) <= preserve_count:
            return messages

        region = messages[:-preserve_count]
        preserved = messages[-preserve_count:]

        # Separate non-compactable messages from the summarization region
        compactable: list[Message] = []
        non_compactable: list[Message] = []
        for msg in region:
            if msg.metadata and msg.metadata.get("non_compactable"):
                non_compactable.append(msg)
            else:
                compactable.append(msg)

        if not compactable:
            return messages

        dialog_lines: list[str] = []
        for msg in compactable:
            dialog_lines.append(f"{msg.role}: {msg.content}")
        dialog_text = "\n".join(dialog_lines)

        summary = await self._llm_call(_SUMMARIZE_PROMPT, dialog_text)  # ty: ignore[call-non-callable]  # Optional Callable gated by caller config
        summary_msg = Message(
            role="system",
            content=f"[Conversation summary]: {summary}",
        )
        return [summary_msg, *non_compactable, *preserved]

    def _emergency_truncate(
        self, messages: list[Message], system_prompt: str
    ) -> list[Message]:
        """Tier 3: Drop oldest messages until under budget.

        Always preserves the last message. Messages with
        ``metadata.non_compactable=True`` are never dropped.
        System prompt tokens are counted against the budget but
        never truncated.  O(n) performance.
        """
        budget = self._config.threshold_tokens - estimate_tokens(system_prompt)
        if budget <= 0:
            non_compactable = [
                m
                for m in messages[:-1]
                if m.metadata and m.metadata.get("non_compactable")
            ]
            return [*non_compactable, messages[-1]]

        total = sum(estimate_tokens(m.content) for m in messages)
        dropped: set[int] = set()
        for i in range(len(messages) - 1):
            if total <= budget:
                break
            msg = messages[i]
            if msg.metadata and msg.metadata.get("non_compactable"):
                continue
            total -= estimate_tokens(msg.content)
            dropped.add(i)

        return [m for i, m in enumerate(messages) if i not in dropped]

    def _collapse_tool_results(self, messages: list[Message]) -> list[Message]:
        """Collapse old tool call/result pairs into compact summary messages.

        Preserves the most recent ``preserve_recent_pairs`` pairs intact.
        Each collapsed pair becomes a single system message with tool name
        and a snippet of the result.
        """
        pairs = self._find_tool_pairs(messages)
        if not pairs:
            return messages

        preserve = self._config.preserve_recent_pairs
        if preserve >= len(pairs):
            return messages

        collapse_set = {
            idx for a, t in pairs[: len(pairs) - preserve] for idx in (a, t)
        }

        result: list[Message] = []
        i = 0
        while i < len(messages):
            if i in collapse_set and messages[i].role == "assistant":
                a_msg = messages[i]
                t_msg = messages[i + 1]
                tool_name = (a_msg.metadata or {}).get("tool_call", "unknown")
                snippet = t_msg.content[:_SNIPPET_MAX_CHARS]
                result.append(
                    Message(
                        role="system",
                        content=f"[Collapsed tool call: {tool_name}] {snippet}",
                    )
                )
                i += 2
            elif i in collapse_set:
                # Tool result index — already handled via the assistant branch
                i += 1
            else:
                result.append(messages[i])
                i += 1

        return result
