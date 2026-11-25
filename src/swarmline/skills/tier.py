"""Skill tier classification and health status."""

from __future__ import annotations

from enum import Enum, IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from swarmline.skills.types import SkillSpec


class SkillTier(IntEnum):
    """Skill availability tier (lower = higher priority)."""

    T1_ALWAYS = 1
    T2_ROLE = 2
    T3_DISCOVERABLE = 3
    T4_DISABLED = 4


class SkillHealthStatus(Enum):
    """Runtime health status of a skill's dependencies."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


def filter_by_tier(skills: list[SkillSpec], max_tier: SkillTier) -> list[SkillSpec]:
    """Return skills whose tier is at or below *max_tier*."""
    return [s for s in skills if s.tier <= max_tier]
