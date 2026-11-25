"""Hybrid skill retriever — Reciprocal Rank Fusion of multiple retrievers."""

from __future__ import annotations

from collections import defaultdict

from swarmline.skills.protocols import ScoredSkill, SkillRetriever
from swarmline.skills.types import SkillSpec

_RRF_K = 60  # standard RRF constant


class HybridSkillRetriever:
    """Fuses results from multiple SkillRetrievers via Reciprocal Rank Fusion.

    Implements SkillRetriever Protocol.
    """

    def __init__(
        self,
        retrievers: list[SkillRetriever],
        weights: list[float] | None = None,
        min_score: float = 0.1,
    ) -> None:
        self._retrievers = retrievers
        self._weights = weights or [1.0 / len(retrievers)] * len(retrievers)
        self.min_score = min_score

    def retrieve(
        self, query: str, candidates: list[SkillSpec], top_k: int = 8
    ) -> list[ScoredSkill]:
        """Fuse retriever results via RRF and return top-k above threshold."""
        if not query.strip() or not candidates:
            return []

        # Collect ranked lists from each retriever
        # Use generous top_k for sub-retrievers so RRF has full ranked lists
        sub_top_k = len(candidates)
        rrf_scores: dict[str, float] = defaultdict(float)
        skill_map: dict[str, SkillSpec] = {}

        for retriever, weight in zip(self._retrievers, self._weights, strict=True):
            results = retriever.retrieve(query, candidates, top_k=sub_top_k)
            for rank, scored in enumerate(results, start=1):
                sid = scored.skill.skill_id
                rrf_scores[sid] += weight * (1.0 / (_RRF_K + rank))
                skill_map[sid] = scored.skill

        if not rrf_scores:
            return []

        # Normalize to [0, 1]
        max_score = max(rrf_scores.values())
        if max_score <= 0.0:
            return []

        scored: list[ScoredSkill] = []
        for sid, raw in rrf_scores.items():
            norm = raw / max_score
            if norm >= self.min_score:
                scored.append(
                    ScoredSkill(skill=skill_map[sid], score=norm, source="hybrid")
                )

        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top_k]
