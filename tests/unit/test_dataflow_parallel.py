"""Tests for ParallelStage — the static fork/join primitive on the registry engine.

A ParallelStage runs named ``branches`` concurrently over the SAME input, then joins their outputs
(``joiner``) — the static fork/join a strictly-linear pipeline cannot express. ``require_all`` fails
the stage if any branch fails; ``allow_partial`` drops failed branches (fail-soft) and records their
errors as non-fatal. Per-branch attempt counts surface as ``{name}.{branch}`` entries in the run's
attempts dict (``StageOutcome.sub_attempts``). Branches share the single ``PipelineContext`` so a
joiner can read artifacts/messages they published. Unlike the dynamic ``FanOutStage`` (one handler
over a runtime list), ParallelStage is a fixed set of named, heterogeneous branches.
"""

from __future__ import annotations

from typing import Any

from swarmline.pipeline.dataflow_core import PipelineContext, StageConfigError
from swarmline.pipeline.dataflow_engine import run_pipeline
from swarmline.pipeline.stages.parallel import ParallelStage
from swarmline.pipeline.stages.typed_stage import TypedStage


async def test_parallel_fans_out_and_joins_branch_outputs() -> None:
    """Branches run concurrently; the joiner combines their outputs; sub-attempts surface."""
    stage = ParallelStage(
        name="compare",
        branches={
            "fast": TypedStage("fast", lambda value: f"fast:{value}"),
            "deep": TypedStage("deep", lambda value: f"deep:{value}"),
        },
        joiner=lambda outputs: outputs["fast"] + "|" + outputs["deep"],
    )

    result = await run_pipeline([stage], "question")

    assert result.status == "completed"
    assert result.output == "fast:question|deep:question"
    assert result.attempts == {"compare.fast": 1, "compare.deep": 1, "compare": 1}


async def test_parallel_allow_partial_drops_failed_branch() -> None:
    """``allow_partial``: a failed branch is skipped, its error recorded non-fatally."""
    stage = ParallelStage(
        name="compare",
        branches={
            "ok": TypedStage("ok", lambda value: f"ok:{value}"),
            "bad": TypedStage("bad", lambda value: (_ for _ in ()).throw(RuntimeError("boom"))),
        },
        joiner=lambda outputs: outputs,
        failure_policy="allow_partial",
    )

    result = await run_pipeline([stage], "question")

    assert result.status == "completed"
    assert result.output == {"ok": "ok:question"}
    assert result.errors == ("compare.bad: boom",)


async def test_parallel_require_all_fails_the_stage_on_a_branch_error() -> None:
    """``require_all`` (default): any branch failure fails the whole stage, attempts recorded."""
    stage = ParallelStage(
        name="compare",
        branches={
            "ok": TypedStage("ok", lambda value: f"ok:{value}"),
            "bad": TypedStage("bad", lambda value: (_ for _ in ()).throw(RuntimeError("boom"))),
        },
    )

    result = await run_pipeline([stage], "question")

    assert result.status == "failed"
    assert result.failed_stage == "compare"
    assert any("bad" in err and "boom" in err for err in result.errors)
    assert result.attempts.get("compare.bad") == 1


async def test_parallel_branches_share_pipeline_context() -> None:
    """Branches write to the single shared context; the joiner reads their artifacts/messages."""

    def fast_branch(value: str, context: PipelineContext) -> str:
        context.write_artifact("fast_notes", {"source": "fast", "input": value})
        context.add_message("fast", "candidate ready")
        return "fast-candidate"

    def deep_branch(value: str, context: PipelineContext) -> str:
        context.write_artifact("deep_notes", {"source": "deep", "input": value})
        return "deep-candidate"

    def join(outputs: dict[str, str], context: PipelineContext) -> dict[str, Any]:
        return {
            "outputs": outputs,
            "artifacts": context.artifacts,
            "messages": tuple(context.messages),
        }

    stage = ParallelStage(
        name="compare",
        branches={
            "fast": TypedStage("fast", fast_branch),
            "deep": TypedStage("deep", deep_branch),
        },
        joiner=join,
    )

    result = await run_pipeline([stage], "question")

    assert result.status == "completed"
    assert result.output["outputs"] == {"fast": "fast-candidate", "deep": "deep-candidate"}
    assert result.output["artifacts"]["fast_notes"]["input"] == "question"
    assert result.output["messages"] == ({"from": "fast", "content": "candidate ready"},)


async def test_parallel_emits_branch_events() -> None:
    """The stage emits ordered fork/join events (parallel_start / branch_* / parallel_join)."""
    events: list[tuple[str, dict[str, Any]]] = []

    async def sink(name: str, data: dict[str, Any]) -> None:
        events.append((name, data))

    stage = ParallelStage(
        name="compare",
        branches={"fast": TypedStage("fast", lambda value: value)},
        joiner=lambda outputs: outputs,
    )

    await run_pipeline([stage], "q", event_sink=sink)

    names = [name for name, _ in events]
    assert "parallel_start" in names
    assert "branch_start" in names
    assert "branch_end" in names
    assert "parallel_join" in names


async def test_parallel_require_all_surfaces_per_branch_errors() -> None:
    """A require_all failure keeps the per-branch error detail in result.errors, not just a summary."""
    stage = ParallelStage(
        name="compare",
        branches={
            "a": TypedStage("a", lambda value: (_ for _ in ()).throw(RuntimeError("boom"))),
            "b": TypedStage("b", lambda value: (_ for _ in ()).throw(RuntimeError("boom"))),
        },
    )

    result = await run_pipeline([stage], "q")

    assert result.status == "failed"
    assert "compare.a: boom" in result.errors
    assert "compare.b: boom" in result.errors


async def test_branch_end_event_carries_error_on_failure() -> None:
    """A failing branch's branch_end event keeps the legacy ``error`` key (failure attribution)."""
    events: list[tuple[str, dict[str, Any]]] = []

    async def sink(name: str, data: dict[str, Any]) -> None:
        events.append((name, data))

    stage = ParallelStage(
        name="compare",
        branches={
            "ok": TypedStage("ok", lambda value: value),
            "bad": TypedStage("bad", lambda value: (_ for _ in ()).throw(RuntimeError("nope"))),
        },
        failure_policy="allow_partial",
    )

    await run_pipeline([stage], "q", event_sink=sink)

    bad_ends = [
        data
        for name, data in events
        if name == "branch_end" and data.get("branch") == "bad"
    ]
    assert bad_ends == [{"stage": "compare", "branch": "bad", "ok": False, "error": "nope"}]


async def test_parallel_requires_at_least_one_branch() -> None:
    """An empty branch map is a configuration error caught at construction."""
    try:
        ParallelStage(name="empty", branches={})
    except StageConfigError as exc:
        assert "branch" in str(exc).lower()
    else:  # pragma: no cover - the constructor must reject
        raise AssertionError("expected StageConfigError for empty branches")
