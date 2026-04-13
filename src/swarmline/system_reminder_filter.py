"""SystemReminderFilter — conditional context injection via InputFilter.

Injects priority-ordered <system-reminder> blocks into the system prompt,
respecting a configurable token budget. Higher-priority reminders survive
budget pressure; triggers gate which reminders are active per turn.

Implements the InputFilter protocol without modifying ThinRuntime.run().
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from swarmline.runtime.types import Message


@dataclass(frozen=True)
class SystemReminder:
    """A conditional context block injectable into the system prompt.

    Attributes:
        id: Unique identifier for the reminder.
        content: Text content to inject.
        priority: Higher = more important. Survives budget pressure first.
        trigger: Predicate evaluated per turn. None = always active.
        token_estimate: Pre-computed token count. None = auto from content length.
    """

    id: str
    content: str
    priority: int = 0
    trigger: Callable[[list[Message], str], bool] | None = None
    token_estimate: int | None = None


class SystemReminderFilter:
    """Injects <system-reminder> blocks into system_prompt under a token budget.

    Implements InputFilter protocol.
    """

    DEFAULT_BUDGET_TOKENS: int = 500
    CHARS_PER_TOKEN: float = 4.0

    def __init__(
        self,
        reminders: list[SystemReminder],
        budget_tokens: int = DEFAULT_BUDGET_TOKENS,
    ) -> None:
        self._reminders = reminders
        self._budget_tokens = budget_tokens

    def _estimate_tokens(self, reminder: SystemReminder) -> int:
        """Return token count: explicit estimate or auto from content length."""
        if reminder.token_estimate is not None:
            return reminder.token_estimate
        return int(len(reminder.content) / self.CHARS_PER_TOKEN)

    @staticmethod
    def _format_block(reminder: SystemReminder) -> str:
        return f'<system-reminder id="{reminder.id}">\n{reminder.content}\n</system-reminder>'

    async def filter(
        self, messages: list[Message], system_prompt: str
    ) -> tuple[list[Message], str]:
        # 1. Evaluate triggers → collect active reminders
        active: list[SystemReminder] = []
        for r in self._reminders:
            if r.trigger is None or r.trigger(messages, system_prompt):
                active.append(r)

        if not active:
            return messages, system_prompt

        # 2. Sort by priority descending (highest first)
        active.sort(key=lambda r: r.priority, reverse=True)

        # 3. Budget enforcement — keep highest-priority within budget.
        # Guarantee: at least the highest-priority reminder is always included,
        # even if it alone exceeds the budget (prevents silent no-op).
        selected: list[SystemReminder] = []
        used_tokens = 0

        for r in active:
            cost = self._estimate_tokens(r)
            if used_tokens + cost <= self._budget_tokens:
                selected.append(r)
                used_tokens += cost
            elif not selected:
                # 4. If budget too small even for highest-priority → include it anyway
                selected.append(r)
                break

        # 5. Inject as <system-reminder> blocks appended to system_prompt
        blocks = "\n".join(self._format_block(r) for r in selected)
        if system_prompt:
            new_prompt = f"{system_prompt}\n{blocks}"
        else:
            new_prompt = blocks

        # 6. Return messages unchanged
        return messages, new_prompt
