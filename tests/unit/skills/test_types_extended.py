"""Tests for new SkillSpec fields: tier, health_status, embedding, keywords."""

from __future__ import annotations

from swarmline.skills.tier import SkillHealthStatus, SkillTier
from swarmline.skills.types import SkillSpec


class TestSkillSpecNewFields:
    """SkillSpec extended with tier, health_status, embedding, keywords."""

    def test_default_tier_is_t2_role(self) -> None:
        spec = SkillSpec(skill_id="x", title="X")
        assert spec.tier == SkillTier.T2_ROLE

    def test_default_health_is_healthy(self) -> None:
        spec = SkillSpec(skill_id="x", title="X")
        assert spec.health_status == SkillHealthStatus.HEALTHY

    def test_default_embedding_is_none(self) -> None:
        spec = SkillSpec(skill_id="x", title="X")
        assert spec.embedding is None

    def test_default_keywords_is_empty_list(self) -> None:
        spec = SkillSpec(skill_id="x", title="X")
        assert spec.keywords == []

    def test_custom_tier(self) -> None:
        spec = SkillSpec(skill_id="x", title="X", tier=SkillTier.T1_ALWAYS)
        assert spec.tier == SkillTier.T1_ALWAYS

    def test_custom_embedding(self) -> None:
        emb = [0.1, 0.2, 0.3]
        spec = SkillSpec(skill_id="x", title="X", embedding=emb)
        assert spec.embedding == [0.1, 0.2, 0.3]

    def test_custom_keywords(self) -> None:
        spec = SkillSpec(skill_id="x", title="X", keywords=["api", "rest"])
        assert spec.keywords == ["api", "rest"]

    def test_backward_compat_no_new_fields(self) -> None:
        """Old-style creation without new fields still works."""
        spec = SkillSpec(
            skill_id="old",
            title="Old Skill",
            description="desc",
            instruction_file="file.md",
        )
        assert spec.skill_id == "old"
        assert spec.tier == SkillTier.T2_ROLE
        assert spec.health_status == SkillHealthStatus.HEALTHY
        assert spec.embedding is None
        assert spec.keywords == []
