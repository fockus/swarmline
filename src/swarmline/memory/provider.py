"""Memory provider - ISP-compliant protocols.

ISP from RULES.MD: each Protocol has <=5 methods.
The small protocols are defined in swarmline.protocols.

This module re-exports them for convenient imports
and provides a MemoryProvider type hint for the composition root.
"""

from __future__ import annotations

# ISP: all storage protocols have <=5 methods.
# Each consumer depends only on the required subset (ISP/DIP).
# Concrete classes (PostgresMemoryProvider, InMemoryMemoryProvider)
# implement all protocols, but that is an implementation detail, not a contract.
from swarmline.protocols import (
    FactStore,
    GoalStore,
    MessageStore,
    PhaseStore,
    SessionStateStore,
    SummaryStore,
    ToolEventStore,
    UserStore,
)

__all__ = [
    "FactStore",
    "GoalStore",
    "MessageStore",
    "PhaseStore",
    "SessionStateStore",
    "SummaryStore",
    "ToolEventStore",
    "UserStore",
]
