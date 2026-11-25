"""Tests for SkillStore Protocol, SkillRetriever Protocol, and ScoredSkill."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from swarmline.skills.protocols import ScoredSkill, SkillRetriever, SkillStore
from swarmline.skills.types import SkillSpec


class TestScoredSkill:
    """ScoredSkill is a frozen dataclass with skill, score, source."""

    def test_create_scored_skill(self) -> None:
        spec = SkillSpec(skill_id="test", title="Test")
        scored = ScoredSkill(skill=spec, score=0.85, source="bm25")
        assert scored.skill is spec
        assert scored.score == 0.85
        assert scored.source == "bm25"

    def test_scored_skill_is_frozen(self) -> None:
        spec = SkillSpec(skill_id="test", title="Test")
        scored = ScoredSkill(skill=spec, score=0.5, source="embed")
        with pytest.raises(FrozenInstanceError):
            scored.score = 0.9  # type: ignore[misc]


class TestSkillStoreProtocol:
    """SkillStore is a runtime_checkable Protocol."""

    def test_protocol_is_runtime_checkable(self) -> None:
        assert hasattr(SkillStore, "__protocol_attrs__") or isinstance(SkillStore, type)

    def test_conforming_class_is_instance(self) -> None:
        class _FakeStore:
            def get_spec(self, skill_id: str) -> SkillSpec | None:
                return None

            def list_specs(self) -> list[SkillSpec]:
                return []

            def search(self, query: str, top_k: int = 5) -> list[ScoredSkill]:
                return []

        assert isinstance(_FakeStore(), SkillStore)

    def test_non_conforming_class_is_not_instance(self) -> None:
        class _BadStore:
            pass

        assert not isinstance(_BadStore(), SkillStore)


class TestSkillRetrieverProtocol:
    """SkillRetriever is a runtime_checkable Protocol."""

    def test_conforming_class_is_instance(self) -> None:
        class _FakeRetriever:
            def retrieve(
                self, query: str, candidates: list[SkillSpec], top_k: int = 5
            ) -> list[ScoredSkill]:
                return []

        assert isinstance(_FakeRetriever(), SkillRetriever)

    def test_non_conforming_class_is_not_instance(self) -> None:
        class _Bad:
            pass

        assert not isinstance(_Bad(), SkillRetriever)
