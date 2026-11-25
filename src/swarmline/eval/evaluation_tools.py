"""Evaluation agent tools — 4 tools for coding quality assessment.

Factory accepts protocols (DIP), returns (specs, executors) matching the standard pattern.
All tools return JSON strings.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from swarmline.domain_types import ToolSpec
from swarmline.eval.coding_protocols import (
    CodingOutcomeScorerPort,
    GoldenTaskSuitePort,
    ProviderComparisonPort,
    RegressionGatePort,
)
from swarmline.eval.coding_types import (
    CodingOutcome,
    ProviderConfig,
    ProviderResult,
    TaskCategory,
)

# ---------------------------------------------------------------------------
# JSON Schemas
# ---------------------------------------------------------------------------

_LIST_GOLDEN_TASKS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "category": {
            "type": "string",
            "description": "Optional category filter: bugfix, refactor, test_writing, migration, review",
        },
    },
    "required": [],
}

_RUN_EVALUATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_id": {
            "type": "string",
            "description": "Golden task ID to evaluate against",
        },
        "tests_passed": {"type": "boolean", "description": "Whether tests passed"},
        "lint_clean": {"type": "boolean", "description": "Whether linting is clean"},
        "mypy_clean": {
            "type": "boolean",
            "description": "Whether mypy type check is clean",
        },
        "diff_quality": {"type": "number", "description": "Diff quality score 0.0-1.0"},
        "behavioral_pass": {
            "type": "boolean",
            "description": "Whether behavioral check passed",
        },
    },
    "required": [
        "task_id",
        "tests_passed",
        "lint_clean",
        "mypy_clean",
        "diff_quality",
        "behavioral_pass",
    ],
}

_COMPARE_PROVIDERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_id": {
            "type": "string",
            "description": "Golden task ID to compare against",
        },
        "results": {
            "type": "array",
            "description": "Array of provider result objects",
            "items": {
                "type": "object",
                "properties": {
                    "provider_id": {"type": "string"},
                    "provider_name": {"type": "string"},
                    "model": {"type": "string"},
                    "tests_passed": {"type": "boolean"},
                    "lint_clean": {"type": "boolean"},
                    "mypy_clean": {"type": "boolean"},
                    "diff_quality": {"type": "number"},
                    "behavioral_pass": {"type": "boolean"},
                    "latency_ms": {"type": "number"},
                },
                "required": [
                    "provider_id",
                    "provider_name",
                    "model",
                    "tests_passed",
                    "lint_clean",
                    "mypy_clean",
                    "diff_quality",
                    "behavioral_pass",
                    "latency_ms",
                ],
            },
        },
    },
    "required": ["task_id", "results"],
}

_CHECK_REGRESSION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "current_score": {
            "type": "number",
            "description": "Current aggregate score (0.0-1.0)",
        },
        "threshold": {
            "type": "number",
            "description": "Max allowed degradation (default 0.1)",
        },
    },
    "required": ["current_score"],
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _error_json(error_type: str, message: str) -> str:
    return json.dumps({"status": "error", "error_type": error_type, "message": message})


def _golden_task_to_dict(task: Any) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "category": task.category.value,
        "name": task.name,
        "description": task.description,
        "tags": list(task.tags),
    }


def _coding_outcome_to_dict(outcome: CodingOutcome) -> dict[str, Any]:
    return {
        "task_id": outcome.task_id,
        "tests_passed": outcome.tests_passed,
        "lint_clean": outcome.lint_clean,
        "mypy_clean": outcome.mypy_clean,
        "diff_quality": outcome.diff_quality,
        "behavioral_pass": outcome.behavioral_pass,
        "details": outcome.details,
    }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_evaluation_tools(
    *,
    suite: GoldenTaskSuitePort,
    scorer: CodingOutcomeScorerPort,
    comparison: ProviderComparisonPort,
    regression_gate: RegressionGatePort,
) -> tuple[dict[str, ToolSpec], dict[str, Callable[..., Any]]]:
    """Create 4 evaluation tools for agent use.

    Returns (specs dict, executors dict) matching the standard tools pattern.
    Accepts protocols (DIP), not concrete implementations.
    """
    specs: dict[str, ToolSpec] = {}
    executors: dict[str, Callable[..., Any]] = {}

    # 1. list_golden_tasks
    def _list_golden_tasks(args: dict[str, Any]) -> str:
        category_str = args.get("category")
        if category_str:
            try:
                category = TaskCategory(category_str)
            except ValueError:
                valid = ", ".join(c.value for c in TaskCategory)
                return _error_json(
                    "validation", f"Invalid category '{category_str}'. Valid: {valid}"
                )
            tasks = suite.filter_by_category(category)
        else:
            tasks = suite.list_tasks()

        return json.dumps(
            {
                "count": len(tasks),
                "tasks": [_golden_task_to_dict(t) for t in tasks],
            }
        )

    specs["list_golden_tasks"] = ToolSpec(
        name="list_golden_tasks",
        description="List golden evaluation tasks, optionally filtered by category",
        parameters=_LIST_GOLDEN_TASKS_SCHEMA,
    )
    executors["list_golden_tasks"] = _list_golden_tasks

    # 2. run_evaluation
    def _run_evaluation(args: dict[str, Any]) -> str:
        task_id = args.get("task_id", "")
        if not task_id:
            return _error_json("validation", "task_id is required")

        task = suite.get_task(task_id)
        if task is None:
            return _error_json("not_found", f"Task '{task_id}' not found")

        outcome = scorer.score_outcome(
            task=task,
            tests_passed=bool(args.get("tests_passed", False)),
            lint_clean=bool(args.get("lint_clean", False)),
            mypy_clean=bool(args.get("mypy_clean", False)),
            diff_quality=float(args.get("diff_quality", 0.0)),
            behavioral_pass=bool(args.get("behavioral_pass", False)),
        )

        return json.dumps(_coding_outcome_to_dict(outcome))

    specs["run_evaluation"] = ToolSpec(
        name="run_evaluation",
        description="Score a coding outcome against a golden task",
        parameters=_RUN_EVALUATION_SCHEMA,
    )
    executors["run_evaluation"] = _run_evaluation

    # 3. compare_providers
    def _compare_providers(args: dict[str, Any]) -> str:
        task_id = args.get("task_id", "")
        if not task_id:
            return _error_json("validation", "task_id is required")

        task = suite.get_task(task_id)
        if task is None:
            return _error_json("not_found", f"Task '{task_id}' not found")

        raw_results = args.get("results", [])
        provider_results: list[ProviderResult] = []
        for r in raw_results:
            try:
                cfg = ProviderConfig(
                    provider_id=r["provider_id"],
                    name=r["provider_name"],
                    model=r["model"],
                    parameters={},
                )
            except (KeyError, TypeError) as e:
                return _error_json(
                    "validation", f"Missing required field in result: {e}"
                )
            raw_dq = float(r.get("diff_quality", 0.0))
            outcome = CodingOutcome(
                task_id=task_id,
                tests_passed=bool(r.get("tests_passed", False)),
                lint_clean=bool(r.get("lint_clean", False)),
                mypy_clean=bool(r.get("mypy_clean", False)),
                diff_quality=max(0.0, min(1.0, raw_dq)),
                behavioral_pass=bool(r.get("behavioral_pass", False)),
                details={},
            )
            provider_results.append(
                ProviderResult(
                    provider=cfg,
                    outcome=outcome,
                    latency_ms=float(r.get("latency_ms", 0.0)),
                )
            )

        report = comparison.compare(task, tuple(provider_results))

        return json.dumps(
            {
                "task_id": task_id,
                "winner_id": report.winner_id,
                "results": [
                    {
                        "provider_id": pr.provider.provider_id,
                        "provider_name": pr.provider.name,
                        "model": pr.provider.model,
                        "latency_ms": pr.latency_ms,
                        "tests_passed": pr.outcome.tests_passed,
                        "diff_quality": pr.outcome.diff_quality,
                    }
                    for pr in report.results
                ],
            }
        )

    specs["compare_providers"] = ToolSpec(
        name="compare_providers",
        description="Compare multiple providers on a single golden task",
        parameters=_COMPARE_PROVIDERS_SCHEMA,
    )
    executors["compare_providers"] = _compare_providers

    # 4. check_regression
    def _check_regression(args: dict[str, Any]) -> str:
        current_raw = args.get("current_score")
        if current_raw is None:
            return _error_json("validation", "current_score is required")

        current_score = float(current_raw)
        threshold = float(args.get("threshold", 0.1))

        result = regression_gate.check_regression(current_score, threshold)

        return json.dumps(
            {
                "passed": result.passed,
                "current_score": result.current_score,
                "baseline_score": result.baseline_score,
                "threshold": result.threshold,
                "regressions": list(result.regressions),
            }
        )

    specs["check_regression"] = ToolSpec(
        name="check_regression",
        description="Check if current score regresses beyond threshold from baseline",
        parameters=_CHECK_REGRESSION_SCHEMA,
    )
    executors["check_regression"] = _check_regression

    return specs, executors
