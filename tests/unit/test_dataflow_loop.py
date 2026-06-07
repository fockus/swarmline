"""Tests for LoopStage — the bounded review-loop primitive on the registry engine.

A LoopStage runs its ``body`` against the original input, then a ``reviewer`` decides whether the
output may continue. If the reviewer rejects, the body re-runs (against the same input) until it is
approved or ``max_iterations`` is reached. Reaching the limit unapproved FAILS the stage with a
verbatim message and the iteration count recorded (via ``StageExecutionError``). The body runs
through the registry like any stage, so it can be a TypedStage (or any registered kind).
"""

from __future__ import annotations

from typing import Any

from swarmline.pipeline.dataflow_core import StageConfigError
from swarmline.pipeline.dataflow_engine import run_pipeline
from swarmline.pipeline.stages.loop import LoopStage
from swarmline.pipeline.stages.typed_stage import TypedStage


async def test_loop_repeats_body_until_reviewer_passes() -> None:
    """The body re-runs against the original input until the reviewer approves; attempts counted."""
    attempts = 0

    def draft(value: str) -> str:
        nonlocal attempts
        attempts += 1
        return "bad draft" if attempts < 3 else f"{value}: approved draft"

    stage = LoopStage(
        name="review_loop",
        body=TypedStage("draft", draft),
        reviewer=lambda value: "approved" in value,
        max_iterations=3,
    )

    result = await run_pipeline([stage], "report")

    assert result.status == "completed"
    assert result.output == "report: approved draft"
    assert result.attempts == {"review_loop": 3}


async def test_loop_fails_when_reviewer_never_passes_before_limit() -> None:
    """Hitting the iteration limit unapproved fails the stage with a verbatim message + attempts."""
    stage = LoopStage(
        name="review_loop",
        body=TypedStage("draft", lambda value: f"{value}!"),
        reviewer=lambda _value: False,
        max_iterations=2,
    )

    result = await run_pipeline([stage], "report")

    assert result.status == "failed"
    assert result.failed_stage == "review_loop"
    assert result.attempts == {"review_loop": 2}
    assert result.errors == (
        "stage 'review_loop' reviewer did not pass after 2 iterations",
    )


async def test_loop_body_failure_fails_the_stage() -> None:
    """A body that raises fails the loop stage (failed_stage = the loop name)."""
    stage = LoopStage(
        name="review_loop",
        body=TypedStage("draft", lambda value: (_ for _ in ()).throw(RuntimeError("kaboom"))),
        reviewer=lambda _value: True,
        max_iterations=3,
    )

    result = await run_pipeline([stage], "report")

    assert result.status == "failed"
    assert result.failed_stage == "review_loop"
    assert any("kaboom" in err for err in result.errors)


async def test_loop_emits_iteration_events() -> None:
    """Each iteration emits ordered loop_iteration_start / loop_iteration_end events."""
    events: list[tuple[str, dict[str, Any]]] = []

    async def sink(name: str, data: dict[str, Any]) -> None:
        events.append((name, data))

    stage = LoopStage(
        name="review_loop",
        body=TypedStage("draft", lambda value: f"{value}-ok"),
        reviewer=lambda value: "ok" in value,
        max_iterations=2,
    )

    await run_pipeline([stage], "r", event_sink=sink)

    names = [name for name, _ in events]
    assert names.count("loop_iteration_start") == 1
    assert names.count("loop_iteration_end") == 1


async def test_loop_rejects_non_positive_max_iterations() -> None:
    """``max_iterations`` below 1 is a configuration error caught at construction."""
    try:
        LoopStage(
            name="bad",
            body=TypedStage("draft", lambda value: value),
            reviewer=lambda _value: True,
            max_iterations=0,
        )
    except StageConfigError as exc:
        assert "max_iterations" in str(exc)
    else:  # pragma: no cover - the constructor must reject
        raise AssertionError("expected StageConfigError for max_iterations < 1")
