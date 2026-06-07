"""LoopStage — bounded review loop on the registry engine.

Runs ``body`` against the original input, then ``reviewer`` decides whether the output may continue.
If the reviewer rejects, the body re-runs (against the SAME input) until it is approved or
``max_iterations`` is reached. Reaching the limit unapproved FAILS the stage with a verbatim message
and the iteration count recorded (via :class:`StageExecutionError`) — distinct from a body that
raises (which also fails the stage, attributing the failure to the loop). The body runs through the
engine registry like any stage, so it may be a TypedStage or any other registered kind. ``reviewer``
is arity-detected exactly like a stage handler, so it can read the context / params.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from typing import Any

from swarmline.pipeline.dataflow_core import (
    PipelineContext,
    StageConfigError,
    StageExecutionError,
    StageOutcome,
)
from swarmline.pipeline.dataflow_engine import (
    emit_event,
    register_stage_runner,
    resolve_runner,
)
from swarmline.pipeline.stages.typed_stage import call_with_arity


@dataclasses.dataclass(frozen=True)
class LoopStage:
    """Re-run ``body`` against the original input until ``reviewer`` approves or the limit is hit."""

    name: str
    body: Any
    reviewer: Callable[..., Any]
    max_iterations: int = 3
    status_label: str | None = None
    params: Mapping[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        """Reject an empty name and a sub-1 iteration limit."""
        if not self.name:
            raise StageConfigError("LoopStage.name must be non-empty")
        if self.max_iterations < 1:
            raise StageConfigError("LoopStage.max_iterations must be >= 1")


async def _run_loop_stage(
    stage: LoopStage, value: Any, ctx: PipelineContext, event_sink: Any
) -> StageOutcome:
    """Iterate body→review until approval; fail (with attempts) on the limit or a body error."""
    body_runner = resolve_runner(stage.body)
    for iteration in range(1, stage.max_iterations + 1):
        await emit_event(
            event_sink, "loop_iteration_start", {"stage": stage.name, "iteration": iteration}
        )
        try:
            outcome = await body_runner(stage.body, value, ctx, event_sink)
        except Exception as exc:  # noqa: BLE001 — a body failure fails the loop stage
            raise StageExecutionError(
                f"loop {stage.name!r} body failed: {exc}", attempts=iteration
            ) from exc
        candidate = outcome.value
        approved = await call_with_arity(stage.reviewer, candidate, ctx, stage.params)
        await emit_event(
            event_sink,
            "loop_iteration_end",
            {"stage": stage.name, "iteration": iteration, "approved": bool(approved)},
        )
        if approved:
            return StageOutcome(
                value=candidate,
                attempts=iteration,
                sub_attempts=outcome.sub_attempts,
                errors=outcome.errors,
            )
    raise StageExecutionError(
        f"stage '{stage.name}' reviewer did not pass after {stage.max_iterations} iterations",
        attempts=stage.max_iterations,
    )


register_stage_runner(LoopStage, _run_loop_stage)
