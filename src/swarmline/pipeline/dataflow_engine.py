"""Data-flow pipeline engine — registry-dispatch sequential executor.

``run_pipeline`` walks the stages in order, threading the current value forward (each stage's
output is the next stage's input), and dispatches each stage to its runner via a TYPE registry
(``register_stage_runner``) — NOT an ``isinstance`` chain. New stage kinds register their runner at
import time, so adding a stage type never edits this module (OCP).

The engine also emits ordered events (``status`` when a stage declares a ``status_label``, plus
``stage_start`` / ``stage_end`` / ``stage_failed``), honours a stage's early-terminate outcome, and
degrades per the fallback policy when a stage raises.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from swarmline.pipeline.dataflow_core import (
    EventSink,
    FallbackMode,
    PipelineContext,
    PipelineResult,
    StageConfigError,
    StageExecutionError,
    StageOutcome,
)

logger = logging.getLogger(__name__)

#: A stage runner: ``await runner(stage, value, context, event_sink) -> StageOutcome``.
StageRunner = Callable[
    [Any, Any, PipelineContext, "EventSink | None"], Awaitable[StageOutcome]
]

#: Type → runner registry. Populated by ``register_stage_runner`` at stage-module import time.
_STAGE_RUNNERS: dict[type, StageRunner] = {}


def register_stage_runner(stage_type: type, runner: StageRunner) -> None:
    """Register ``runner`` as the executor for stages of exactly ``stage_type``."""
    _STAGE_RUNNERS[stage_type] = runner


def stage_runner(stage_type: type) -> Callable[[StageRunner], StageRunner]:
    """Decorator form of :func:`register_stage_runner` for a stage runner function."""

    def decorate(runner: StageRunner) -> StageRunner:
        register_stage_runner(stage_type, runner)
        return runner

    return decorate


async def emit_event(
    event_sink: EventSink | None, name: str, data: dict[str, Any]
) -> None:
    """Fire an event on the sink if one is wired (no-op otherwise).

    Public so composite stage runners (fork/join, review loop) can emit their own granular events
    through the same sink the engine uses.
    """
    if event_sink is not None:
        await event_sink(name, data)


def resolve_runner(stage: Any) -> StageRunner:
    """Return the runner registered for ``stage``'s exact type, or raise :class:`StageConfigError`.

    Composite stages dispatch a child stage through this — keeping type dispatch in ONE place (the
    registry), so there is no ``isinstance`` chain anywhere in the pipeline package.
    """
    runner = _STAGE_RUNNERS.get(type(stage))
    if runner is None:
        raise StageConfigError(
            f"no runner registered for stage type {type(stage).__name__!r}"
        )
    return runner


async def _fail(
    event_sink: EventSink | None,
    fallback: FallbackMode,
    has_valid: bool,
    last_valid: Any,
    failed_stage: str,
    attempts: dict[str, int],
    errors: list[str],
) -> PipelineResult:
    """Build the terminal result for a stage failure per the ``fallback`` policy.

    A ``last_valid`` degrade applies ONLY when a PRIOR stage actually produced a value
    (``has_valid``) — a failure with nothing valid behind it cannot fall back and is reported as
    ``failed``. When it does degrade, the legacy ``fallback_selected`` event is emitted first.
    """
    if fallback == "last_valid" and has_valid:
        await emit_event(
            event_sink,
            "fallback_selected",
            {"stage": failed_stage, "mode": "last_valid"},
        )
        return PipelineResult(
            status="fallback",
            output=last_valid,
            failed_stage=failed_stage,
            attempts=attempts,
            errors=tuple(errors),
        )
    return PipelineResult(
        status="failed",
        output=None,
        failed_stage=failed_stage,
        attempts=attempts,
        errors=tuple(errors),
    )


async def run_pipeline(
    stages: Sequence[Any],
    initial: Any,
    context: PipelineContext | None = None,
    *,
    event_sink: EventSink | None = None,
    fallback: FallbackMode = "none",
) -> PipelineResult:
    """Run ``stages`` in order over ``initial``, returning the aggregate :class:`PipelineResult`.

    Each stage is dispatched by type via the runner registry; an unregistered type raises
    :class:`StageConfigError`. A stage's :class:`StageOutcome` carries the next value, its attempt
    count, and an optional early-terminate (which completes the run with that value). On a stage
    exception the run degrades per ``fallback``: ``last_valid`` returns the last good value with
    status ``fallback``; otherwise status ``failed``.
    """
    ctx = context if context is not None else PipelineContext()
    value = initial
    last_valid = initial
    has_valid = False  # a last_valid degrade applies only once a prior stage has produced a value
    attempts: dict[str, int] = {}
    errors: list[str] = []

    for stage in stages:
        runner = resolve_runner(stage)
        status_label = getattr(stage, "status_label", None)
        if status_label:
            await emit_event(
                event_sink, "status", {"label": status_label, "stage": stage.name}
            )
        await emit_event(event_sink, "stage_start", {"stage": stage.name})
        try:
            outcome = await runner(stage, value, ctx, event_sink)
        except StageExecutionError as exc:
            # A composite/iterative stage failed fatally but reported its own accounting + message.
            attempts[stage.name] = exc.attempts
            if exc.sub_attempts:
                attempts.update(exc.sub_attempts)
            errors.extend(
                exc.errors
            )  # per-child detail first, then the verbatim summary below
            errors.append(
                str(exc)
            )  # verbatim — the stage already formatted its message
            await emit_event(
                event_sink, "stage_failed", {"stage": stage.name, "error": str(exc)}
            )
            logger.debug("pipeline stage %r failed: %s", stage.name, exc)
            return await _fail(
                event_sink,
                fallback,
                has_valid,
                last_valid,
                stage.name,
                attempts,
                errors,
            )
        except Exception as exc:  # noqa: BLE001 — a stage failure is handled per the fallback policy
            attempts[stage.name] = getattr(stage, "max_attempts", 1)
            errors.append(f"{stage.name}: {exc}")
            await emit_event(
                event_sink, "stage_failed", {"stage": stage.name, "error": str(exc)}
            )
            logger.debug("pipeline stage %r failed: %s", stage.name, exc)
            return await _fail(
                event_sink,
                fallback,
                has_valid,
                last_valid,
                stage.name,
                attempts,
                errors,
            )
        attempts[stage.name] = outcome.attempts
        if outcome.sub_attempts:
            attempts.update(outcome.sub_attempts)
        if outcome.errors:
            errors.extend(outcome.errors)
        await emit_event(event_sink, "stage_end", {"stage": stage.name})
        if outcome.terminate_early:
            return PipelineResult(
                status="completed",
                output=outcome.value,
                attempts=attempts,
                errors=tuple(errors),
                terminated_early=True,
            )
        value = outcome.value
        last_valid = value
        has_valid = True

    return PipelineResult(
        status="completed", output=value, attempts=attempts, errors=tuple(errors)
    )
