"""Tests for BM25Retriever."""

from __future__ import annotations

import pytest
from swarmline.skills.bm25 import BM25Retriever
from swarmline.skills.protocols import ScoredSkill, SkillRetriever
from swarmline.skills.types import SkillSpec


def _skill(
    sid: str, title: str, desc: str = "", keywords: list[str] | None = None
) -> SkillSpec:
    return SkillSpec(
        skill_id=sid,
        title=title,
        description=desc,
        keywords=keywords or [],
    )


CANDIDATES = [
    _skill(
        "web", "Web Search", "Search the internet for information", ["web", "search"]
    ),
    _skill(
        "code",
        "Code Review",
        "Review code for bugs and style issues",
        ["code", "review"],
    ),
    _skill(
        "db", "Database Query", "Execute SQL queries on database", ["sql", "database"]
    ),
    _skill(
        "deploy", "Deploy Service", "Deploy application to production", ["deploy", "ci"]
    ),
]


class TestBM25RetrieverProtocol:
    """BM25Retriever satisfies SkillRetriever Protocol."""

    def test_is_skill_retriever(self) -> None:
        retriever = BM25Retriever()
        assert isinstance(retriever, SkillRetriever)


class TestBM25RetrieverRetrieve:
    """Core retrieval behavior."""

    def test_retrieve_returns_sorted_by_score_descending(self) -> None:
        retriever = BM25Retriever()
        results = retriever.retrieve("search web", CANDIDATES, top_k=4)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_retrieve_returns_scored_skills(self) -> None:
        retriever = BM25Retriever()
        results = retriever.retrieve("code review", CANDIDATES, top_k=2)
        assert all(isinstance(r, ScoredSkill) for r in results)

    def test_retrieve_source_is_bm25(self) -> None:
        retriever = BM25Retriever()
        results = retriever.retrieve("database query", CANDIDATES, top_k=1)
        assert all(r.source == "bm25" for r in results)

    def test_retrieve_scores_in_zero_one_range(self) -> None:
        retriever = BM25Retriever()
        results = retriever.retrieve("code", CANDIDATES, top_k=4)
        for r in results:
            assert 0.0 <= r.score <= 1.0, f"Score {r.score} out of range"

    def test_retrieve_respects_top_k(self) -> None:
        retriever = BM25Retriever()
        results = retriever.retrieve("code", CANDIDATES, top_k=1)
        assert len(results) <= 1

    def test_retrieve_relevant_skill_ranked_first(self) -> None:
        retriever = BM25Retriever()
        results = retriever.retrieve("database sql query", CANDIDATES, top_k=4)
        assert results[0].skill.skill_id == "db"


class TestBM25RetrieverEdgeCases:
    """Edge cases: empty inputs, thresholds."""

    def test_empty_query_returns_empty(self) -> None:
        retriever = BM25Retriever()
        results = retriever.retrieve("", CANDIDATES, top_k=4)
        assert results == []

    def test_no_candidates_returns_empty(self) -> None:
        retriever = BM25Retriever()
        results = retriever.retrieve("search", [], top_k=4)
        assert results == []

    def test_whitespace_query_returns_empty(self) -> None:
        retriever = BM25Retriever()
        results = retriever.retrieve("   ", CANDIDATES, top_k=4)
        assert results == []

    def test_min_score_filters_low_scores(self) -> None:
        retriever = BM25Retriever(min_score=0.99)
        results = retriever.retrieve("code", CANDIDATES, top_k=4)
        for r in results:
            assert r.score >= 0.99

    def test_single_candidate(self) -> None:
        retriever = BM25Retriever()
        single = [_skill("only", "Only Skill", "the one and only")]
        results = retriever.retrieve("only skill", single, top_k=5)
        assert len(results) >= 1
        assert results[0].skill.skill_id == "only"

    def test_no_matching_terms_returns_empty_or_low(self) -> None:
        retriever = BM25Retriever()
        results = retriever.retrieve("zzzzxyzzy", CANDIDATES, top_k=4)
        assert len(results) == 0


class TestBM25RetrieverConfig:
    """Configuration: k1, b, min_score."""

    def test_custom_k1_b(self) -> None:
        retriever = BM25Retriever(k1=2.0, b=0.5)
        results = retriever.retrieve("code review", CANDIDATES, top_k=2)
        assert len(results) >= 1

    def test_default_min_score(self) -> None:
        retriever = BM25Retriever()
        assert retriever.min_score == 0.1


class TestBM25Tokenizer:
    """_tokenize: punctuation, special chars, case folding."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Hello, World!", ["hello", "world"]),
            ("foo--bar__baz", ["foo", "bar", "baz"]),
            ("CamelCase123", ["camelcase123"]),
            ("a.b.c@d#e", ["a", "b", "c", "d", "e"]),
            ("   spaces   ", ["spaces"]),
            ("MiXeD-CASE_text!", ["mixed", "case", "text"]),
            ("", []),
        ],
    )
    def test_tokenizer_handles_punctuation_and_special_chars(
        self, text: str, expected: list[str]
    ) -> None:
        from swarmline.skills.bm25 import _tokenize

        assert _tokenize(text) == expected


class TestBM25ScoringSemantics:
    """Scoring: exact vs partial, query-candidate relevance."""

    def test_bm25_scoring_favors_exact_match_over_partial(self) -> None:
        exact = _skill(
            "exact", "database query", "execute database queries", ["database"]
        )
        partial = _skill(
            "partial", "data processing", "process data pipelines", ["data"]
        )
        retriever = BM25Retriever()
        results = retriever.retrieve("database query", [exact, partial], top_k=2)
        assert results[0].skill.skill_id == "exact"

    @pytest.mark.parametrize(
        ("query", "expected_first"),
        [
            ("deploy application production", "deploy"),
            ("code review bugs style", "code"),
            ("search web internet", "web"),
            ("sql database query", "db"),
        ],
    )
    def test_query_routes_to_most_relevant_skill(
        self, query: str, expected_first: str
    ) -> None:
        retriever = BM25Retriever()
        results = retriever.retrieve(query, CANDIDATES, top_k=1)
        assert len(results) >= 1
        assert results[0].skill.skill_id == expected_first

    def test_intents_field_contributes_to_scoring(self) -> None:
        """Skills with matching intents should score higher."""
        with_intent = SkillSpec(
            skill_id="intent_match",
            title="Generic Tool",
            description="A tool",
            intents=["find information online"],
        )
        without_intent = SkillSpec(
            skill_id="no_intent",
            title="Generic Tool",
            description="A tool",
            intents=[],
        )
        retriever = BM25Retriever()
        results = retriever.retrieve(
            "find information", [with_intent, without_intent], top_k=2
        )
        assert results[0].skill.skill_id == "intent_match"

    def test_keywords_boost_relevance(self) -> None:
        """Keywords matching query tokens boost score."""
        with_kw = _skill("kw", "Tool", "a tool", keywords=["search", "web", "internet"])
        without_kw = _skill("no_kw", "Tool", "a tool", keywords=[])
        retriever = BM25Retriever()
        results = retriever.retrieve("search internet", [with_kw, without_kw], top_k=2)
        assert results[0].skill.skill_id == "kw"
