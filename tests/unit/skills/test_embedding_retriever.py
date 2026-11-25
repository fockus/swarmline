"""Tests for EmbeddingRetriever."""

from __future__ import annotations

from swarmline.skills.embedding_retriever import EmbeddingRetriever
from swarmline.skills.protocols import SkillRetriever
from swarmline.skills.types import SkillSpec


def _skill(sid: str, embedding: list[float] | None = None) -> SkillSpec:
    return SkillSpec(skill_id=sid, title=sid, embedding=embedding)


class TestEmbeddingRetrieverProtocol:
    def test_is_skill_retriever(self) -> None:
        retriever = EmbeddingRetriever(embed_fn=lambda q: [1.0, 0.0])
        assert isinstance(retriever, SkillRetriever)


class TestEmbeddingRetrieverRetrieve:
    def test_returns_scored_skills_sorted_descending(self) -> None:
        def embed_fn(q: str) -> list[float]:
            return [1.0, 0.0, 0.0]

        candidates = [
            _skill("a", [1.0, 0.0, 0.0]),  # exact match
            _skill("b", [0.0, 1.0, 0.0]),  # orthogonal
            _skill("c", [0.7, 0.7, 0.0]),  # partial
        ]
        retriever = EmbeddingRetriever(embed_fn=embed_fn)
        results = retriever.retrieve("test", candidates, top_k=3)
        assert results[0].skill.skill_id == "a"
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_scores_in_zero_one_range(self) -> None:
        def embed_fn(q: str) -> list[float]:
            return [1.0, 0.0]

        candidates = [_skill("a", [1.0, 0.0]), _skill("b", [0.5, 0.5])]
        retriever = EmbeddingRetriever(embed_fn=embed_fn)
        results = retriever.retrieve("q", candidates, top_k=2)
        for r in results:
            assert 0.0 <= r.score <= 1.0

    def test_source_is_embedding(self) -> None:
        retriever = EmbeddingRetriever(embed_fn=lambda q: [1.0])
        results = retriever.retrieve("q", [_skill("a", [1.0])], top_k=1)
        assert all(r.source == "embedding" for r in results)

    def test_respects_top_k(self) -> None:
        retriever = EmbeddingRetriever(embed_fn=lambda q: [1.0, 0.0])
        candidates = [_skill(f"s{i}", [1.0, 0.0]) for i in range(5)]
        results = retriever.retrieve("q", candidates, top_k=2)
        assert len(results) <= 2


class TestEmbeddingRetrieverEdgeCases:
    def test_no_embed_fn_returns_empty(self) -> None:
        retriever = EmbeddingRetriever(embed_fn=None)
        results = retriever.retrieve("q", [_skill("a", [1.0])], top_k=5)
        assert results == []

    def test_skill_without_embedding_skipped(self) -> None:
        retriever = EmbeddingRetriever(embed_fn=lambda q: [1.0, 0.0])
        candidates = [_skill("no_emb"), _skill("has_emb", [1.0, 0.0])]
        results = retriever.retrieve("q", candidates, top_k=5)
        assert len(results) == 1
        assert results[0].skill.skill_id == "has_emb"

    def test_empty_candidates_returns_empty(self) -> None:
        retriever = EmbeddingRetriever(embed_fn=lambda q: [1.0])
        results = retriever.retrieve("q", [], top_k=5)
        assert results == []

    def test_empty_query_returns_empty(self) -> None:
        retriever = EmbeddingRetriever(embed_fn=lambda q: [1.0])
        results = retriever.retrieve("", [_skill("a", [1.0])], top_k=5)
        assert results == []

    def test_opposing_vectors_excluded(self) -> None:
        """Negative cosine similarity is clamped to 0 and excluded."""
        retriever = EmbeddingRetriever(embed_fn=lambda q: [1.0, 0.0])
        candidates = [_skill("opp", [-1.0, 0.0])]
        results = retriever.retrieve("q", candidates, top_k=5)
        assert results == []

    def test_zero_vector_skill_returns_zero_score(self) -> None:
        """Zero-norm embedding → cosine=0 → excluded from results."""
        retriever = EmbeddingRetriever(embed_fn=lambda q: [1.0, 0.0])
        candidates = [_skill("zero", [0.0, 0.0])]
        results = retriever.retrieve("q", candidates, top_k=5)
        assert results == []

    def test_zero_query_vector_returns_empty(self) -> None:
        """Zero-norm query embedding → cosine=0 for all candidates."""
        retriever = EmbeddingRetriever(embed_fn=lambda q: [0.0, 0.0])
        candidates = [_skill("a", [1.0, 0.0])]
        results = retriever.retrieve("q", candidates, top_k=5)
        assert results == []

    def test_whitespace_query_returns_empty(self) -> None:
        retriever = EmbeddingRetriever(embed_fn=lambda q: [1.0])
        results = retriever.retrieve("   ", [_skill("a", [1.0])], top_k=5)
        assert results == []
