"""ConditionalStage — the routing primitive.

A ConditionalStage selects a case key and runs the matching sub-chain against the SAME input — the
branch a strictly-linear pipeline cannot express. The key comes from either a ``selector`` callable
(arity-detected) or a dotted path read off the value (``"kind"`` → ``value.kind`` /
``value["kind"]``). An unmatched key uses ``default``; with no default the routing fails the
pipeline. The chosen sub-chain runs through the same ``run_pipeline`` (so its status events and any
early-terminate propagate to the outer run).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from swarmline.pipeline.dataflow_core import (
    PipelineContext,
    StageConfigError,
    StageExecutionError,
    StageOutcome,
    resolve_path,
)
from swarmline.pipeline.dataflow_engine import register_stage_runner, run_pipeline
from swarmline.pipeline.stages.typed_stage import call_with_arity


@dataclasses.dataclass(frozen=True)
class ConditionalStage:
    """Route the value to one of ``cases`` (by ``selector``) and run that sub-chain."""

    name: str
    selector: str | Callable[..., Any]
    cases: Mapping[str, Sequence[Any]]
    default: Sequence[Any] | None = None
    status_label: str | None = None
    params: Mapping[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        """Reject an empty name / empty cases map."""
        if not self.name:
            raise StageConfigError("ConditionalStage.name must be non-empty")
        if not self.cases:
            raise StageConfigError("ConditionalStage.cases must be non-empty")


async def _run_conditional_stage(
    stage: ConditionalStage, value: Any, ctx: PipelineContext, event_sink: Any
) -> StageOutcome:
    """Resolve the case key, run the matching (or default) sub-chain, propagate its outcome."""
    if callable(stage.selector):
        key = str(await call_with_arity(stage.selector, value, ctx, stage.params))
    else:
        key = str(resolve_path(value, stage.selector))
    branch = stage.cases.get(key, stage.default)
    if branch is None:
        raise StageConfigError(
            f"conditional {stage.name!r}: no case for {key!r} and no default"
        )
    sub = await run_pipeline(branch, value, ctx, event_sink=event_sink)
    if sub.status == "failed":
        # A runtime branch failure (not a config error): propagate the inner accounting + verbatim
        # reason via StageExecutionError so the outer run keeps the sub-chain's attempts and message.
        raise StageExecutionError(
            "; ".join(sub.errors)
            or f"conditional {stage.name!r} branch {key!r} failed",
            attempts=1,
            sub_attempts=dict(sub.attempts),
        )
    return StageOutcome(
        value=sub.output,
        terminate_early=sub.terminated_early,
        sub_attempts=dict(sub.attempts),
        errors=sub.errors,
    )


register_stage_runner(ConditionalStage, _run_conditional_stage)
