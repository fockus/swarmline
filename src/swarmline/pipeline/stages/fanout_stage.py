"""FanOutStage — dynamic bounded fan-out.

Runs ``item_handler`` over a runtime list (resolved from ``over``), bounded by a
``Semaphore(concurrency)`` and sliced to ``max_n``, with its OWN per-item try/except: with
``on_item_error="skip"`` a failed item degrades to skipped (fail-soft union), with ``"fail"`` it
fails the stage. The item handler is invoked directly (NOT through the retry/fail-hard stage
machinery), so an item is never re-issued — no double-spend. Unlike the static
``ParallelStage`` (named branches, require_all/allow_partial), FanOut is dynamic over a
runtime collection with a concurrency cap, an item cap, dedup, and fail-soft.

* ``dedup_key`` set → each item result is treated as an iterable; results are flattened and deduped
  by key, first-seen order preserved (the ``gather`` shape).
* ``dedup_key`` absent → per-item results are collected in input order; an optional ``joiner``
  combines them (e.g. ``dict`` for the reviews shape).
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Callable, Mapping
from typing import Any, Literal

from swarmline.pipeline.dataflow_core import (
    PipelineContext,
    StageConfigError,
    StageDependency,
    StageOutcome,
    resolve_path,
)
from swarmline.pipeline.dataflow_engine import register_stage_runner
from swarmline.pipeline.stages.typed_stage import call_with_arity


@dataclasses.dataclass(frozen=True)
class FanOutStage:
    """Concurrent, bounded, fail-soft fan-out of ``item_handler`` over a runtime list."""

    name: str
    item_handler: Callable[..., Any]
    over: str | Callable[..., Any]
    concurrency: int
    max_n: int
    dedup_key: str | Callable[..., Any] | None = None
    on_item_error: Literal["skip", "fail"] = "skip"
    joiner: Callable[..., Any] | None = None
    dependency: StageDependency = "io"
    status_label: str | None = None
    params: Mapping[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        """Reject empty name, sub-1 concurrency/max_n, and an unknown item-error policy."""
        if not self.name:
            raise StageConfigError("FanOutStage.name must be non-empty")
        if self.concurrency < 1:
            raise StageConfigError("FanOutStage.concurrency must be >= 1")
        if self.max_n < 1:
            raise StageConfigError("FanOutStage.max_n must be >= 1")
        if self.on_item_error not in ("skip", "fail"):
            raise StageConfigError("FanOutStage.on_item_error must be 'skip' or 'fail'")


async def _resolve_items(
    stage: FanOutStage, value: Any, ctx: PipelineContext
) -> list[Any]:
    """Resolve the runtime item list from ``over`` (callable or dotted path on the value)."""
    if callable(stage.over):
        items = await call_with_arity(stage.over, value, ctx, stage.params)
    else:
        items = resolve_path(value, stage.over)
    return list(items)


def _key_of(element: Any, key: str) -> Any:
    """Read ``key`` off an element (Mapping key or attribute) for dedup."""
    if isinstance(element, Mapping):
        return element.get(key)
    return getattr(element, key, None)


def _dedup_flatten(
    batches: list[Any], dedup_key: str | Callable[..., Any]
) -> list[Any]:
    """Flatten per-item iterables and drop duplicates by key, preserving first-seen order."""
    seen: set[Any] = set()
    out: list[Any] = []
    for batch in batches:
        for element in batch:
            if isinstance(dedup_key, str):
                key = _key_of(element, dedup_key)
            else:
                key = dedup_key(element)
            if key not in seen:
                seen.add(key)
                out.append(element)
    return out


async def _run_fanout_stage(
    stage: FanOutStage,
    value: Any,
    ctx: PipelineContext,
    event_sink: Any,  # noqa: ARG001 — event_sink unused by this stage kind
) -> StageOutcome:
    """Fan ``item_handler`` over the bounded item list, fail-soft per item, then dedup / join."""
    issued = (await _resolve_items(stage, value, ctx))[: stage.max_n]
    semaphore = asyncio.Semaphore(stage.concurrency)

    async def _one(item: Any) -> tuple[bool, Any]:
        async with semaphore:
            try:
                return True, await call_with_arity(
                    stage.item_handler, item, ctx, stage.params
                )
            except Exception:  # noqa: BLE001 — fail-soft per item unless on_item_error='fail'
                if stage.on_item_error == "fail":
                    raise
                return False, None

    results = await asyncio.gather(*(_one(item) for item in issued))
    collected = [output for ok, output in results if ok]

    if stage.dedup_key is not None:
        combined: Any = _dedup_flatten(collected, stage.dedup_key)
    else:
        combined = collected
    if stage.joiner is not None:
        combined = stage.joiner(combined)
    return StageOutcome(value=combined)


register_stage_runner(FanOutStage, _run_fanout_stage)
