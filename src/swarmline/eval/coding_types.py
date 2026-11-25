"""Coding evaluation types — frozen dataclasses for agent code quality assessment."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class TaskCategory(Enum):
    """Category of a coding evaluation task."""

    BUGFIX = "bugfix"
    REFACTOR = "refactor"
    TEST_WRITING = "test_writing"
    MIGRATION = "migration"
    REVIEW = "review"


@dataclass(frozen=True)
class GoldenTask:
    """A golden reference task for evaluating coding agent quality."""

    task_id: str
    category: TaskCategory
    name: str
    description: str
    setup_files: dict[str, str]
    expected_outcomes: tuple[str, ...]
    tags: tuple[str, ...]


@dataclass(frozen=True)
class CodingOutcome:
    """Result of a coding agent's attempt at a task."""

    task_id: str
    tests_passed: bool
    lint_clean: bool
    mypy_clean: bool
    diff_quality: float  # 0.0–1.0
    behavioral_pass: bool
    details: dict[str, Any]


@dataclass(frozen=True)
class ProviderConfig:
    """Configuration for an LLM provider under evaluation."""

    provider_id: str
    name: str
    model: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ProviderResult:
    """Result from a specific provider on a specific task."""

    provider: ProviderConfig
    outcome: CodingOutcome
    latency_ms: float


@dataclass(frozen=True)
class ComparisonReport:
    """Report comparing multiple providers on a single task."""

    task: GoldenTask
    results: tuple[ProviderResult, ...]
    winner_id: str | None


@dataclass(frozen=True)
class RegressionGateResult:
    """Result of a regression check against baseline."""

    passed: bool
    current_score: float
    baseline_score: float
    threshold: float
    regressions: tuple[str, ...]
