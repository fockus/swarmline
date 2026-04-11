"""Core Swarmline types - contracts from architecture section 17.

Contains the shared types used across modules:
TurnContext, ContextPack, SkillSet.
"""

from __future__ import annotations

from dataclasses import dataclass

from swarmline.domain_types import RuntimeEvent

__all__ = ["ContextPack", "RuntimeEvent", "SkillSet", "TurnContext"]


@dataclass(frozen=True)
class TurnContext:
    """Unified turn context - passed between modules.

    Contains everything needed for decisions:
    model selection, tool policy, context assembly.
    """

    user_id: str
    topic_id: str
    role_id: str
    model: str
    active_skill_ids: tuple[str, ...]


@dataclass(frozen=True)
class ContextPack:
    """A context unit with priority and size estimation.

    Priorities (from architecture section 10.2):
    0 - Guardrails (never dropped)
    1 - Role instruction
    2 - Active goals
    3 - Phase
    4 - Tool hints
    5 - Memory recall
    6 - User profile
    """

    pack_id: str
    priority: int
    content: str
    tokens_estimate: int


@dataclass(frozen=True)
class SkillSet:
    """Named skill set (architecture section 5.1).

    The role selects a SkillSet -> the SkillSet defines the tool allowlist.
    """

    set_id: str
    skill_ids: tuple[str, ...] = ()
    local_tool_ids: tuple[str, ...] = ()
