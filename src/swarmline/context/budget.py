"""ContextBudget - management of context packet sizes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextBudget:
    """Token budget for context packets.

    Priority (highest to lowest):
    P0: guardrails   - never dropped
    P1: active_goal  - truncate to goal_max if needed
    P2: tool hints   - keep only for active skills
    P3: memory recall - reduce top-k
    P4: user_profile  - truncate to key facts
    P5: summary      - dropped first
    """

    total_tokens: int = 8000
    guardrails_reserved: int = 1500  # P0: always reserved
    goal_max: int = 1000  # P1
    tools_max: int = 2000  # P2
    messages_max: int = 2000  # P2.5: latest conversation messages
    memory_max: int = 1500  # P3
    profile_max: int = 1000  # P4
    summary_max: int = 1000  # P5


def estimate_tokens(text: str) -> int:
    """Rough token estimate (1 token ~ 4 characters for Russian/English)."""
    return len(text) // 4 + 1


def truncate_to_budget(text: str, max_tokens: int) -> str:
    """Truncate text to max_tokens (approximately)."""
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [обрезано]"
