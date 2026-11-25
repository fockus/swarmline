"""Tests for coding evaluation types — frozen dataclasses."""

from __future__ import annotations

import pytest

from swarmline.eval.coding_types import (
    CodingOutcome,
    ComparisonReport,
    GoldenTask,
    ProviderConfig,
    ProviderResult,
    RegressionGateResult,
    TaskCategory,
)


class TestTaskCategory:
    def test_has_all_categories(self) -> None:
        expected = {"BUGFIX", "REFACTOR", "TEST_WRITING", "MIGRATION", "REVIEW"}
        actual = {c.name for c in TaskCategory}
        assert actual == expected

    @pytest.mark.parametrize(
        "member",
        ["BUGFIX", "REFACTOR", "TEST_WRITING", "MIGRATION", "REVIEW"],
    )
    def test_category_accessible_by_name(self, member: str) -> None:
        assert TaskCategory[member].name == member


class TestGoldenTask:
    def test_frozen(self) -> None:
        task = GoldenTask(
            task_id="gt-1",
            category=TaskCategory.BUGFIX,
            name="Fix null check",
            description="Add null check to parser",
            setup_files={"main.py": "code"},
            expected_outcomes=("tests pass",),
            tags=("python",),
        )
        with pytest.raises(AttributeError):
            task.name = "changed"  # type: ignore[misc]

    def test_all_fields_present(self) -> None:
        task = GoldenTask(
            task_id="gt-1",
            category=TaskCategory.REFACTOR,
            name="Extract method",
            description="Extract duplicated logic",
            setup_files={"a.py": "x", "b.py": "y"},
            expected_outcomes=("lint clean", "tests pass"),
            tags=("refactor",),
        )
        assert task.task_id == "gt-1"
        assert task.category == TaskCategory.REFACTOR
        assert task.name == "Extract method"
        assert task.description == "Extract duplicated logic"
        assert task.setup_files == {"a.py": "x", "b.py": "y"}
        assert task.expected_outcomes == ("lint clean", "tests pass")
        assert task.tags == ("refactor",)

    def test_defaults(self) -> None:
        task = GoldenTask(
            task_id="gt-2",
            category=TaskCategory.BUGFIX,
            name="n",
            description="d",
            setup_files={},
            expected_outcomes=(),
            tags=(),
        )
        assert task.setup_files == {}
        assert task.expected_outcomes == ()
        assert task.tags == ()


class TestCodingOutcome:
    def test_frozen(self) -> None:
        outcome = CodingOutcome(
            task_id="gt-1",
            tests_passed=True,
            lint_clean=True,
            mypy_clean=True,
            diff_quality=0.85,
            behavioral_pass=True,
            details={},
        )
        with pytest.raises(AttributeError):
            outcome.tests_passed = False  # type: ignore[misc]

    def test_all_fields(self) -> None:
        outcome = CodingOutcome(
            task_id="gt-1",
            tests_passed=True,
            lint_clean=False,
            mypy_clean=True,
            diff_quality=0.7,
            behavioral_pass=False,
            details={"note": "lint warning"},
        )
        assert outcome.task_id == "gt-1"
        assert outcome.tests_passed is True
        assert outcome.lint_clean is False
        assert outcome.mypy_clean is True
        assert outcome.diff_quality == 0.7
        assert outcome.behavioral_pass is False
        assert outcome.details == {"note": "lint warning"}


class TestProviderConfig:
    def test_frozen(self) -> None:
        cfg = ProviderConfig(
            provider_id="p1",
            name="Claude",
            model="sonnet",
            parameters={},
        )
        with pytest.raises(AttributeError):
            cfg.name = "other"  # type: ignore[misc]

    def test_all_fields(self) -> None:
        cfg = ProviderConfig(
            provider_id="p1",
            name="Claude",
            model="opus",
            parameters={"temperature": 0.0},
        )
        assert cfg.provider_id == "p1"
        assert cfg.name == "Claude"
        assert cfg.model == "opus"
        assert cfg.parameters == {"temperature": 0.0}


class TestProviderResult:
    def test_frozen(self) -> None:
        cfg = ProviderConfig("p1", "Claude", "sonnet", {})
        outcome = CodingOutcome("gt-1", True, True, True, 1.0, True, {})
        result = ProviderResult(provider=cfg, outcome=outcome, latency_ms=150.0)
        with pytest.raises(AttributeError):
            result.latency_ms = 200.0  # type: ignore[misc]

    def test_all_fields(self) -> None:
        cfg = ProviderConfig("p1", "Claude", "sonnet", {})
        outcome = CodingOutcome("gt-1", True, True, True, 0.9, True, {})
        result = ProviderResult(provider=cfg, outcome=outcome, latency_ms=100.5)
        assert result.provider == cfg
        assert result.outcome == outcome
        assert result.latency_ms == 100.5


class TestComparisonReport:
    def test_frozen(self) -> None:
        task = GoldenTask("gt-1", TaskCategory.BUGFIX, "n", "d", {}, (), ())
        report = ComparisonReport(task=task, results=(), winner_id=None)
        with pytest.raises(AttributeError):
            report.winner_id = "x"  # type: ignore[misc]

    def test_all_fields(self) -> None:
        task = GoldenTask("gt-1", TaskCategory.BUGFIX, "n", "d", {}, (), ())
        cfg = ProviderConfig("p1", "Claude", "sonnet", {})
        outcome = CodingOutcome("gt-1", True, True, True, 1.0, True, {})
        pr = ProviderResult(cfg, outcome, 100.0)
        report = ComparisonReport(task=task, results=(pr,), winner_id="p1")
        assert report.task == task
        assert report.results == (pr,)
        assert report.winner_id == "p1"

    def test_winner_can_be_none(self) -> None:
        task = GoldenTask("gt-1", TaskCategory.BUGFIX, "n", "d", {}, (), ())
        report = ComparisonReport(task=task, results=(), winner_id=None)
        assert report.winner_id is None


class TestRegressionGateResult:
    def test_frozen(self) -> None:
        r = RegressionGateResult(
            passed=True,
            current_score=0.9,
            baseline_score=0.85,
            threshold=0.05,
            regressions=(),
        )
        with pytest.raises(AttributeError):
            r.passed = False  # type: ignore[misc]

    def test_all_fields(self) -> None:
        r = RegressionGateResult(
            passed=False,
            current_score=0.7,
            baseline_score=0.9,
            threshold=0.1,
            regressions=("tests_passed", "lint_clean"),
        )
        assert r.passed is False
        assert r.current_score == 0.7
        assert r.baseline_score == 0.9
        assert r.threshold == 0.1
        assert r.regressions == ("tests_passed", "lint_clean")
