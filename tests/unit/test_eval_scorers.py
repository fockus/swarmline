"""Unit: builtin eval scorers."""

from __future__ import annotations

import pytest

from swarmline.eval.types import EvalCase, Scorer

# Import scorers (will create these)
from swarmline.eval.scorers import (
    ContainsScorer,
    CostScorer,
    ExactMatchScorer,
    LatencyScorer,
    RegexScorer,
)


def _case(expected: str | None = None, **ctx: object) -> EvalCase:
    return EvalCase(id="t1", input="test", expected=expected, context=dict(ctx))


# ---------------------------------------------------------------------------
# ExactMatchScorer
# ---------------------------------------------------------------------------


class TestExactMatchScorer:

    @pytest.fixture
    def scorer(self) -> ExactMatchScorer:
        return ExactMatchScorer()

    async def test_exact_match(self, scorer: ExactMatchScorer) -> None:
        result = await scorer.score(_case(expected="hello"), "hello")
        assert result.score == 1.0

    async def test_mismatch(self, scorer: ExactMatchScorer) -> None:
        result = await scorer.score(_case(expected="hello"), "world")
        assert result.score == 0.0

    async def test_case_insensitive(self) -> None:
        scorer = ExactMatchScorer(case_sensitive=False)
        result = await scorer.score(_case(expected="Hello"), "hello")
        assert result.score == 1.0

    async def test_no_expected_returns_zero(self, scorer: ExactMatchScorer) -> None:
        result = await scorer.score(_case(), "anything")
        assert result.score == 0.0

    async def test_implements_protocol(self, scorer: ExactMatchScorer) -> None:
        assert isinstance(scorer, Scorer)

    async def test_has_name(self, scorer: ExactMatchScorer) -> None:
        assert scorer.name == "exact_match"


# ---------------------------------------------------------------------------
# ContainsScorer
# ---------------------------------------------------------------------------


class TestContainsScorer:

    @pytest.fixture
    def scorer(self) -> ContainsScorer:
        return ContainsScorer()

    async def test_contains(self, scorer: ContainsScorer) -> None:
        result = await scorer.score(_case(expected="Paris"), "The capital is Paris.")
        assert result.score == 1.0

    async def test_not_contains(self, scorer: ContainsScorer) -> None:
        result = await scorer.score(_case(expected="London"), "The capital is Paris.")
        assert result.score == 0.0

    async def test_case_insensitive(self) -> None:
        scorer = ContainsScorer(case_sensitive=False)
        result = await scorer.score(_case(expected="paris"), "The capital is Paris.")
        assert result.score == 1.0

    async def test_no_expected(self, scorer: ContainsScorer) -> None:
        result = await scorer.score(_case(), "anything")
        assert result.score == 0.0


# ---------------------------------------------------------------------------
# RegexScorer
# ---------------------------------------------------------------------------


class TestRegexScorer:

    async def test_pattern_matches(self) -> None:
        scorer = RegexScorer(pattern=r"\d{3}-\d{4}")
        result = await scorer.score(_case(), "call 555-1234 now")
        assert result.score == 1.0

    async def test_pattern_no_match(self) -> None:
        scorer = RegexScorer(pattern=r"\d{3}-\d{4}")
        result = await scorer.score(_case(), "no phone here")
        assert result.score == 0.0

    async def test_expected_as_pattern(self) -> None:
        scorer = RegexScorer()
        result = await scorer.score(_case(expected=r"\d+"), "there are 42 items")
        assert result.score == 1.0

    async def test_no_pattern_no_expected(self) -> None:
        scorer = RegexScorer()
        result = await scorer.score(_case(), "anything")
        assert result.score == 0.0


# ---------------------------------------------------------------------------
# LatencyScorer
# ---------------------------------------------------------------------------


class TestLatencyScorer:

    async def test_under_threshold(self) -> None:
        scorer = LatencyScorer(max_ms=500.0)
        # LatencyScorer reads latency_ms from context
        result = await scorer.score(_case(latency_ms=200.0), "output")
        assert result.score == 1.0

    async def test_over_threshold(self) -> None:
        scorer = LatencyScorer(max_ms=500.0)
        result = await scorer.score(_case(latency_ms=800.0), "output")
        assert result.score < 0.5

    async def test_exact_threshold(self) -> None:
        scorer = LatencyScorer(max_ms=500.0)
        result = await scorer.score(_case(latency_ms=500.0), "output")
        assert result.score == 1.0


# ---------------------------------------------------------------------------
# CostScorer
# ---------------------------------------------------------------------------


class TestCostScorer:

    async def test_under_budget(self) -> None:
        scorer = CostScorer(max_cost_usd=1.0)
        result = await scorer.score(_case(cost_usd=0.05), "output")
        assert result.score == 1.0

    async def test_over_budget(self) -> None:
        scorer = CostScorer(max_cost_usd=0.10)
        result = await scorer.score(_case(cost_usd=0.50), "output")
        assert result.score < 0.5

    async def test_no_cost_info(self) -> None:
        scorer = CostScorer(max_cost_usd=1.0)
        result = await scorer.score(_case(), "output")
        assert result.score == 1.0  # no cost data = pass
