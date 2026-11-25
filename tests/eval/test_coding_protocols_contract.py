"""Contract tests for coding evaluation protocols.

These tests verify that ANY correct implementation of the protocols
satisfies the expected behavior. Each protocol gets a concrete stub
implementation that fulfills the contract.
"""

from __future__ import annotations

import pytest

from swarmline.eval.coding_protocols import (
    CodingOutcomeScorerPort,
    GoldenTaskSuitePort,
    ProviderComparisonPort,
    RegressionGatePort,
)
from swarmline.eval.coding_types import (
    CodingOutcome,
    ComparisonReport,
    GoldenTask,
    ProviderConfig,
    ProviderResult,
    RegressionGateResult,
    TaskCategory,
)


# ---------------------------------------------------------------------------
# Stub implementations for contract testing
# ---------------------------------------------------------------------------


class StubGoldenTaskSuite:
    """Minimal correct implementation of GoldenTaskSuitePort."""

    def __init__(self) -> None:
        self._tasks: dict[str, GoldenTask] = {}

    def register_task(self, task: GoldenTask) -> None:
        self._tasks[task.task_id] = task

    def list_tasks(self) -> tuple[GoldenTask, ...]:
        return tuple(self._tasks.values())

    def get_task(self, task_id: str) -> GoldenTask | None:
        return self._tasks.get(task_id)

    def filter_by_category(self, category: TaskCategory) -> tuple[GoldenTask, ...]:
        return tuple(t for t in self._tasks.values() if t.category == category)


class StubCodingOutcomeScorer:
    """Minimal correct implementation of CodingOutcomeScorerPort."""

    def score_outcome(
        self,
        task: GoldenTask,
        tests_passed: bool,
        lint_clean: bool,
        mypy_clean: bool,
        diff_quality: float,
        behavioral_pass: bool,
    ) -> CodingOutcome:
        return CodingOutcome(
            task_id=task.task_id,
            tests_passed=tests_passed,
            lint_clean=lint_clean,
            mypy_clean=mypy_clean,
            diff_quality=diff_quality,
            behavioral_pass=behavioral_pass,
            details={},
        )


class StubProviderComparison:
    """Minimal correct implementation of ProviderComparisonPort."""

    def compare(
        self,
        task: GoldenTask,
        results: tuple[ProviderResult, ...],
    ) -> ComparisonReport:
        winner_id: str | None = None
        if results:
            best = max(results, key=lambda r: r.outcome.diff_quality)
            winner_id = best.provider.provider_id
        return ComparisonReport(task=task, results=results, winner_id=winner_id)


class StubRegressionGate:
    """Minimal correct implementation of RegressionGatePort."""

    def __init__(self) -> None:
        self._baseline: float = 0.0

    def check_regression(
        self,
        current_score: float,
        threshold: float,
    ) -> RegressionGateResult:
        diff = self._baseline - current_score
        passed = diff <= threshold
        regressions: tuple[str, ...] = ()
        if not passed:
            regressions = ("score_degraded",)
        return RegressionGateResult(
            passed=passed,
            current_score=current_score,
            baseline_score=self._baseline,
            threshold=threshold,
            regressions=regressions,
        )

    def update_baseline(self, score: float) -> None:
        self._baseline = score


# ---------------------------------------------------------------------------
# Contract: runtime_checkable
# ---------------------------------------------------------------------------


class TestProtocolsRuntimeCheckable:
    def test_golden_task_suite_is_instance(self) -> None:
        suite = StubGoldenTaskSuite()
        assert isinstance(suite, GoldenTaskSuitePort)

    def test_coding_outcome_scorer_is_instance(self) -> None:
        scorer = StubCodingOutcomeScorer()
        assert isinstance(scorer, CodingOutcomeScorerPort)

    def test_provider_comparison_is_instance(self) -> None:
        comp = StubProviderComparison()
        assert isinstance(comp, ProviderComparisonPort)

    def test_regression_gate_is_instance(self) -> None:
        gate = StubRegressionGate()
        assert isinstance(gate, RegressionGatePort)


# ---------------------------------------------------------------------------
# Contract: GoldenTaskSuitePort
# ---------------------------------------------------------------------------


def _make_task(
    task_id: str, category: TaskCategory = TaskCategory.BUGFIX
) -> GoldenTask:
    return GoldenTask(
        task_id=task_id,
        category=category,
        name=f"Task {task_id}",
        description=f"Description for {task_id}",
        setup_files={},
        expected_outcomes=("tests pass",),
        tags=(),
    )


