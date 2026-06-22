"""Tests for GuardStage — graceful early-exit as a first-class success.

A GuardStage checks a predicate over the current value: when it trips, the pipeline COMPLETES
EARLY (``terminated_early=True``, status ``completed``) with the guard's ``on_trip`` payload — a
normal business outcome, NOT a failure or a fallback. When it does not trip, the value passes
through.
"""

from __future__ import annotations

from swarmline.pipeline.dataflow_engine import run_pipeline
from swarmline.pipeline.stages.guard_stage import GuardStage
from swarmline.pipeline.stages.typed_stage import TypedStage


async def test_guard_trips_and_terminates_early() -> None:
    """A tripped guard completes the run early with its notice; later stages do not run."""
    result = await run_pipeline(
        [
            GuardStage("empty_pool", predicate=lambda v: v == [], on_trip="NOTICE"),
            TypedStage("never", lambda v: f"{v}!"),
        ],
        [],
    )

    assert result.status == "completed"
    assert result.terminated_early is True
    assert result.output == "NOTICE"
    assert "never" not in result.attempts


async def test_guard_passes_through_when_not_tripped() -> None:
    """An untripped guard returns the value unchanged and the pipeline continues."""
    result = await run_pipeline(
        [
            GuardStage("empty_pool", predicate=lambda v: v == [], on_trip="NOTICE"),
            TypedStage("next", lambda v: [*v, 1]),
        ],
        [0],
    )

    assert result.status == "completed"
    assert result.terminated_early is False
    assert result.output == [0, 1]


async def test_guard_on_trip_callable_computes_payload() -> None:
    """When on_trip is callable it is invoked with the value to compute the early output."""
    result = await run_pipeline(
        [
            GuardStage(
                "g", predicate=lambda v: v == "X", on_trip=lambda v: f"tripped:{v}"
            )
        ],
        "X",
    )

    assert result.terminated_early is True
    assert result.output == "tripped:X"
