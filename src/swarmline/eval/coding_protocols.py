"""Coding evaluation protocols — ISP-compliant ports for eval subsystem."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from swarmline.eval.coding_types import (
    CodingOutcome,
    ComparisonReport,
    GoldenTask,
    ProviderResult,
    RegressionGateResult,
    TaskCategory,
)


@runtime_checkable
class GoldenTaskSuitePort(Protocol):
    """Port for managing golden reference tasks (ISP: 3 methods)."""

    def list_tasks(self) -> tuple[GoldenTask, ...]: ...

    def get_task(self, task_id: str) -> GoldenTask | None: ...

    def filter_by_category(self, category: TaskCategory) -> tuple[GoldenTask, ...]: ...


@runtime_checkable
class CodingOutcomeScorerPort(Protocol):
    """Port for scoring coding outcomes (ISP: 1 method)."""

    def score_outcome(
        self,
        task: GoldenTask,
        tests_passed: bool,
        lint_clean: bool,
        mypy_clean: bool,
        diff_quality: float,
        behavioral_pass: bool,
    ) -> CodingOutcome: ...


@runtime_checkable
class ProviderComparisonPort(Protocol):
    """Port for comparing provider results (ISP: 1 method)."""

    def compare(
        self,
        task: GoldenTask,
        results: tuple[ProviderResult, ...],
    ) -> ComparisonReport: ...


@runtime_checkable
class RegressionGatePort(Protocol):
    """Port for regression detection (ISP: 2 methods)."""

    def check_regression(
        self,
        current_score: float,
        threshold: float,
    ) -> RegressionGateResult: ...

    def update_baseline(self, score: float) -> None: ...
