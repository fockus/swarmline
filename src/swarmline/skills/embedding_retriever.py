"""Embedding-based skill retriever using cosine similarity."""

from __future__ import annotations

import math
from collections.abc import Callable

from swarmline.skills.protocols import ScoredSkill
from swarmline.skills.types import SkillSpec


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class EmbeddingRetriever:
    """Skill retriever based on cosine similarity of pre-computed embeddings.

    Implements SkillRetriever Protocol.
    """

    def __init__(self, embed_fn: Callable[[str], list[float]] | None = None) -> None:
        self._embed_fn = embed_fn

    def retrieve(
        self, query: str, candidates: list[SkillSpec], top_k: int = 8
    ) -> list[ScoredSkill]:
        """Score candidates by cosine similarity to query embedding."""
        if not query.strip() or not candidates or self._embed_fn is None:
            return []

        query_emb = self._embed_fn(query)
        scored: list[ScoredSkill] = []
        for skill in candidates:
            if skill.embedding is None:
                continue
            sim = _cosine_similarity(query_emb, skill.embedding)
            # Clamp to [0, 1] (cosine can be negative for opposing vectors)
            clamped = max(0.0, min(1.0, sim))
            if clamped > 0.0:
                scored.append(
                    ScoredSkill(skill=skill, score=clamped, source="embedding")
                )

        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top_k]
