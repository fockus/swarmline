"""SummaryGenerator - generate a rolling summary from message history.

MVP: template-based (no LLM call).
Can later be replaced with an LLM-based implementation via the same Protocol.
"""

from __future__ import annotations

from swarmline.memory.types import MemoryMessage


class TemplateSummaryGenerator:
    """Template-based summary generator (KISS for the MVP).

    Takes the last N messages, truncates long ones, and builds
    a short textual summary in the format:
    - [user]: text
    - [assistant]: text
    """

    def __init__(
        self,
        max_messages: int = 20,
        max_message_chars: int = 200,
    ) -> None:
        self._max_messages = max_messages
        self._max_message_chars = max_message_chars

    def summarize(self, messages: list[MemoryMessage]) -> str:
        """Generate a summary from a list of messages.

        Args:
            messages: List of messages (oldest to newest).

        Returns:
            Summary text or an empty string if there are no messages.
        """
        if not messages:
            return ""

        # Take only the latest N messages
        recent = messages[-self._max_messages :]

        lines: list[str] = []
        for msg in recent:
            content = msg.content
            if len(content) > self._max_message_chars:
                content = content[: self._max_message_chars] + "..."
            role_label = "user" if msg.role == "user" else "assistant"
            lines.append(f"- [{role_label}]: {content}")

        return "\n".join(lines)
