"""Tests for ConditionalStage — the routing primitive.

A ConditionalStage selects a case key (a dotted path on the value OR a callable) and runs the
matching sub-chain against the SAME input — the branch a strictly-linear pipeline cannot express.
An unmatched key uses ``default``; with no default it fails the pipeline. An early-terminate inside
a branch propagates to the outer run.
"""

from __future__ import annotations

import dataclasses

from swarmline.pipeline.dataflow_engine import run_pipeline
from swarmline.pipeline.stages.conditional_stage import ConditionalStage
from swarmline.pipeline.stages.guard_stage import GuardStage
from swarmline.pipeline.stages.loop import LoopStage
from swarmline.pipeline.stages.parallel import ParallelStage
from swarmline.pipeline.stages.typed_stage import TypedStage


@dataclasses.dataclass(frozen=True)
class _Decision:
    """A tiny stand-in for a turn decision to exercise dotted-path routing on an object."""

    kind: str


def _route_cases() -> dict[str, list[TypedStage]]:
    return {
        "search": [TypedStage("s", lambda v: f"searched:{v.kind}")],
        "answer": [TypedStage("a", lambda v: f"answered:{v.kind}")],
    }


async def test_routes_by_dotted_path_on_object() -> None:
    """selector='kind' reads the attribute off the value object and runs that branch."""
    result = await run_pipeline(
        [ConditionalStage("route", selector="kind", cases=_route_cases())],
        _Decision(kind="search"),
    )

    assert result.output == "searched:search"


async def test_routes_by_dotted_path_on_dict() -> None:
    """selector='kind' reads the key off a dict value (Mapping branch of the resolver)."""
    cases = {"answer": [TypedStage("a", lambda v: f"answered:{v['kind']}")]}
    result = await run_pipeline(
        [ConditionalStage("route", selector="kind", cases=cases)],
        {"kind": "answer", "extra": 1},
    )

    assert result.output == "answered:answer"


async def test_selector_callable_picks_case() -> None:
    """A callable selector returns the case key directly."""
    cases = {"x": [TypedStage("x", lambda v: f"X:{v}")]}
    result = await run_pipeline(
        [ConditionalStage("route", selector=lambda v: "x", cases=cases)],  # noqa: ARG005
        "in",
    )

    assert result.output == "X:in"


async def test_default_branch_used_when_no_case_matches() -> None:
    """An unmatched key falls back to the default sub-chain."""
    result = await run_pipeline(
        [
            ConditionalStage(
                "route",
                selector="kind",
                cases={"search": [TypedStage("s", lambda v: "S")]},  # noqa: ARG005
                default=[TypedStage("d", lambda v: f"default:{v.kind}")],
            )
        ],
        _Decision(kind="weird"),
    )

    assert result.output == "default:weird"


async def test_no_case_and_no_default_fails() -> None:
    """An unmatched key with no default fails the pipeline (routing error)."""
    result = await run_pipeline(
        [
            ConditionalStage(
                "route",
                selector="kind",
                cases={"search": [TypedStage("s", lambda v: "S")]},  # noqa: ARG005
            )
        ],
        _Decision(kind="weird"),
    )

    assert result.status == "failed"
    assert result.failed_stage == "route"


async def test_conditional_propagates_nested_parallel_accounting() -> None:
    """A ParallelStage nested in a branch surfaces its sub_attempts and non-fatal errors upward."""
    parallel = ParallelStage(
        name="par",
        branches={
            "good": TypedStage("good", lambda v: f"ok:{v.kind}"),
            "bad": TypedStage("bad", lambda v: (_ for _ in ()).throw(RuntimeError("boom"))),
        },
        joiner=lambda outputs: outputs,
        failure_policy="allow_partial",
    )
    result = await run_pipeline(
        [ConditionalStage("cond", selector="kind", cases={"go": [parallel]})],
        _Decision(kind="go"),
    )

    assert result.status == "completed"
    assert result.attempts.get("par.good") == 1
    assert result.attempts.get("par.bad") == 1
    assert result.errors == ("par.bad: boom",)


async def test_conditional_branch_failure_propagates_inner_attempts() -> None:
    """A failing LoopStage in a branch fails the conditional with the inner attempt count preserved."""
    loop = LoopStage(
        name="rev",
        body=TypedStage("draft", lambda v: "draft"),
        reviewer=lambda _v: False,
        max_iterations=3,
    )
    result = await run_pipeline(
        [ConditionalStage("cond", selector="kind", cases={"go": [loop]})],
        _Decision(kind="go"),
    )

    assert result.status == "failed"
    assert result.failed_stage == "cond"
    assert result.attempts.get("rev") == 3
    assert result.errors == ("stage 'rev' reviewer did not pass after 3 iterations",)


async def test_early_terminate_in_branch_propagates() -> None:
    """A guard tripping inside a branch terminates the whole run early with its payload."""
    cases = {
        "search": [
            GuardStage("empty", predicate=lambda v: v.kind == "search", on_trip="EMPTY"),
            TypedStage("never", lambda v: "X"),  # noqa: ARG005
        ]
    }
    result = await run_pipeline(
        [ConditionalStage("route", selector="kind", cases=cases)],
        _Decision(kind="search"),
    )

    assert result.terminated_early is True
    assert result.output == "EMPTY"
