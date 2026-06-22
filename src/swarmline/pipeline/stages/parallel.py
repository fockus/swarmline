"""ParallelStage — static fork/join on the registry engine.

Runs a FIXED set of named ``branches`` concurrently over the SAME input (``asyncio.gather``), then a
``joiner`` combines their outputs — the static fork/join a strictly-linear pipeline cannot express.
``require_all`` (default) fails the stage if any branch fails; ``allow_partial`` drops failed
branches (fail-soft) and records their errors as NON-fatal. Each branch is a full stage dispatched
through the engine registry by its TYPE, so branches may be any registered kind. Per-branch attempt
counts surface as ``{name}.{branch}`` entries (``StageOutcome.sub_attempts``); branches share the
single ``PipelineContext`` so the joiner can read what they published. Contrast the dynamic
``FanOutStage`` (one handler over a runtime list).
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Callable, Mapping
from typing import Any, Literal

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

#: How a parallel stage reacts to a branch failure. ``require_all`` → any branch failure fails the
#: stage; ``allow_partial`` → failed branches are dropped (fail-soft) and recorded as non-fatal.
ParallelFailurePolicy = Literal["require_all", "allow_partial"]


@dataclasses.dataclass(frozen=True)
class ParallelStage:
    """Run named ``branches`` concurrently over the same input, then ``joiner`` their outputs."""

    name: str
    branches: Mapping[str, Any]
    joiner: Callable[..., Any] | None = None
    failure_policy: ParallelFailurePolicy = "require_all"
    status_label: str | None = None
    params: Mapping[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        """Reject an empty name, an empty branch map, and an unknown failure policy."""
        if not self.name:
            raise StageConfigError("ParallelStage.name must be non-empty")
        if not self.branches:
            raise StageConfigError("ParallelStage requires at least one branch")
        if self.failure_policy not in ("require_all", "allow_partial"):
            raise StageConfigError(
                "ParallelStage.failure_policy must be 'require_all' or 'allow_partial'"
            )


async def _run_one_branch(
    stage: ParallelStage,
    branch_name: str,
    branch: Any,
    value: Any,
    ctx: PipelineContext,
    event_sink: Any,
) -> tuple[str, Any, int, str | None]:
    """Run a single branch through its registered runner, isolating its failure (decided later)."""
    runner = resolve_runner(
        branch
    )  # fail-fast outside the try — a bad branch type is a config bug
    await emit_event(
        event_sink, "branch_start", {"stage": stage.name, "branch": branch_name}
    )
    try:
        outcome = await runner(branch, value, ctx, event_sink)
        result: tuple[str, Any, int, str | None] = (
            branch_name,
            outcome.value,
            outcome.attempts,
            None,
        )
    except Exception as exc:  # noqa: BLE001 — per-branch isolation; fatality decided by the policy
        attempts = int(getattr(branch, "max_attempts", 1))
        result = (branch_name, None, attempts, str(exc))
    await emit_event(
        event_sink,
        "branch_end",
        {
            "stage": stage.name,
            "branch": branch_name,
            "ok": result[3] is None,
            "error": result[3],
        },
    )
    return result


async def _run_parallel_stage(
    stage: ParallelStage, value: Any, ctx: PipelineContext, event_sink: Any
) -> StageOutcome:
    """Fork every branch over the shared value, then join the survivors per the failure policy."""
    await emit_event(
        event_sink,
        "parallel_start",
        {"stage": stage.name, "branches": tuple(stage.branches)},
    )
    branch_results = await asyncio.gather(
        *(
            _run_one_branch(stage, name, branch, value, ctx, event_sink)
            for name, branch in stage.branches.items()
        )
    )

    outputs: dict[str, Any] = {}
    sub_attempts: dict[str, int] = {}
    errors: list[str] = []
    for branch_name, output, attempt_count, error in branch_results:
        sub_attempts[f"{stage.name}.{branch_name}"] = attempt_count
        if error is None:
            outputs[branch_name] = output
        else:
            errors.append(f"{stage.name}.{branch_name}: {error}")

    if errors and stage.failure_policy == "require_all":
        raise StageExecutionError(
            "; ".join(errors),
            attempts=1,
            sub_attempts=sub_attempts,
            errors=tuple(errors),
        )
    if not outputs:
        raise StageExecutionError(
            "all parallel branches failed",
            attempts=1,
            sub_attempts=sub_attempts,
            errors=tuple(errors),
        )

    joiner = stage.joiner
    if joiner is None:
        joined: Any = outputs
    else:
        joined = await call_with_arity(joiner, outputs, ctx, stage.params)
    await emit_event(
        event_sink,
        "parallel_join",
        {"stage": stage.name, "branches": tuple(outputs), "partial": bool(errors)},
    )
    return StageOutcome(
        value=joined, attempts=1, sub_attempts=sub_attempts, errors=tuple(errors)
    )


register_stage_runner(ParallelStage, _run_parallel_stage)
