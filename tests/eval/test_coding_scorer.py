"""Tests for CodingOutcomeScorer — pure scoring logic."""

from __future__ import annotations

import pytest

from swarmline.eval.coding_protocols import CodingOutcomeScorerPort
from swarmline.eval.coding_scorer import CodingOutcomeScorer
from swarmline.eval.coding_types import GoldenTask, TaskCategory


def _task(task_id: str = "gt-1") -> GoldenTask:
    return GoldenTask(
        task_id=task_id,
        category=TaskCategory.BUGFIX,
        name="Test task",
        description="A task",
        setup_files={},
        expected_outcomes=("tests pass", "lint clean"),
        tags=(),
    )


class TestCodingOutcomeScorerProtocol:
    def test_implements_port(self) -> None:
        scorer = CodingOutcomeScorer()
        assert isinstance(scorer, CodingOutcomeScorerPort)


class TestScoreOutcome:
    def test_all_passing_outcome(self) -> None:
        scorer = CodingOutcomeScorer()
        outcome = scorer.score_outcome(
            task=_task(),
            tests_passed=True,
            lint_clean=True,
            mypy_clean=True,
            diff_quality=0.95,
            behavioral_pass=True,
        )
        assert outcome.task_id == "gt-1"
        assert outcome.tests_passed is True
        assert outcome.lint_clean is True
        assert outcome.mypy_clean is True
        assert outcome.diff_quality == 0.95
        assert outcome.behavioral_pass is True

    def test_all_failing_outcome(self) -> None:
        scorer = CodingOutcomeScorer()
        outcome = scorer.score_outcome(
            task=_task(),
            tests_passed=False,
            lint_clean=False,
            mypy_clean=False,
            diff_quality=0.0,
            behavioral_pass=False,
        )
        assert outcome.tests_passed is False
        assert outcome.lint_clean is False
        assert outcome.mypy_clean is False
        assert outcome.diff_quality == 0.0
        assert outcome.behavioral_pass is False

    def test_preserves_task_id(self) -> None:
        scorer = CodingOutcomeScorer()
        outcome = scorer.score_outcome(
            task=_task("custom-id"),
            tests_passed=True,
            lint_clean=True,
            mypy_clean=True,
            diff_quality=0.5,
            behavioral_pass=True,
        )
        assert outcome.task_id == "custom-id"

    @pytest.mark.parametrize(
        ("tests", "lint", "mypy", "quality", "behavioral"),
        [
            (True, False, True, 0.8, True),
            (False, True, False, 0.3, True),
            (True, True, True, 0.0, False),
        ],
    )
    def test_mixed_dimensions(
        self,
        tests: bool,
        lint: bool,
        mypy: bool,
        quality: float,
        behavioral: bool,
    ) -> None:
        scorer = CodingOutcomeScorer()
        outcome = scorer.score_outcome(_task(), tests, lint, mypy, quality, behavioral)
        assert outcome.tests_passed == tests
        assert outcome.lint_clean == lint
        assert outcome.mypy_clean == mypy
        assert outcome.diff_quality == quality
        assert outcome.behavioral_pass == behavioral

    def test_diff_quality_clamped_to_valid_range(self) -> None:
        scorer = CodingOutcomeScorer()
        outcome = scorer.score_outcome(_task(), True, True, True, 1.5, True)
        assert outcome.diff_quality <= 1.0

        outcome_low = scorer.score_outcome(_task(), True, True, True, -0.5, True)
        assert outcome_low.diff_quality >= 0.0

    def test_outcome_details_populated(self) -> None:
        scorer = CodingOutcomeScorer()
        task = _task()
        outcome = scorer.score_outcome(task, True, True, True, 0.9, True)
        assert isinstance(outcome.details, dict)
