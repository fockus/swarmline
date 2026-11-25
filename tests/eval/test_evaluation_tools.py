"""Tests for evaluation agent tools.

TDD: written BEFORE implementation.
Covers: 4 tools, JSON output, ToolSpec schema, DIP compliance (accepts protocols).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from swarmline.domain_types import ToolSpec
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
    ProviderResult,
    RegressionGateResult,
    TaskCategory,
)
from swarmline.eval.evaluation_tools import create_evaluation_tools

# ---------------------------------------------------------------------------
# Stub implementations for DIP compliance
# ---------------------------------------------------------------------------


class StubGoldenTaskSuite:
    def __init__(self) -> None:
        self._tasks: dict[str, GoldenTask] = {}

    def add(self, task: GoldenTask) -> None:
        self._tasks[task.task_id] = task

    def list_tasks(self) -> tuple[GoldenTask, ...]:
        return tuple(self._tasks.values())

    def get_task(self, task_id: str) -> GoldenTask | None:
        return self._tasks.get(task_id)

    def filter_by_category(self, category: TaskCategory) -> tuple[GoldenTask, ...]:
        return tuple(t for t in self._tasks.values() if t.category == category)


class StubCodingOutcomeScorer:
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
    def __init__(self) -> None:
        self._baseline: float = 0.0

    def check_regression(
        self, current_score: float, threshold: float
    ) -> RegressionGateResult:
        diff = self._baseline - current_score
        passed = diff <= threshold
        regressions: tuple[str, ...] = () if passed else ("score_degraded",)
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
# Helpers
# ---------------------------------------------------------------------------


def _make_task(
    task_id: str = "gt-1", category: TaskCategory = TaskCategory.BUGFIX
) -> GoldenTask:
    return GoldenTask(
        task_id=task_id,
        category=category,
        name=f"Task {task_id}",
        description=f"Desc {task_id}",
        setup_files={},
        expected_outcomes=("tests pass",),
        tags=(),
    )


def _build_tools() -> tuple[dict[str, ToolSpec], dict[str, Any]]:
    suite = StubGoldenTaskSuite()
    suite.add(_make_task("gt-1", TaskCategory.BUGFIX))
    suite.add(_make_task("gt-2", TaskCategory.REFACTOR))

    scorer = StubCodingOutcomeScorer()
    comparison = StubProviderComparison()
    gate = StubRegressionGate()
    gate.update_baseline(0.8)

    return create_evaluation_tools(
        suite=suite,
        scorer=scorer,
        comparison=comparison,
        regression_gate=gate,
    )


# ---------------------------------------------------------------------------
# Tests: factory
# ---------------------------------------------------------------------------


class TestCreateEvaluationTools:
    def test_returns_specs_and_executors(self) -> None:
        specs, executors = _build_tools()
        assert isinstance(specs, dict)
        assert isinstance(executors, dict)

    def test_four_tools_created(self) -> None:
        specs, executors = _build_tools()
        expected = {
            "list_golden_tasks",
            "run_evaluation",
            "compare_providers",
            "check_regression",
        }
        assert set(specs.keys()) == expected
        assert set(executors.keys()) == expected

    def test_all_specs_are_toolspec(self) -> None:
        specs, _ = _build_tools()
        for spec in specs.values():
            assert isinstance(spec, ToolSpec)

    def test_accepts_protocol_types(self) -> None:
        """DIP compliance: factory accepts protocols, not concrete implementations."""
        suite = StubGoldenTaskSuite()
        scorer = StubCodingOutcomeScorer()
        comparison = StubProviderComparison()
        gate = StubRegressionGate()

        assert isinstance(suite, GoldenTaskSuitePort)
        assert isinstance(scorer, CodingOutcomeScorerPort)
        assert isinstance(comparison, ProviderComparisonPort)
        assert isinstance(gate, RegressionGatePort)

        specs, executors = create_evaluation_tools(
            suite=suite,
            scorer=scorer,
            comparison=comparison,
            regression_gate=gate,
        )
        assert len(specs) == 4


# ---------------------------------------------------------------------------
# Tests: list_golden_tasks
# ---------------------------------------------------------------------------


class TestListGoldenTasksTool:
    def test_lists_all_tasks(self) -> None:
        _, executors = _build_tools()
        result = json.loads(executors["list_golden_tasks"]({}))
        assert result["count"] == 2
        assert len(result["tasks"]) == 2

    def test_filter_by_category(self) -> None:
        _, executors = _build_tools()
        result = json.loads(executors["list_golden_tasks"]({"category": "bugfix"}))
        assert result["count"] == 1
        assert result["tasks"][0]["task_id"] == "gt-1"

    def test_filter_invalid_category_returns_error(self) -> None:
        _, executors = _build_tools()
        result = json.loads(executors["list_golden_tasks"]({"category": "invalid"}))
        assert result["status"] == "error"

    def test_returns_json_string(self) -> None:
        _, executors = _build_tools()
        raw = executors["list_golden_tasks"]({})
        assert isinstance(raw, str)
        json.loads(raw)  # must be valid JSON


# ---------------------------------------------------------------------------
# Tests: run_evaluation
# ---------------------------------------------------------------------------


class TestRunEvaluationTool:
    def test_scores_valid_outcome(self) -> None:
        _, executors = _build_tools()
        result = json.loads(
            executors["run_evaluation"](
                {
                    "task_id": "gt-1",
                    "tests_passed": True,
                    "lint_clean": True,
                    "mypy_clean": True,
                    "diff_quality": 0.9,
                    "behavioral_pass": True,
                }
            )
        )
        assert result["task_id"] == "gt-1"
        assert result["tests_passed"] is True
        assert result["diff_quality"] == 0.9

    def test_unknown_task_returns_error(self) -> None:
        _, executors = _build_tools()
        result = json.loads(
            executors["run_evaluation"](
                {
                    "task_id": "nonexistent",
                    "tests_passed": True,
                    "lint_clean": True,
                    "mypy_clean": True,
                    "diff_quality": 0.5,
                    "behavioral_pass": True,
                }
            )
        )
        assert result["status"] == "error"

    def test_missing_task_id_returns_error(self) -> None:
        _, executors = _build_tools()
        result = json.loads(
            executors["run_evaluation"](
                {
                    "tests_passed": True,
                    "lint_clean": True,
                    "mypy_clean": True,
                    "diff_quality": 0.5,
                    "behavioral_pass": True,
                }
            )
        )
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Tests: compare_providers
# ---------------------------------------------------------------------------


class TestCompareProvidersTool:
    def test_compare_two_providers(self) -> None:
        _, executors = _build_tools()
        result = json.loads(
            executors["compare_providers"](
                {
                    "task_id": "gt-1",
                    "results": [
                        {
                            "provider_id": "p1",
                            "provider_name": "A",
                            "model": "m1",
                            "tests_passed": True,
                            "lint_clean": True,
                            "mypy_clean": True,
                            "diff_quality": 0.6,
                            "behavioral_pass": True,
                            "latency_ms": 100.0,
                        },
                        {
                            "provider_id": "p2",
                            "provider_name": "B",
                            "model": "m2",
                            "tests_passed": True,
                            "lint_clean": True,
                            "mypy_clean": True,
                            "diff_quality": 0.9,
                            "behavioral_pass": True,
                            "latency_ms": 200.0,
                        },
                    ],
                }
            )
        )
        assert result["winner_id"] == "p2"
        assert result["task_id"] == "gt-1"
        assert len(result["results"]) == 2

    def test_unknown_task_returns_error(self) -> None:
        _, executors = _build_tools()
        result = json.loads(
            executors["compare_providers"](
                {
                    "task_id": "nonexistent",
                    "results": [],
                }
            )
        )
        assert result["status"] == "error"

    def test_missing_task_id_returns_error(self) -> None:
        _, executors = _build_tools()
        result = json.loads(executors["compare_providers"]({"results": []}))
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Tests: check_regression
# ---------------------------------------------------------------------------


class TestCheckRegressionTool:
    def test_passes_when_no_degradation(self) -> None:
        _, executors = _build_tools()
        result = json.loads(
            executors["check_regression"](
                {
                    "current_score": 0.85,
                }
            )
        )
        assert result["passed"] is True
        assert result["baseline_score"] == 0.8

    def test_fails_when_degraded(self) -> None:
        _, executors = _build_tools()
        result = json.loads(
            executors["check_regression"](
                {
                    "current_score": 0.5,
                }
            )
        )
        assert result["passed"] is False

    def test_custom_threshold(self) -> None:
        _, executors = _build_tools()
        result = json.loads(
            executors["check_regression"](
                {
                    "current_score": 0.5,
                    "threshold": 0.5,
                }
            )
        )
        assert result["passed"] is True

    def test_missing_current_score_returns_error(self) -> None:
        _, executors = _build_tools()
        result = json.loads(executors["check_regression"]({}))
        assert result["status"] == "error"

    @pytest.mark.parametrize(
        ("current", "threshold", "expected_passed"),
        [
            (0.85, 0.1, True),
            (0.5, 0.1, False),
            (0.75, 0.1, True),
        ],
    )
    def test_parametrized_regression_check(
        self, current: float, threshold: float, expected_passed: bool
    ) -> None:
        _, executors = _build_tools()
        result = json.loads(
            executors["check_regression"](
                {
                    "current_score": current,
                    "threshold": threshold,
                }
            )
        )
        assert result["passed"] is expected_passed
