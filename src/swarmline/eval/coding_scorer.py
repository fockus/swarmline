"""Coding outcome scorer — pure scoring logic for coding evaluation."""

from __future__ import annotations

from swarmline.eval.coding_types import CodingOutcome, GoldenTask


class CodingOutcomeScorer:
    """Score coding agent outcomes against golden task expectations.

    Pure logic — no subprocess calls. Outcomes are provided as input.
    Clamps diff_quality to [0.0, 1.0].
    """

    def score_outcome(
        self,
        task: GoldenTask,
        tests_passed: bool,
        lint_clean: bool,
        mypy_clean: bool,
        diff_quality: float,
        behavioral_pass: bool,
    ) -> CodingOutcome:
        clamped_quality = max(0.0, min(1.0, diff_quality))
        return CodingOutcome(
            task_id=task.task_id,
            tests_passed=tests_passed,
            lint_clean=lint_clean,
            mypy_clean=mypy_clean,
            diff_quality=clamped_quality,
            behavioral_pass=behavioral_pass,
            details={
                "expected_outcomes": list(task.expected_outcomes),
                "category": task.category.value,
            },
        )