class TestGoldenTaskSuiteContract:
    def test_list_tasks_empty_initially(self) -> None:
        suite = StubGoldenTaskSuite()
        assert suite.list_tasks() == ()

    def test_get_task_returns_none_for_unknown(self) -> None:
        suite = StubGoldenTaskSuite()
        assert suite.get_task("nonexistent") is None

    def test_register_and_list(self) -> None:
        suite = StubGoldenTaskSuite()
        t1 = _make_task("gt-1")
        t2 = _make_task("gt-2", TaskCategory.REFACTOR)
        suite.register_task(t1)
        suite.register_task(t2)
        tasks = suite.list_tasks()
        assert len(tasks) == 2
        assert t1 in tasks
        assert t2 in tasks

    def test_get_task_returns_registered(self) -> None:
        suite = StubGoldenTaskSuite()
        t = _make_task("gt-1")
        suite.register_task(t)
        assert suite.get_task("gt-1") == t

    def test_filter_by_category(self) -> None:
        suite = StubGoldenTaskSuite()
        t_bug = _make_task("gt-1", TaskCategory.BUGFIX)
        t_ref = _make_task("gt-2", TaskCategory.REFACTOR)
        t_bug2 = _make_task("gt-3", TaskCategory.BUGFIX)
        suite.register_task(t_bug)
        suite.register_task(t_ref)
        suite.register_task(t_bug2)
        filtered = suite.filter_by_category(TaskCategory.BUGFIX)
        assert len(filtered) == 2
        assert t_bug in filtered
        assert t_bug2 in filtered

    def test_filter_by_category_returns_empty_for_no_match(self) -> None:
        suite = StubGoldenTaskSuite()
        suite.register_task(_make_task("gt-1", TaskCategory.BUGFIX))
        assert suite.filter_by_category(TaskCategory.MIGRATION) == ()


# ---------------------------------------------------------------------------
# Contract: CodingOutcomeScorerPort
# ---------------------------------------------------------------------------


class TestCodingOutcomeScorerContract:
    def test_score_outcome_returns_coding_outcome(self) -> None:
        scorer = StubCodingOutcomeScorer()
        task = _make_task("gt-1")
        outcome = scorer.score_outcome(
            task=task,
            tests_passed=True,
            lint_clean=True,
            mypy_clean=True,
            diff_quality=0.9,
            behavioral_pass=True,
        )
        assert isinstance(outcome, CodingOutcome)
        assert outcome.task_id == "gt-1"

    def test_score_outcome_preserves_all_dimensions(self) -> None:
        scorer = StubCodingOutcomeScorer()
        task = _make_task("gt-2")
        outcome = scorer.score_outcome(
            task=task,
            tests_passed=False,
            lint_clean=True,
            mypy_clean=False,
            diff_quality=0.5,
            behavioral_pass=True,
        )
        assert outcome.tests_passed is False
        assert outcome.lint_clean is True
        assert outcome.mypy_clean is False
        assert outcome.diff_quality == 0.5
        assert outcome.behavioral_pass is True

    @pytest.mark.parametrize("quality", [0.0, 0.5, 1.0])
    def test_score_outcome_diff_quality_range(self, quality: float) -> None:
        scorer = StubCodingOutcomeScorer()
        task = _make_task("gt-1")
        outcome = scorer.score_outcome(task, True, True, True, quality, True)
        assert 0.0 <= outcome.diff_quality <= 1.0


# ---------------------------------------------------------------------------
# Contract: ProviderComparisonPort
# ---------------------------------------------------------------------------


class TestProviderComparisonContract:
    def test_compare_returns_report(self) -> None:
        comp = StubProviderComparison()
        task = _make_task("gt-1")
        cfg = ProviderConfig("p1", "Claude", "sonnet", {})
        outcome = CodingOutcome("gt-1", True, True, True, 0.9, True, {})
        pr = ProviderResult(cfg, outcome, 100.0)
        report = comp.compare(task, (pr,))
        assert isinstance(report, ComparisonReport)
        assert report.task == task

    def test_compare_selects_winner(self) -> None:
        comp = StubProviderComparison()
        task = _make_task("gt-1")
        cfg1 = ProviderConfig("p1", "A", "m1", {})
        cfg2 = ProviderConfig("p2", "B", "m2", {})
        o1 = CodingOutcome("gt-1", True, True, True, 0.7, True, {})
        o2 = CodingOutcome("gt-1", True, True, True, 0.9, True, {})
        pr1 = ProviderResult(cfg1, o1, 100.0)
        pr2 = ProviderResult(cfg2, o2, 100.0)
        report = comp.compare(task, (pr1, pr2))
        assert report.winner_id == "p2"

    def test_compare_empty_results(self) -> None:
        comp = StubProviderComparison()
        task = _make_task("gt-1")
        report = comp.compare(task, ())
        assert report.winner_id is None
        assert report.results == ()


# ---------------------------------------------------------------------------
# Contract: RegressionGatePort
# ---------------------------------------------------------------------------


class TestRegressionGateContract:
    def test_check_regression_passes_when_no_degradation(self) -> None:
        gate = StubRegressionGate()
        gate.update_baseline(0.8)
        result = gate.check_regression(current_score=0.85, threshold=0.1)
        assert isinstance(result, RegressionGateResult)
        assert result.passed is True
        assert result.regressions == ()

    def test_check_regression_fails_when_degraded(self) -> None:
        gate = StubRegressionGate()
        gate.update_baseline(0.9)
        result = gate.check_regression(current_score=0.5, threshold=0.1)
        assert result.passed is False
        assert len(result.regressions) > 0

    def test_update_baseline_changes_reference(self) -> None:
        gate = StubRegressionGate()
        gate.update_baseline(0.5)
        r1 = gate.check_regression(0.45, 0.1)
        assert r1.passed is True  # diff=0.05 <= 0.1

        gate.update_baseline(0.9)
        r2 = gate.check_regression(0.45, 0.1)
        assert r2.passed is False  # diff=0.45 > 0.1

    def test_check_regression_reports_scores(self) -> None:
        gate = StubRegressionGate()
        gate.update_baseline(0.85)
        result = gate.check_regression(0.7, 0.05)
        assert result.current_score == 0.7
        assert result.baseline_score == 0.85
        assert result.threshold == 0.05
