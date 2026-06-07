"""Tests for TypedStage — the seam-agnostic work stage.

A TypedStage wraps a handler called with arity-detected ``(value)`` / ``(value, ctx)`` /
``(value, ctx, params)``; an optional validator rejects bad output; retries are allowed ONLY on
``pure`` stages (a side-effecting stage with ``max_attempts>1`` would re-issue its side effects —
e.g. Tavily calls — so it is rejected at construction to make double-spend impossible).
"""

from __future__ import annotations

from typing import Any

from swarmline.pipeline.dataflow_core import PipelineContext, StageConfigError
from swarmline.pipeline.dataflow_engine import run_pipeline
from swarmline.pipeline.stages.typed_stage import TypedStage


async def test_handler_receives_params_when_three_arg() -> None:
    """A 3-arg handler is given (value, context, params); params come from the stage."""

    async def handler(value: int, ctx: PipelineContext, params: dict[str, Any]) -> int:  # noqa: ARG001
        return value * params["factor"]

    result = await run_pipeline(
        [TypedStage("mul", handler, params={"factor": 3})], 4
    )

    assert result.output == 12


async def test_handler_two_arg_gets_context_only() -> None:
    """A 2-arg handler is given (value, context) and can read artifacts from it."""

    async def handler(value: int, ctx: PipelineContext) -> int:
        return value + ctx.read_artifact("bonus", 0)

    ctx = PipelineContext()
    ctx.write_artifact("bonus", 10)
    result = await run_pipeline([TypedStage("add", handler)], 5, context=ctx)

    assert result.output == 15


async def test_handler_one_arg_and_sync_supported() -> None:
    """A plain 1-arg SYNC handler works (the stage awaits only when needed)."""

    def handler(value: int) -> int:
        return value - 1

    result = await run_pipeline([TypedStage("dec", handler)], 9)

    assert result.output == 8


async def test_validator_false_fails_the_stage() -> None:
    """A validator returning False rejects the output → the pipeline fails on that stage."""

    result = await run_pipeline(
        [TypedStage("v", lambda value: value, validator=lambda out: out > 0)], -1
    )

    assert result.status == "failed"
    assert result.failed_stage == "v"


async def test_validator_none_passes() -> None:
    """A validator returning None (not False) is treated as a pass."""

    result = await run_pipeline(
        [TypedStage("v", lambda value: value, validator=lambda out: None)], 7  # noqa: ARG005
    )

    assert result.status == "completed"
    assert result.output == 7


async def test_retry_on_pure_stage_reruns_until_success() -> None:
    """A pure stage with max_attempts>1 re-runs the handler on failure and counts attempts."""
    calls = {"n": 0}

    def flaky(value: int) -> int:
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("transient")
        return value

    result = await run_pipeline(
        [TypedStage("flaky", flaky, dependency="pure", max_attempts=3)], 42
    )

    assert result.status == "completed"
    assert result.output == 42
    assert result.attempts["flaky"] == 2


def test_retry_forbidden_on_side_effecting_stage() -> None:
    """Constructing a non-pure stage with max_attempts>1 fails fast (anti double-spend)."""
    for dependency in ("io", "llm"):
        try:
            TypedStage("x", lambda v: v, dependency=dependency, max_attempts=2)  # noqa: ARG005
        except StageConfigError as exc:
            assert "double-spend" in str(exc) or "pure" in str(exc)
        else:  # pragma: no cover
            raise AssertionError(f"expected StageConfigError for {dependency!r} retry")


def test_bad_config_rejected() -> None:
    """Empty name and max_attempts<1 are rejected at construction."""
    for bad in (
        lambda: TypedStage("", lambda v: v),  # noqa: ARG005
        lambda: TypedStage("x", lambda v: v, max_attempts=0),  # noqa: ARG005
    ):
        try:
            bad()
        except StageConfigError:
            pass
        else:  # pragma: no cover
            raise AssertionError("expected StageConfigError for bad TypedStage config")
