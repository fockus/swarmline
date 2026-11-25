"""Tests for InMemoryProviderComparison.

TDD: written BEFORE implementation.
Covers: winner selection, tie handling, empty results, single provider.
"""

from __future__ import annotations

import pytest
from swarmline.eval.coding_protocols import ProviderComparisonPort
from swarmline.eval.coding_types import (
    CodingOutcome,
    ComparisonReport,
    GoldenTask,
    ProviderConfig,
    ProviderResult,
    TaskCategory,
)
from swarmline.eval.provider_comparison import InMemoryProviderComparison


def _make_task(task_id: str = "gt-1") -> GoldenTask:
    return GoldenTask(
        task_id=task_id,
        category=TaskCategory.BUGFIX,
        name="Test task",
        description="A test task",
        setup_files={},
        expected_outcomes=("tests pass",),
        tags=(),
    )


def _make_provider_result(
    provider_id: str,
    tests_passed: bool = True,
    lint_clean: bool = True,
    mypy_clean: bool = True,
    diff_quality: float = 0.8,
    behavioral_pass: bool = True,
    latency_ms: float = 100.0,
    task_id: str = "gt-1",
) -> ProviderResult:
    cfg = ProviderConfig(
        provider_id, f"Provider-{provider_id}", f"model-{provider_id}", {}
    )
    outcome = CodingOutcome(
        task_id=task_id,
        tests_passed=tests_passed,
        lint_clean=lint_clean,
        mypy_clean=mypy_clean,
        diff_quality=diff_quality,
        behavioral_pass=behavioral_pass,
        details={},
    )
    return ProviderResult(provider=cfg, outcome=outcome, latency_ms=latency_ms)


class TestInMemoryProviderComparisonProtocol:
    def test_implements_protocol(self) -> None:
        comp = InMemoryProviderComparison()
        assert isinstance(comp, ProviderComparisonPort)


class TestCompareWinnerSelection:
    """Winner = highest mean score across all boolean + float dimensions."""

    def test_single_provider_is_winner(self) -> None:
        comp = InMemoryProviderComparison()
        task = _make_task()
        pr = _make_provider_result("p1", diff_quality=0.9)
        report = comp.compare(task, (pr,))
        assert isinstance(report, ComparisonReport)
        assert report.winner_id == "p1"
        assert report.task == task
        assert len(report.results) == 1

    def test_higher_score_provider_wins(self) -> None:
        comp = InMemoryProviderComparison()
        task = _make_task()
        pr1 = _make_provider_result("p1", diff_quality=0.6)
        pr2 = _make_provider_result("p2", diff_quality=0.9)
        report = comp.compare(task, (pr1, pr2))
        assert report.winner_id == "p2"

    def test_boolean_dimensions_affect_score(self) -> None:
        comp = InMemoryProviderComparison()
        task = _make_task()
        pr1 = _make_provider_result(
            "p1",
            tests_passed=False,
            lint_clean=False,
            mypy_clean=False,
            diff_quality=1.0,
            behavioral_pass=False,
        )
        pr2 = _make_provider_result(
            "p2",
            tests_passed=True,
            lint_clean=True,
            mypy_clean=True,
            diff_quality=0.5,
            behavioral_pass=True,
        )
        report = comp.compare(task, (pr1, pr2))
        assert report.winner_id == "p2"

    def test_three_providers_best_wins(self) -> None:
        comp = InMemoryProviderComparison()
        task = _make_task()
        pr1 = _make_provider_result("p1", diff_quality=0.3)
        pr2 = _make_provider_result("p2", diff_quality=0.9)
        pr3 = _make_provider_result("p3", diff_quality=0.6)
        report = comp.compare(task, (pr1, pr2, pr3))
        assert report.winner_id == "p2"
        assert len(report.results) == 3


class TestCompareTieHandling:
    def test_tie_produces_no_winner(self) -> None:
        comp = InMemoryProviderComparison()
        task = _make_task()
        pr1 = _make_provider_result("p1", diff_quality=0.8)
        pr2 = _make_provider_result("p2", diff_quality=0.8)
        report = comp.compare(task, (pr1, pr2))
        assert report.winner_id is None

    def test_tie_among_three_no_winner(self) -> None:
        comp = InMemoryProviderComparison()
        task = _make_task()
        pr1 = _make_provider_result("p1", diff_quality=0.7)
        pr2 = _make_provider_result("p2", diff_quality=0.7)
        pr3 = _make_provider_result("p3", diff_quality=0.7)
        report = comp.compare(task, (pr1, pr2, pr3))
        assert report.winner_id is None


class TestCompareEmptyResults:
    def test_empty_results_no_winner(self) -> None:
        comp = InMemoryProviderComparison()
        task = _make_task()
        report = comp.compare(task, ())
        assert report.winner_id is None
        assert report.results == ()
        assert report.task == task


class TestCompareReportStructure:
    def test_report_preserves_all_results(self) -> None:
        comp = InMemoryProviderComparison()
        task = _make_task()
        pr1 = _make_provider_result("p1", diff_quality=0.5)
        pr2 = _make_provider_result("p2", diff_quality=0.9)
        report = comp.compare(task, (pr1, pr2))
        assert report.results == (pr1, pr2)

    @pytest.mark.parametrize(
        ("q1", "q2", "expected_winner"),
        [
            (0.1, 0.9, "p2"),
            (0.9, 0.1, "p1"),
            (0.5, 0.5, None),
        ],
    )
    def test_parametrized_quality_comparison(
        self, q1: float, q2: float, expected_winner: str | None
    ) -> None:
        comp = InMemoryProviderComparison()
        task = _make_task()
        pr1 = _make_provider_result("p1", diff_quality=q1)
        pr2 = _make_provider_result("p2", diff_quality=q2)
        report = comp.compare(task, (pr1, pr2))
        assert report.winner_id == expected_winner
