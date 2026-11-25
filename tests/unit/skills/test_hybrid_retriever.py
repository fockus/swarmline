"""Tests for HybridSkillRetriever (RRF fusion)."""

from __future__ import annotations

from swarmline.skills.bm25 import BM25Retriever
from swarmline.skills.embedding_retriever import EmbeddingRetriever
from swarmline.skills.hybrid_retriever import HybridSkillRetriever
from swarmline.skills.protocols import SkillRetriever
from swarmline.skills.types import SkillSpec


def _skill(
    sid: str,
    title: str = "",
    desc: str = "",
    keywords: list[str] | None = None,
    embedding: list[float] | None = None,
) -> SkillSpec:
    return SkillSpec(
        skill_id=sid,
        title=title or sid,
        description=desc,
        keywords=keywords or [],
        embedding=embedding,
    )


CANDIDATES = [
    _skill(
        "web", "Web Search", "Search the internet", ["web", "search"], [1.0, 0.0, 0.0]
    ),
    _skill(
        "code",
        "Code Review",
        "Review code for bugs",
        ["code", "review"],
        [0.0, 1.0, 0.0],
    ),
    _skill(
        "db",
        "Database Query",
        "Execute SQL queries",
        ["sql", "database"],
        [0.0, 0.0, 1.0],
    ),
]


class TestHybridRetrieverProtocol:
    def test_is_skill_retriever(self) -> None:
        retriever = HybridSkillRetriever(retrievers=[BM25Retriever()])
        assert isinstance(retriever, SkillRetriever)


class TestHybridRetrieverBM25Only:
    """With BM25 only, results should reflect BM25 ranking."""

    def test_returns_results_for_matching_query(self) -> None:
        retriever = HybridSkillRetriever(retrievers=[BM25Retriever()])
        results = retriever.retrieve("web search internet", CANDIDATES, top_k=3)
        assert len(results) >= 1

    def test_results_sorted_descending(self) -> None:
        retriever = HybridSkillRetriever(retrievers=[BM25Retriever()])
        results = retriever.retrieve("code review", CANDIDATES, top_k=3)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_source_is_hybrid(self) -> None:
        retriever = HybridSkillRetriever(retrievers=[BM25Retriever()])
        results = retriever.retrieve("web", CANDIDATES, top_k=1)
        assert all(r.source == "hybrid" for r in results)


class TestHybridRetrieverFusion:
    """BM25 + Embedding fusion via RRF."""

    def test_fusion_returns_results(self) -> None:
        def embed_fn(q: str) -> list[float]:
            return [1.0, 0.0, 0.0]  # biased toward "web"

        retriever = HybridSkillRetriever(
            retrievers=[BM25Retriever(), EmbeddingRetriever(embed_fn=embed_fn)],
            weights=[0.4, 0.6],
        )
        results = retriever.retrieve("search", CANDIDATES, top_k=3)
        assert len(results) >= 1

    def test_fusion_scores_in_range(self) -> None:
        def embed_fn(q: str) -> list[float]:
            return [0.0, 1.0, 0.0]

        retriever = HybridSkillRetriever(
            retrievers=[BM25Retriever(), EmbeddingRetriever(embed_fn=embed_fn)],
            weights=[0.4, 0.6],
        )
        results = retriever.retrieve("code", CANDIDATES, top_k=3)
        for r in results:
            assert 0.0 <= r.score <= 1.0


