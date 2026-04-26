"""Unit: eval framework types — EvalCase, ScorerResult, EvalResult, EvalReport."""

from __future__ import annotations

from swarmline.eval.types import EvalCase, EvalReport, EvalResult, Scorer, ScorerResult


# ---------------------------------------------------------------------------
# EvalCase
# ---------------------------------------------------------------------------


class TestEvalCase:
    def test_minimal_creation(self) -> None:
        case = EvalCase(id="c1", input="hello")
        assert case.id == "c1"
        assert case.input == "hello"
        assert case.expected is None
        assert case.tags == ()

    def test_full_creation(self) -> None:
        case = EvalCase(
            id="c2",
            input="What is 2+2?",
            expected="4",
            context={"topic": "math"},
            tags=("math", "basic"),
        )
        assert case.expected == "4"
        assert case.context["topic"] == "math"
        assert len(case.tags) == 2

    def test_frozen(self) -> None:
        case = EvalCase(id="c1", input="hi")
        try:
            case.id = "c2"  # type: ignore[misc]
            assert False, "should be frozen"
        except AttributeError:
            pass


# ---------------------------------------------------------------------------
# ScorerResult
# ---------------------------------------------------------------------------


class TestScorerResult:
    def test_creation(self) -> None:
        sr = ScorerResult(score=0.9, reason="matches", details={"key": "val"})
        assert sr.score == 0.9
        assert sr.reason == "matches"

    def test_defaults(self) -> None:
        sr = ScorerResult(score=0.5, reason="ok")
        assert sr.details == {}


# ---------------------------------------------------------------------------
# EvalResult
# ---------------------------------------------------------------------------


class TestEvalResult:
    def test_passed_when_all_scores_above_threshold(self) -> None:
        case = EvalCase(id="c1", input="hi")
        result = EvalResult(
            case=case,
            output="hello",
            scores={
                "exact": ScorerResult(score=0.8, reason="close"),
                "contains": ScorerResult(score=0.6, reason="partial"),
            },
        )
        assert result.passed is True

    def test_failed_when_score_below_threshold(self) -> None:
        case = EvalCase(id="c1", input="hi")
        result = EvalResult(
            case=case,
            output="hello",
            scores={"exact": ScorerResult(score=0.3, reason="mismatch")},
        )
        assert result.passed is False

    def test_failed_on_error(self) -> None:
        case = EvalCase(id="c1", input="hi")
        result = EvalResult(case=case, output="", error="timeout")
        assert result.passed is False

    def test_mean_score(self) -> None:
        case = EvalCase(id="c1", input="hi")
        result = EvalResult(
            case=case,
            output="hello",
            scores={
                "a": ScorerResult(score=0.8, reason=""),
                "b": ScorerResult(score=0.6, reason=""),
            },
        )
        assert abs(result.mean_score - 0.7) < 0.01

    def test_mean_score_empty(self) -> None:
        case = EvalCase(id="c1", input="hi")
        result = EvalResult(case=case, output="hello")
        assert result.mean_score == 0.0


# ---------------------------------------------------------------------------
# EvalReport
# ---------------------------------------------------------------------------


class TestEvalReport:
    def _make_result(self, score: float) -> EvalResult:
        case = EvalCase(id=f"c-{score}", input="hi")
        return EvalResult(
            case=case,
            output="out",
            scores={"s": ScorerResult(score=score, reason="")},
        )

    def test_counts(self) -> None:
        report = EvalReport(
            results=(
                self._make_result(0.8),
                self._make_result(0.3),
                self._make_result(0.9),
            )
        )
        assert report.total == 3
        assert report.passed == 2
        assert report.failed == 1

    def test_pass_rate(self) -> None:
        report = EvalReport(results=(self._make_result(0.8), self._make_result(0.3)))
        assert abs(report.pass_rate - 0.5) < 0.01

    def test_mean_score(self) -> None:
        report = EvalReport(results=(self._make_result(0.8), self._make_result(0.6)))
        assert abs(report.mean_score - 0.7) < 0.01

    def test_scores_by_scorer(self) -> None:
        report = EvalReport(results=(self._make_result(0.8), self._make_result(0.6)))
        by_scorer = report.scores_by_scorer
        assert "s" in by_scorer
        assert len(by_scorer["s"]) == 2

    def test_scorer_stats(self) -> None:
        report = EvalReport(
            results=(
                self._make_result(0.3),
                self._make_result(0.5),
                self._make_result(0.7),
                self._make_result(0.9),
            )
        )
        stats = report.scorer_stats("s")
        assert stats["min"] == 0.3
        assert stats["max"] == 0.9
        assert abs(stats["mean"] - 0.6) < 0.01

    def test_scorer_stats_missing(self) -> None:
        report = EvalReport(results=())
        assert report.scorer_stats("nope") == {}

    def test_empty_report(self) -> None:
        report = EvalReport(results=())
        assert report.total == 0
        assert report.pass_rate == 0.0
        assert report.mean_score == 0.0


# ---------------------------------------------------------------------------
# Scorer protocol
# ---------------------------------------------------------------------------


class TestScorerProtocol:
    def test_protocol_is_runtime_checkable(self) -> None:
        class FakeScorer:
            @property
            def name(self) -> str:
                return "fake"

            async def score(self, case: EvalCase, output: str) -> ScorerResult:
                return ScorerResult(score=1.0, reason="ok")

        assert isinstance(FakeScorer(), Scorer)
