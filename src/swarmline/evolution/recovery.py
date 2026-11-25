"""RecoveryCascade — 4-strategy escalation for stuck agents.

Strategies applied in order: REPHRASE → SIMPLIFY → ALTERNATIVE → ESCALATE.
ESCALATE signals should_continue=False (agent gives up and asks user).

Pure domain logic — no external dependencies except StuckSignal.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from swarmline.evolution.stuck_detector import StuckSignal


class RecoveryStrategy(enum.Enum):
    """Recovery strategies in escalation order."""

    REPHRASE = "rephrase"
    SIMPLIFY = "simplify"
    ALTERNATIVE = "alternative"
    ESCALATE = "escalate"


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    """Result of a recovery attempt."""

    strategy_used: RecoveryStrategy
    recovery_prompt: str
    should_continue: bool


_PROMPT_TEMPLATES: dict[RecoveryStrategy, str] = {
    RecoveryStrategy.REPHRASE: (
        "Your approach is repeating (tool '{tool}' called {count} times). "
        "Rephrase your goal differently and try a new angle.\n"
        "Original goal: {goal}"
    ),
    RecoveryStrategy.SIMPLIFY: (
        "You are stuck on '{tool}' (called {count} times). "
        "Break the problem into smaller steps. Solve the simplest sub-problem first.\n"
        "Original goal: {goal}"
    ),
    RecoveryStrategy.ALTERNATIVE: (
        "Your current tool/approach ('{tool}') isn't working after {count} attempts. "
        "List 3 alternative approaches and pick the most different one.\n"
        "Original goal: {goal}"
    ),
    RecoveryStrategy.ESCALATE: (
        "You are stuck after multiple recovery attempts on '{tool}' ({count} repeats). "
        "Summarize what you tried, what failed, and ask the user for guidance.\n"
        "Original goal: {goal}"
    ),
}


@runtime_checkable
class RecoveryCascadeLike(Protocol):
    """Port: recovery cascade contract."""

    def next_strategy(self, attempt: int) -> RecoveryStrategy: ...

    def build_recovery_prompt(
        self, strategy: RecoveryStrategy, stuck_signal: StuckSignal, original_goal: str
    ) -> str: ...

    def get_recovery(
        self, attempt: int, stuck_signal: StuckSignal, original_goal: str
    ) -> RecoveryResult: ...


class RecoveryCascade:
    """Progressive recovery: each attempt escalates to a stronger strategy."""

    def __init__(
        self,
        strategies: list[RecoveryStrategy] | None = None,
    ) -> None:
        self._strategies = strategies or list(RecoveryStrategy)

    def next_strategy(self, attempt: int) -> RecoveryStrategy:
        """Return the strategy for the given attempt number (0-based)."""
        if attempt >= len(self._strategies):
            return RecoveryStrategy.ESCALATE
        return self._strategies[attempt]

    def build_recovery_prompt(
        self,
        strategy: RecoveryStrategy,
        stuck_signal: StuckSignal,
        original_goal: str,
    ) -> str:
        """Build a recovery prompt for the given strategy."""
        template = _PROMPT_TEMPLATES[strategy]
        return template.format(
            tool=stuck_signal.repeated_tool,
            count=stuck_signal.repeat_count,
            goal=original_goal,
        )

    def get_recovery(
        self,
        attempt: int,
        stuck_signal: StuckSignal,
        original_goal: str,
    ) -> RecoveryResult:
        """Get recovery result for the given attempt."""
        strategy = self.next_strategy(attempt)
        prompt = self.build_recovery_prompt(strategy, stuck_signal, original_goal)
        should_continue = strategy != RecoveryStrategy.ESCALATE
        return RecoveryResult(
            strategy_used=strategy,
            recovery_prompt=prompt,
            should_continue=should_continue,
        )