class TestHybridRetrieverEdgeCases:
    def test_empty_query_returns_empty(self) -> None:
        retriever = HybridSkillRetriever(retrievers=[BM25Retriever()])
        results = retriever.retrieve("", CANDIDATES, top_k=3)
        assert results == []

    def test_no_candidates_returns_empty(self) -> None:
        retriever = HybridSkillRetriever(retrievers=[BM25Retriever()])
        results = retriever.retrieve("search", [], top_k=3)
        assert results == []

    def test_min_score_filters(self) -> None:
        retriever = HybridSkillRetriever(retrievers=[BM25Retriever()], min_score=0.99)
        results = retriever.retrieve("web", CANDIDATES, top_k=3)
        for r in results:
            assert r.score >= 0.99

    def test_graceful_degradation_embedding_unavailable(self) -> None:
        """If embedding retriever has no embed_fn, BM25 results still returned."""
        retriever = HybridSkillRetriever(
            retrievers=[BM25Retriever(), EmbeddingRetriever(embed_fn=None)],
            weights=[0.4, 0.6],
        )
        results = retriever.retrieve("web search", CANDIDATES, top_k=3)
        assert len(results) >= 1

    def test_default_equal_weights(self) -> None:
        """When weights=None, all retrievers get equal weight."""
        retriever = HybridSkillRetriever(
            retrievers=[BM25Retriever(), BM25Retriever()],
        )
        results = retriever.retrieve("code", CANDIDATES, top_k=3)
        assert len(results) >= 1


class TestHybridRetrieverRRFBlending:
    """RRF fusion mechanics: blending and weight shifting."""

    def test_hybrid_rrf_fusion_blends_rankings(self) -> None:
        """Two retrievers ranking differently — RRF fuses both into result set."""

        # BM25 favors "web" for "search", embedding favors "code"
        def embed_fn_favors_code(q: str) -> list[float]:
            return [0.0, 1.0, 0.0]

        bm25 = BM25Retriever()
        emb = EmbeddingRetriever(embed_fn=embed_fn_favors_code)
        hybrid = HybridSkillRetriever(retrievers=[bm25, emb], weights=[0.5, 0.5])
        results = hybrid.retrieve("search", CANDIDATES, top_k=3)
        result_ids = {r.skill.skill_id for r in results}
        # Both "web" (from BM25) and "code" (from embedding) should appear
        assert "web" in result_ids
        assert "code" in result_ids

    def test_hybrid_custom_weights_shift_ranking(self) -> None:
        """Heavy embedding weight shifts top result toward embedding favorite."""

        def embed_fn_favors_db(q: str) -> list[float]:
            return [0.0, 0.0, 1.0]  # db=[0,0,1]

        bm25 = BM25Retriever()
        emb = EmbeddingRetriever(embed_fn=embed_fn_favors_db)

        # BM25-heavy: BM25 ranks "web" first for "web search"
        bm25_heavy = HybridSkillRetriever(retrievers=[bm25, emb], weights=[0.9, 0.1])
        results_bm25 = bm25_heavy.retrieve("web search internet", CANDIDATES, top_k=3)

        # Embedding-heavy: embedding ranks "db" first
        emb_heavy = HybridSkillRetriever(retrievers=[bm25, emb], weights=[0.1, 0.9])
        results_emb = emb_heavy.retrieve("web search internet", CANDIDATES, top_k=3)

        # BM25-heavy should rank "web" first
        assert results_bm25[0].skill.skill_id == "web"
        # Embedding-heavy should rank "db" first
        assert results_emb[0].skill.skill_id == "db"

    def test_hybrid_with_single_retriever_matches_base_ranking(self) -> None:
        """Single retriever in hybrid produces same ranking as base retriever."""
        bm25 = BM25Retriever()
        hybrid = HybridSkillRetriever(retrievers=[bm25])
        query = "database sql query"
        base_results = bm25.retrieve(query, CANDIDATES, top_k=3)
        hybrid_results = hybrid.retrieve(query, CANDIDATES, top_k=3)
        base_ids = [r.skill.skill_id for r in base_results]
        hybrid_ids = [r.skill.skill_id for r in hybrid_results]
        assert base_ids == hybrid_ids

    def test_hybrid_threshold_filter_excludes_low_scores(self) -> None:
        """High min_score excludes all low-scoring results."""
        retriever = HybridSkillRetriever(retrievers=[BM25Retriever()], min_score=0.999)
        results = retriever.retrieve("code review bugs", CANDIDATES, top_k=3)
        # With such high threshold, only the top result (if normalized to 1.0) passes
        assert all(r.score >= 0.999 for r in results)

    def test_hybrid_respects_top_k(self) -> None:
        retriever = HybridSkillRetriever(retrievers=[BM25Retriever()])
        results = retriever.retrieve("code", CANDIDATES, top_k=1)
        assert len(results) <= 1
