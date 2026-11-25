"""Tests for SkillTier, SkillHealthStatus, and filter_by_tier."""

from __future__ import annotations

import pytest
from swarmline.skills.tier import SkillHealthStatus, SkillTier, filter_by_tier
from swarmline.skills.types import SkillSpec


class TestSkillTier:
    """SkillTier enum: 4 ordered levels."""

    def test_tier_has_four_levels(self) -> None:
        assert len(SkillTier) == 4

    def test_tier_ordering_t1_less_than_t2(self) -> None:
        assert SkillTier.T1_ALWAYS < SkillTier.T2_ROLE

    def test_tier_ordering_t2_less_than_t3(self) -> None:
        assert SkillTier.T2_ROLE < SkillTier.T3_DISCOVERABLE

    def test_tier_ordering_t3_less_than_t4(self) -> None:
        assert SkillTier.T3_DISCOVERABLE < SkillTier.T4_DISABLED

    def test_tier_values(self) -> None:
        assert SkillTier.T1_ALWAYS == 1
        assert SkillTier.T2_ROLE == 2
        assert SkillTier.T3_DISCOVERABLE == 3
        assert SkillTier.T4_DISABLED == 4

    def test_tier_is_intenum(self) -> None:
        assert isinstance(SkillTier.T1_ALWAYS, int)


class TestSkillHealthStatus:
    """SkillHealthStatus enum."""

    def test_has_three_statuses(self) -> None:
        assert len(SkillHealthStatus) == 3

    def test_statuses_exist(self) -> None:
        assert SkillHealthStatus.HEALTHY is not None
        assert SkillHealthStatus.DEGRADED is not None
        assert SkillHealthStatus.UNAVAILABLE is not None


def _make_skill(skill_id: str, tier: SkillTier) -> SkillSpec:
    return SkillSpec(skill_id=skill_id, title=skill_id, tier=tier)


class TestFilterByTier:
    """filter_by_tier returns only skills with tier <= max_tier."""

    def test_filter_t1_only(self) -> None:
        skills = [
            _make_skill("a", SkillTier.T1_ALWAYS),
            _make_skill("b", SkillTier.T2_ROLE),
            _make_skill("c", SkillTier.T3_DISCOVERABLE),
        ]
        result = filter_by_tier(skills, SkillTier.T1_ALWAYS)
        assert [s.skill_id for s in result] == ["a"]

    def test_filter_up_to_t2(self) -> None:
        skills = [
            _make_skill("a", SkillTier.T1_ALWAYS),
            _make_skill("b", SkillTier.T2_ROLE),
            _make_skill("c", SkillTier.T3_DISCOVERABLE),
        ]
        result = filter_by_tier(skills, SkillTier.T2_ROLE)
        assert [s.skill_id for s in result] == ["a", "b"]

    def test_filter_up_to_t3_includes_all_except_disabled(self) -> None:
        skills = [
            _make_skill("a", SkillTier.T1_ALWAYS),
            _make_skill("d", SkillTier.T4_DISABLED),
        ]
        result = filter_by_tier(skills, SkillTier.T3_DISCOVERABLE)
        assert [s.skill_id for s in result] == ["a"]

    def test_filter_empty_list(self) -> None:
        result = filter_by_tier([], SkillTier.T3_DISCOVERABLE)
        assert result == []

    def test_filter_t4_includes_all(self) -> None:
        skills = [
            _make_skill("a", SkillTier.T1_ALWAYS),
            _make_skill("b", SkillTier.T2_ROLE),
            _make_skill("c", SkillTier.T3_DISCOVERABLE),
            _make_skill("d", SkillTier.T4_DISABLED),
        ]
        result = filter_by_tier(skills, SkillTier.T4_DISABLED)
        assert len(result) == 4

    def test_filter_returns_empty_when_all_above_threshold(self) -> None:
        skills = [
            _make_skill("x", SkillTier.T3_DISCOVERABLE),
            _make_skill("y", SkillTier.T4_DISABLED),
        ]
        result = filter_by_tier(skills, SkillTier.T2_ROLE)
        assert result == []


class TestSkillHealthStatusValues:
    """Health status string values."""

    def test_healthy_value(self) -> None:
        assert SkillHealthStatus.HEALTHY.value == "healthy"

    def test_degraded_value(self) -> None:
        assert SkillHealthStatus.DEGRADED.value == "degraded"

    def test_unavailable_value(self) -> None:
        assert SkillHealthStatus.UNAVAILABLE.value == "unavailable"


class TestSkillTierComparisons:
    """Full ordering parametrized."""

    @pytest.mark.parametrize(
        ("lower", "higher"),
        [
            (SkillTier.T1_ALWAYS, SkillTier.T2_ROLE),
            (SkillTier.T1_ALWAYS, SkillTier.T3_DISCOVERABLE),
            (SkillTier.T1_ALWAYS, SkillTier.T4_DISABLED),
            (SkillTier.T2_ROLE, SkillTier.T3_DISCOVERABLE),
            (SkillTier.T2_ROLE, SkillTier.T4_DISABLED),
            (SkillTier.T3_DISCOVERABLE, SkillTier.T4_DISABLED),
        ],
    )
    def test_tier_ordering_all_pairs(self, lower: SkillTier, higher: SkillTier) -> None:
        assert lower < higher
