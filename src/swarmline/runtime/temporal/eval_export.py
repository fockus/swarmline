"""Eval trace export — score production Temporal runs with the eval module.

A completed ``AgentLoopWorkflow`` returns an :class:`AgentRunResult` that
already carries everything the eval module needs: the input conversation is
addressable by run id, the final text is the output, tool usage and errors
are recorded. These helpers convert results into ``eval`` types so
``Scorer`` implementations work on real production runs, not just synthetic
suites::

    from swarmline.runtime.temporal.eval_export import (
        fetch_run_result, run_to_eval_result, score_run_results,
    )

    result = await fetch_run_result(client, options, run_id)
    trace = run_to_eval_result(run_id, "original question", result)
    report = await score_run_results([trace], scorers=[my_scorer])

Pure converters need nothing but the payload dataclasses;
``fetch_run_result`` needs a Temporal client (completed workflows keep
their result in history — no worker required to read it).
"""

from __future__ import annotations

from typing import Any

from swarmline.eval.types import EvalCase, EvalReport, EvalResult, ScorerResult
from swarmline.runtime.temporal.client import workflow_id_for_run
from swarmline.runtime.temporal.options import TemporalRuntimeOptions
from swarmline.runtime.temporal.payloads import AgentRunResult

__all__ = [
    "fetch_run_result",
    "run_to_eval_case",
    "run_to_eval_result",
    "score_run_results",
]


def run_to_eval_case(
    run_id: str,
    input_text: str,
    *,
    expected: str | None = None,
    tags: tuple[str, ...] = ("temporal-run",),
) -> EvalCase:
    """An ``EvalCase`` describing one production run."""
    return EvalCase(id=run_id, input=input_text, expected=expected, tags=tags)


def run_to_eval_result(
    run_id: str,
    input_text: str,
    result: AgentRunResult,
    *,
    expected: str | None = None,
) -> EvalResult:
    """Convert a workflow result into an unscored ``EvalResult`` trace.

    Failed runs carry ``error`` (so ``passed`` is False); tool usage and
    iteration counts land in the case context for scorers that want them.
    """
    case = EvalCase(
        id=run_id,
        input=input_text,
        expected=expected,
        context={
            "iterations": result.iterations,
            "tool_calls": result.tool_calls,
            "event_types": [e.get("type", "") for e in result.events],
        },
        tags=("temporal-run",),
    )
    error: str | None = None
    if result.status != "ok":
        error = f"{result.error_kind}: {result.error_message}"
    return EvalResult(case=case, output=result.text, error=error)


async def score_run_results(
    traces: list[EvalResult],
    scorers: list[Any],
    *,
    pass_threshold: float = 0.5,
) -> EvalReport:
    """Apply scorers to already-executed run traces and build a report.

    The offline counterpart of ``EvalRunner.run`` — outputs come from
    production workflows instead of fresh agent queries.
    """
    scored: list[EvalResult] = []
    for trace in traces:
        scores: dict[str, ScorerResult] = {}
        if trace.error is None:
            for scorer in scorers:
                try:
                    scores[scorer.name] = await scorer.score(trace.case, trace.output)
                except Exception as exc:  # noqa: BLE001 — mirror EvalRunner's tolerance
                    scores[scorer.name] = ScorerResult(
                        score=0.0, reason=f"scorer error: {exc}"
                    )
        scored.append(
            EvalResult(
                case=trace.case,
                output=trace.output,
                scores=scores,
                error=trace.error,
                latency_ms=trace.latency_ms,
            )
        )
    return EvalReport(results=tuple(scored), pass_threshold=pass_threshold)


async def fetch_run_result(
    client: Any,
    options: TemporalRuntimeOptions,
    run_id: str,
) -> AgentRunResult:
    """Fetch a completed run's result from Temporal by ``run_id``."""
    handle = client.get_workflow_handle(
        workflow_id_for_run(options, run_id), result_type=AgentRunResult
    )
    return await handle.result()
