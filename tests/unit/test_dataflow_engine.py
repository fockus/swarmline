"""Tests for the data-flow pipeline engine — registry-dispatch + forward data-flow.

The engine dispatches each stage by its TYPE through a ``register_stage_runner`` registry (NOT an
isinstance chain), so new stage kinds plug in without editing the engine (OCP). It threads the
current value forward (output → next input), emits per-stage events, honours an early-terminate
outcome, and degrades per the fallback policy on a stage failure.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from swarmline.pipeline.dataflow_core import (
    PipelineContext,
    StageConfigError,
    StageExecutionError,
    StageOutcome,
)
from swarmline.pipeline.dataflow_engine import register_stage_runner, run_pipeline


@dataclasses.dataclass(frozen=True)
class _AppendStage:
    """A trivial test stage: append ``suffix`` to the running string value."""

    name: str
    suffix: str
    status_label: str | None = None


async def _run_append(
    stage: _AppendStage,
    value: Any,
    ctx: PipelineContext,
    event_sink: Any,  # noqa: ARG001
) -> StageOutcome:
    return StageOutcome(value=f"{value}{stage.suffix}")


@dataclasses.dataclass(frozen=True)
class _TerminateStage:
    """A stage that completes the pipeline early with a fixed payload."""

    name: str
    payload: Any


async def _run_terminate(
    stage: _TerminateStage,
    value: Any,
    ctx: PipelineContext,
    event_sink: Any,  # noqa: ARG001
) -> StageOutcome:
    return StageOutcome(value=stage.payload, terminate_early=True)


@dataclasses.dataclass(frozen=True)
class _BoomStage:
    """A stage that always raises (drives the fallback / failed paths)."""

    name: str


async def _run_boom(
    stage: _BoomStage,
    value: Any,
    ctx: PipelineContext,
    event_sink: Any,  # noqa: ARG001
) -> StageOutcome:
    raise RuntimeError("boom")


@dataclasses.dataclass(frozen=True)
class _UnregisteredStage:
    name: str


register_stage_runner(_AppendStage, _run_append)
register_stage_runner(_TerminateStage, _run_terminate)
register_stage_runner(_BoomStage, _run_boom)


async def test_dispatch_runs_registered_runners_in_order() -> None:
    """Stages run sequentially; each output feeds the next (forward data-flow)."""
    result = await run_pipeline(
        [_AppendStage("a", "-A"), _AppendStage("b", "-B")], "start"
    )

    assert result.status == "completed"
    assert result.output == "start-A-B"
    assert result.attempts == {"a": 1, "b": 1}


async def test_unknown_stage_type_raises_config_error() -> None:
    """A stage type with no registered runner fails fast with a clear config error."""
    try:
        await run_pipeline([_UnregisteredStage("x")], "v")
    except StageConfigError as exc:
        assert "_UnregisteredStage" in str(exc)
    else:  # pragma: no cover - the call must raise
        raise AssertionError("expected StageConfigError for an unregistered stage type")


async def test_status_label_emitted_before_stage_runs() -> None:
    """A stage carrying ``status_label`` emits an ordered 'status' event before executing."""
    events: list[tuple[str, dict[str, Any]]] = []

    async def sink(name: str, data: dict[str, Any]) -> None:
        events.append((name, data))

    await run_pipeline(
        [_AppendStage("a", "-A", status_label="searching")], "s", event_sink=sink
    )

    statuses = [data["label"] for name, data in events if name == "status"]
    assert statuses == ["searching"]


async def test_terminate_early_stops_remaining_stages() -> None:
    """An early-terminate outcome completes the pipeline without running later stages."""
    result = await run_pipeline(
        [_TerminateStage("guard", "EARLY"), _AppendStage("never", "-X")], "s"
    )

    assert result.status == "completed"
    assert result.terminated_early is True
    assert result.output == "EARLY"
    assert "never" not in result.attempts


async def test_failure_without_fallback_marks_failed() -> None:
    """A stage exception with the default policy yields status='failed' + the failing stage name."""
    result = await run_pipeline([_AppendStage("a", "-A"), _BoomStage("boom")], "s")

    assert result.status == "failed"
    assert result.failed_stage == "boom"
    assert any("boom" in err for err in result.errors)


async def test_fallback_last_valid_returns_last_good_output() -> None:
    """With fallback='last_valid' a failure returns the last successful value, status='fallback'."""
    result = await run_pipeline(
        [_AppendStage("a", "-A"), _BoomStage("boom")], "s", fallback="last_valid"
    )

    assert result.status == "fallback"
    assert result.output == "s-A"
    assert result.failed_stage == "boom"


# ── Composite-stage accounting: sub_attempts / non-fatal errors / StageExecutionError ───────


@dataclasses.dataclass(frozen=True)
class _CompositeStage:
    """A stage that reports per-child attempts and non-fatal child errors to the engine."""

    name: str


async def _run_composite(
    stage: _CompositeStage,
    value: Any,
    ctx: PipelineContext,
    event_sink: Any,  # noqa: ARG001
) -> StageOutcome:
    return StageOutcome(
        value=f"{value}-joined",
        sub_attempts={f"{stage.name}.x": 1, f"{stage.name}.y": 2},
        errors=(f"{stage.name}.y: soft fail",),
    )


@dataclasses.dataclass(frozen=True)
class _FatalStage:
    """A stage whose runner fails fatally while reporting its own attempts + verbatim message."""

    name: str


async def _run_fatal(
    stage: _FatalStage,
    value: Any,
    ctx: PipelineContext,
    event_sink: Any,  # noqa: ARG001
) -> StageOutcome:
    raise StageExecutionError(f"stage {stage.name!r} gave up after 3 tries", attempts=3)


register_stage_runner(_CompositeStage, _run_composite)
register_stage_runner(_FatalStage, _run_fatal)


async def test_sub_attempts_merge_into_result_attempts() -> None:
    """A StageOutcome.sub_attempts map is merged alongside the stage's own attempt entry."""
    result = await run_pipeline([_CompositeStage("compare")], "v")

    assert result.status == "completed"
    assert result.attempts == {"compare": 1, "compare.x": 1, "compare.y": 2}


