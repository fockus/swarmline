"""Evaluation runner — executes eval suites against agents."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from swarmline.eval.types import EvalCase, EvalReport, EvalResult, ScorerResult

if TYPE_CHECKING:
    pass


class EvalRunner:
    """Runs evaluation suites against a Swarmline agent.

    For each case in the suite:
    1. Sends the input to the agent via agent.query()
    2. Applies all scorers to the (case, output) pair
    3. Records latency and any errors
    4. Aggregates into an EvalReport
    """

    async def run(
        self,
        agent: Any,
        suite: list[EvalCase],
        scorers: list[Any],
    ) -> EvalReport:
        """Run all cases through the agent and score the outputs."""
        results: list[EvalResult] = []

        for case in suite:
            result = await self._run_case(agent, case, scorers)
            results.append(result)

        return EvalReport(results=tuple(results))

    async def _run_case(
        self,
        agent: Any,
        case: EvalCase,
        scorers: list[Any],
    ) -> EvalResult:
        """Run a single case and return its result."""
        start = time.monotonic()
        output = ""
        error: str | None = None

        try:
            result = await agent.query(case.input)
            output = result.text or ""
        except Exception as exc:
            error = str(exc)

        latency_ms = (time.monotonic() - start) * 1000

        scores: dict[str, ScorerResult] = {}
        if error is None:
            for scorer in scorers:
                try:
                    sr = await scorer.score(case, output)
                    scores[scorer.name] = sr
                except Exception as exc:
                    scores[scorer.name] = ScorerResult(
                        score=0.0,
                        reason=f"scorer error: {exc}",
                    )

        return EvalResult(
            case=case,
            output=output,
            scores=scores,
            error=error,
            latency_ms=latency_ms,
        )
