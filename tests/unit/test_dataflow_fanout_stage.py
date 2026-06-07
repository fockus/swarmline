"""Tests for FanOutStage — dynamic bounded fan-out.

FanOutStage runs ``item_handler`` over a runtime list (resolved from ``over``), bounded by
``Semaphore(concurrency)`` and sliced to ``max_n``, with its OWN per-item try/except so a single
failed item degrades to skipped (fail-soft union) instead of failing the whole stage — the contract
the static ``ParallelPipelineStage`` (named branches, require_all/allow_partial) cannot express. The
item handler bypasses the retry/fail-hard machinery, so an item is never issued twice (no
double-spend).
"""

from __future__ import annotations

import asyncio
from typing import Any

from swarmline.pipeline.dataflow_core import StageConfigError
from swarmline.pipeline.dataflow_engine import run_pipeline
from swarmline.pipeline.stages.fanout_stage import FanOutStage


async def test_concurrency_is_bounded_by_semaphore() -> None:
    """No more than ``concurrency`` item handlers run at once (peak ≤ bound)."""
    state = {"current": 0, "peak": 0}

    async def handler(item: Any, ctx: Any, params: Any) -> list[Any]:  # noqa: ARG001
        state["current"] += 1
        state["peak"] = max(state["peak"], state["current"])
        await asyncio.sleep(0.01)
        state["current"] -= 1
        return [item]

    await run_pipeline(
        [FanOutStage("fan", item_handler=handler, over=lambda v: v, concurrency=2, max_n=10)],
        [1, 2, 3, 4, 5],
    )

    assert state["peak"] <= 2


async def test_max_n_caps_issued_items() -> None:
    """Only the first ``max_n`` items are handled (the budget ceiling)."""
    calls: list[Any] = []

    async def handler(item: Any, ctx: Any, params: Any) -> Any:  # noqa: ARG001
        calls.append(item)
        return item

    result = await run_pipeline(
        [FanOutStage("fan", item_handler=handler, over=lambda v: v, concurrency=4, max_n=3)],
        [1, 2, 3, 4, 5],
    )

    assert sorted(calls) == [1, 2, 3]  # only 3 issued, never re-issued (no double-spend)
    assert sorted(result.output) == [1, 2, 3]


async def test_dedup_flattens_and_keeps_first_seen() -> None:
    """With ``dedup_key`` the per-item lists are flattened and deduped, first-seen order kept."""

    async def handler(item: str, ctx: Any, params: Any) -> list[dict[str, str]]:  # noqa: ARG001
        return [{"id": item}, {"id": "shared"}]

    result = await run_pipeline(
        [
            FanOutStage(
                "fan",
                item_handler=handler,
                over=lambda v: v,
                concurrency=4,
                max_n=10,
                dedup_key=lambda el: el["id"],
            )
        ],
        ["a", "b"],
    )

    assert result.output == [{"id": "a"}, {"id": "shared"}, {"id": "b"}]


async def test_on_item_error_skip_degrades_to_empty() -> None:
    """A failing item is skipped (fail-soft union); the others still contribute."""

    async def handler(item: str, ctx: Any, params: Any) -> list[str]:  # noqa: ARG001
        if item == "bad":
            raise RuntimeError("boom")
        return [item]

    result = await run_pipeline(
        [
            FanOutStage(
                "fan",
                item_handler=handler,
                over=lambda v: v,
                concurrency=4,
                max_n=10,
                dedup_key=lambda el: el,
                on_item_error="skip",
            )
        ],
        ["a", "bad", "b"],
    )

    assert result.status == "completed"
    assert result.output == ["a", "b"]


async def test_on_item_error_fail_fails_the_stage() -> None:
    """With on_item_error='fail' a single item exception fails the stage."""

    async def handler(item: str, ctx: Any, params: Any) -> list[str]:  # noqa: ARG001
        if item == "bad":
            raise RuntimeError("boom")
        return [item]

    result = await run_pipeline(
        [
            FanOutStage(
                "fan",
                item_handler=handler,
                over=lambda v: v,
                concurrency=4,
                max_n=10,
                on_item_error="fail",
            )
        ],
        ["a", "bad"],
    )

    assert result.status == "failed"
    assert result.failed_stage == "fan"


async def test_joiner_combines_results_into_dict() -> None:
    """Without dedup the per-item results are collected and a joiner can combine them (reviews)."""

    async def handler(item: str, ctx: Any, params: Any) -> tuple[str, int]:  # noqa: ARG001
        return item, len(item)

    result = await run_pipeline(
        [
            FanOutStage(
                "reviews",
                item_handler=handler,
                over=lambda v: v,
                concurrency=4,
                max_n=10,
                joiner=lambda pairs: dict(pairs),
            )
        ],
        ["aa", "bbb"],
    )

    assert result.output == {"aa": 2, "bbb": 3}


def test_bad_config_rejected() -> None:
    """Empty name / sub-1 concurrency or max_n / bad on_item_error are rejected at construction."""
    bad_configs = [
        lambda: FanOutStage("", item_handler=lambda x: x, over="o", concurrency=1, max_n=1),  # noqa: ARG005
        lambda: FanOutStage("f", item_handler=lambda x: x, over="o", concurrency=0, max_n=1),  # noqa: ARG005
        lambda: FanOutStage("f", item_handler=lambda x: x, over="o", concurrency=1, max_n=0),  # noqa: ARG005
        lambda: FanOutStage(
            "f", item_handler=lambda x: x, over="o", concurrency=1, max_n=1, on_item_error="oops"  # noqa: ARG005
        ),
    ]
    for make in bad_configs:
        try:
            make()
        except StageConfigError:
            pass
        else:  # pragma: no cover
            raise AssertionError("expected StageConfigError for bad FanOutStage config")