async def test_outcome_errors_accumulate_without_failing() -> None:
    """Non-fatal StageOutcome.errors surface in the result while the run stays 'completed'."""
    result = await run_pipeline([_CompositeStage("compare")], "v")

    assert result.status == "completed"
    assert result.output == "v-joined"
    assert result.errors == ("compare.y: soft fail",)


async def test_stage_execution_error_records_attempts_and_verbatim_message() -> None:
    """StageExecutionError fails the run, records its attempts, and is reported VERBATIM (no prefix)."""
    result = await run_pipeline([_FatalStage("loop")], "v")

    assert result.status == "failed"
    assert result.failed_stage == "loop"
    assert result.attempts == {"loop": 3}
    assert result.errors == ("stage 'loop' gave up after 3 tries",)


async def test_first_stage_failure_with_fallback_is_failed_not_fallback() -> None:
    """last_valid degrades only when a PRIOR stage succeeded; a first-stage failure stays 'failed'."""
    result = await run_pipeline([_BoomStage("boom")], "s", fallback="last_valid")

    assert result.status == "failed"
    assert result.output is None
    assert result.failed_stage == "boom"


@dataclasses.dataclass(frozen=True)
class _FatalWithChildErrors:
    """A composite-style stage that fails fatally while reporting per-child non-fatal errors."""

    name: str


async def _run_fatal_with_children(
    stage: _FatalWithChildErrors,
    value: Any,
    ctx: PipelineContext,
    event_sink: Any,  # noqa: ARG001
) -> StageOutcome:
    raise StageExecutionError(
        "all children failed",
        attempts=1,
        errors=(f"{stage.name}.a: boom", f"{stage.name}.b: boom"),
    )


register_stage_runner(_FatalWithChildErrors, _run_fatal_with_children)


async def test_stage_execution_error_extends_per_child_errors_then_summary() -> None:
    """StageExecutionError.errors (per-child) are surfaced BEFORE the verbatim summary message."""
    result = await run_pipeline([_FatalWithChildErrors("par")], "v")

    assert result.status == "failed"
    assert result.errors == ("par.a: boom", "par.b: boom", "all children failed")
