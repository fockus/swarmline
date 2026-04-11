"""Pre-LLM Input Filters — applied to messages and system_prompt before each turn.

Provides:
- InputFilter: runtime-checkable protocol for all filters
- MaxTokensFilter: truncates oldest messages to fit within token budget
- SystemPromptInjector: appends or prepends extra text to system prompt
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from swarmline.runtime.types import Message


@runtime_checkable
class InputFilter(Protocol):
    """Filter applied to messages/system_prompt before each LLM call."""

    async def filter(
        self, messages: list[Message], system_prompt: str
    ) -> tuple[list[Message], str]:
        """Return (filtered_messages, filtered_system_prompt)."""
        ...


class MaxTokensFilter:
    """Truncates oldest messages to fit within max_tokens estimate.

    System prompt tokens are counted but never truncated.
    The last message is always preserved (even if it exceeds budget alone).
    """

    def __init__(
        self, max_tokens: int = 100_000, chars_per_token: float = 4.0
    ) -> None:
        self._max_tokens = max_tokens
        self._chars_per_token = chars_per_token

    def _estimate_tokens(self, text: str) -> int:
        return int(len(text) / self._chars_per_token)

    async def filter(
        self, messages: list[Message], system_prompt: str
    ) -> tuple[list[Message], str]:
        if not messages:
            return messages, system_prompt

        budget = self._max_tokens - self._estimate_tokens(system_prompt)
        if budget <= 0:
            # System prompt alone exceeds budget; keep only last message
            return [messages[-1]], system_prompt

        # Calculate total message tokens
        msg_tokens = [self._estimate_tokens(m.content) for m in messages]
        total = sum(msg_tokens)

        if total <= budget:
            return messages, system_prompt

        # Trim from the front (oldest), always keep at least the last message
        trimmed = list(messages)
        trimmed_tokens = list(msg_tokens)

        while len(trimmed) > 1 and sum(trimmed_tokens) > budget:
            trimmed.pop(0)
            trimmed_tokens.pop(0)

        return trimmed, system_prompt


class SystemPromptInjector:
    """Appends or prepends extra text to the system prompt.

    Args:
        extra_text: Text to inject.
        position: "append" (default) or "prepend".
    """

    def __init__(self, extra_text: str, position: str = "append") -> None:
        self._extra_text = extra_text
        self._position = position

    async def filter(
        self, messages: list[Message], system_prompt: str
    ) -> tuple[list[Message], str]:
        if not system_prompt:
            return messages, self._extra_text

        if self._position == "prepend":
            return messages, f"{self._extra_text}\n{system_prompt}"

        return messages, f"{system_prompt}\n{self._extra_text}"
