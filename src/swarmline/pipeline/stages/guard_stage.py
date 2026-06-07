"""GuardStage — graceful early-exit as a first-class success.

A GuardStage evaluates a predicate over the current value. When it trips, the pipeline completes
EARLY (``StageOutcome.terminate_early``) with the guard's ``on_trip`` payload — a normal business
outcome (status ``completed``), distinct from a failure or a ``last_valid`` fallback. When the
predicate does not trip, the value passes through unchanged and the pipeline continues.

``predicate`` and ``on_trip`` (when callable) are arity-detected exactly like a TypedStage handler,
so they can read the context / params. A non-callable ``on_trip`` is used as the literal payload.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from typing import Any

from swarmline.pipeline.dataflow_core import (
    PipelineContext,
    StageConfigError,
    StageOutcome,
)
from swarmline.pipeline.dataflow_engine import register_stage_runner
from swarmline.pipeline.stages.typed_stage import call_with_arity


@dataclasses.dataclass(frozen=True)
class GuardStage:
    """Complete the pipeline early with ``on_trip`` when ``predicate`` holds; else pass through."""

    name: str
    predicate: Callable[..., Any]
    on_trip: Any
    status_label: str | None = None
    params: Mapping[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        """Reject an empty name."""
        if not self.name:
            raise StageConfigError("GuardStage.name must be non-empty")


async def _run_guard_stage(
    stage: GuardStage,
    value: Any,
    ctx: PipelineContext,
    event_sink: Any,  # noqa: ARG001 — event_sink unused by this stage kind
) -> StageOutcome:
    """Trip → early-complete with ``on_trip`` (literal/computed); else pass ``value`` through."""
    tripped = await call_with_arity(stage.predicate, value, ctx, stage.params)
    if not tripped:
        return StageOutcome(value=value)
    if callable(stage.on_trip):
        payload = await call_with_arity(stage.on_trip, value, ctx, stage.params)
    else:
        payload = stage.on_trip
    return StageOutcome(value=payload, terminate_early=True)


register_stage_runner(GuardStage, _run_guard_stage)
