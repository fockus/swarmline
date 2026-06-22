"""TypedStage — the seam-agnostic work stage.

A TypedStage wraps a handler that maps the current value to the next value. The handler is called
with an arity-detected signature — ``(value)``, ``(value, context)`` or ``(value, context,
params)`` — so a declarative loader can pass per-stage ``params`` (e.g. ``max_queries``) without the
handler closing over them. An optional validator rejects bad output. Retries (``max_attempts > 1``)
are permitted ONLY on ``pure`` stages: retrying an ``io`` / ``llm`` stage would re-issue its side
effects (e.g. Tavily searches), silently blowing the budget — so such a config is rejected at
construction, making double-spend impossible by design.
"""

from __future__ import annotations

import dataclasses
import inspect
from collections.abc import Callable, Mapping
from typing import Any

from swarmline.pipeline.dataflow_core import (
    PipelineContext,
    StageConfigError,
    StageDependency,
    StageExecutionError,
    StageOutcome,
    StageValidationError,
)
from swarmline.pipeline.dataflow_engine import register_stage_runner

#: A stage handler: ``value -> value`` (sync or async), optionally taking ``(context)`` and
#: ``(params)`` as 2nd/3rd positional args.
Handler = Callable[..., Any]
#: A validator: ``output -> bool | None`` (None/truthy = pass, False = reject).
Validator = Callable[..., Any]


@dataclasses.dataclass(frozen=True)
class TypedStage:
    """A single work stage: an arity-detected handler + optional validator and bounded retries."""

    name: str
    handler: Handler
    dependency: StageDependency = "pure"
    validator: Validator | None = None
    max_attempts: int = 1
    params: Mapping[str, Any] = dataclasses.field(default_factory=dict)
    status_label: str | None = None

    def __post_init__(self) -> None:
        """Reject an empty name, a sub-1 attempt count, and retries on side-effecting stages."""
        if not self.name:
            raise StageConfigError("TypedStage.name must be non-empty")
        if self.max_attempts < 1:
            raise StageConfigError("TypedStage.max_attempts must be >= 1")
        if self.max_attempts > 1 and self.dependency != "pure":
            raise StageConfigError(
                f"retry (max_attempts>1) is only allowed on 'pure' stages, not "
                f"{self.dependency!r} — a retried side-effecting stage would double-spend"
            )


def _positional_arity(fn: Callable[..., Any]) -> int:
    """Count the leading positional parameters of ``fn``.

    A non-introspectable callable (signature-less builtin like ``str``/``bool``) falls back to a
    1-arg call (``fn(value)``). A ``*args`` callable is treated as the 2-arg ``(value, context)``
    shape — the legacy behaviour — so ``def h(*args): value, ctx = args`` keeps working.
    """
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return 1
    count = 0
    for param in params:
        if param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD):
            count += 1
        elif param.kind is param.VAR_POSITIONAL:
            return max(count, 2)
    return count


async def _maybe_await(result: Any) -> Any:
    """Await ``result`` if it is awaitable; otherwise return it unchanged."""
    if inspect.isawaitable(result):
        return await result
    return result


async def call_with_arity(
    fn: Callable[..., Any], value: Any, ctx: PipelineContext, params: Mapping[str, Any]
) -> Any:
    """Call ``fn`` with ``(value)`` / ``(value, ctx)`` / ``(value, ctx, params)`` by its arity."""
    arity = _positional_arity(fn)
    if arity >= 3:
        return await _maybe_await(fn(value, ctx, params))
    if arity == 2:
        return await _maybe_await(fn(value, ctx))
    return await _maybe_await(fn(value))


async def _run_typed_stage(
    stage: TypedStage,
    value: Any,
    ctx: PipelineContext,
    event_sink: Any,  # noqa: ARG001 — event_sink unused by this stage kind
) -> StageOutcome:
    """Run the handler (with bounded pure-only retries), validate, and on final failure fail with
    the attempt count + verbatim message (so the engine records attempts and reports it unprefixed)."""
    for attempt in range(1, stage.max_attempts + 1):
        try:
            output = await call_with_arity(stage.handler, value, ctx, stage.params)
            if stage.validator is not None:
                verdict = await call_with_arity(
                    stage.validator, output, ctx, stage.params
                )
                if verdict is False:
                    raise StageValidationError(
                        f"stage '{stage.name}' validator returned False"
                    )
            return StageOutcome(value=output, attempts=attempt)
        except Exception as exc:  # noqa: BLE001 — retried (pure stages) or fatal on the last attempt
            if attempt >= stage.max_attempts:
                raise StageExecutionError(str(exc), attempts=attempt) from exc
    raise StageConfigError(  # pragma: no cover — range is non-empty for max_attempts >= 1
        f"stage {stage.name!r} produced no outcome"
    )


register_stage_runner(TypedStage, _run_typed_stage)
