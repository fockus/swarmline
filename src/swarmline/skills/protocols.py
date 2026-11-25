"""Protocols for skill storage and retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from swarmline.skills.types import SkillSpec


@dataclass(frozen=True)
class ScoredSkill:
    """A skill with a relevance score from a retriever."""

    skill: SkillSpec
    score: float
    source: str


@runtime_checkable
class SkillStore(Protocol):
    """Port: read-only access to the skill catalog."""

    def get_spec(self, skill_id: str) -> SkillSpec | None: ...

    def list_specs(self) -> list[SkillSpec]: ...

    def search(self, query: str, top_k: int = 5) -> list[ScoredSkill]: ...


@runtime_checkable
class SkillRetriever(Protocol):
    """Port: retrieves and scores skills against a query."""

    def retrieve(
        self, query: str, candidates: list[SkillSpec], top_k: int = 5
    ) -> list[ScoredSkill]: ...
