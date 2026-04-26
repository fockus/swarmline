"""Integration: EvalRunner + multiple scorers + reporters end-to-end."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

from swarmline.eval.reporters import ConsoleReporter, JsonReporter
from swarmline.eval.runner import EvalRunner
from swarmline.eval.scorers import (
    ContainsScorer,
    CostScorer,
    ExactMatchScorer,
    LatencyScorer,
)
from swarmline.eval.types import EvalCase


def _mock_agent(responses: dict[str, str]) -> MagicMock:
    agent = MagicMock()

    async def _query(prompt: str) -> MagicMock:
        result = MagicMock()
        result.text = responses.get(prompt, "unknown")
        result.ok = True
        return result

    agent.query = AsyncMock(side_effect=_query)
    return agent


SUITE = [
    EvalCase(
        id="geography-1",
        input="What is the capital of France?",
        expected="Paris",
        context={"latency_ms": 150, "cost_usd": 0.002},
        tags=("geography",),
    ),
    EvalCase(
        id="math-1",
        input="What is 2+2?",
        expected="4",
        context={"latency_ms": 80, "cost_usd": 0.001},
        tags=("math",),
    ),
    EvalCase(
        id="geography-2",
        input="What is the capital of Japan?",
        expected="Tokyo",
        context={"latency_ms": 200, "cost_usd": 0.003},
        tags=("geography",),
    ),
    EvalCase(
        id="trivia-1",
        input="Who wrote Hamlet?",
        expected="Shakespeare",
        context={"latency_ms": 1200, "cost_usd": 0.01},
        tags=("trivia",),
    ),
]


class TestEvalIntegration:
    async def test_full_eval_pipeline(self) -> None:
        agent = _mock_agent(
            {
                "What is the capital of France?": "The capital of France is Paris.",
                "What is 2+2?": "4",
                "What is the capital of Japan?": "Tokyo is the capital.",
                "Who wrote Hamlet?": "William Shakespeare wrote Hamlet.",
            }
        )

        runner = EvalRunner()
        report = await runner.run(
            agent=agent,
            suite=SUITE,
            scorers=[
                ExactMatchScorer(),
                ContainsScorer(),
                LatencyScorer(max_ms=500),
                CostScorer(max_cost_usd=0.005),
            ],
        )

        assert report.total == 4
        assert report.passed >= 1  # at least math-1 passes exact

        # ContainsScorer should pass for all (all contain expected)
        for result in report.results:
            assert result.scores["contains"].score == 1.0

        # ExactMatchScorer: only "4" is exact
        assert report.results[1].scores["exact_match"].score == 1.0
        assert (
            report.results[0].scores["exact_match"].score == 0.0
        )  # "Paris" != "The capital..."

    async def test_console_reporter_output(self) -> None:
        agent = _mock_agent({"hi": "hello"})
        runner = EvalRunner()
        report = await runner.run(
            agent=agent,
            suite=[EvalCase(id="c1", input="hi", expected="hello")],
            scorers=[ExactMatchScorer()],
        )
        output = ConsoleReporter().format(report)
        assert "c1" in output
        assert "PASS" in output or "FAIL" in output

    async def test_json_reporter_roundtrip(self) -> None:
        agent = _mock_agent({"hi": "hello"})
        runner = EvalRunner()
        report = await runner.run(
            agent=agent,
            suite=[EvalCase(id="c1", input="hi", expected="hello")],
            scorers=[ExactMatchScorer(), ContainsScorer()],
        )
        json_output = JsonReporter().format(report)
        data = json.loads(json_output)
        assert data["total"] == 1
        assert "exact_match" in data["results"][0]["scores"]
        assert "contains" in data["results"][0]["scores"]
        assert "scorer_stats" in data

    async def test_multiple_scorers_all_tracked(self) -> None:
        agent = _mock_agent({"test": "result"})
        runner = EvalRunner()
        report = await runner.run(
            agent=agent,
            suite=[EvalCase(id="c1", input="test", expected="result")],
            scorers=[
                ExactMatchScorer(),
                ContainsScorer(),
                LatencyScorer(),
                CostScorer(),
            ],
        )
        result = report.results[0]
        assert len(result.scores) == 4
        for name in ["exact_match", "contains", "latency", "cost"]:
            assert name in result.scores
