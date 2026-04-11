"""Unit: EvalRunner and reporters."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock


from swarmline.eval.runner import EvalRunner
from swarmline.eval.reporters import ConsoleReporter, JsonReporter
from swarmline.eval.scorers import ContainsScorer, ExactMatchScorer
from swarmline.eval.types import EvalCase, EvalReport, ScorerResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_agent(responses: dict[str, str] | None = None) -> MagicMock:
    """Create a mock agent that returns canned responses."""
    agent = MagicMock()
    _responses = responses or {}

    async def _query(prompt: str) -> MagicMock:
        result = MagicMock()
        result.text = _responses.get(prompt, "default response")
        result.ok = True
        result.error = None
        return result

    agent.query = AsyncMock(side_effect=_query)
    return agent


def _cases() -> list[EvalCase]:
    return [
        EvalCase(id="c1", input="capital of France", expected="Paris"),
        EvalCase(id="c2", input="2+2", expected="4"),
        EvalCase(id="c3", input="color of sky", expected="blue"),
    ]


# ---------------------------------------------------------------------------
# EvalRunner
# ---------------------------------------------------------------------------


class TestEvalRunner:

    async def test_runs_all_cases(self) -> None:
        agent = _mock_agent({
            "capital of France": "Paris",
            "2+2": "4",
            "color of sky": "The sky is blue",
        })
        runner = EvalRunner()
        report = await runner.run(
            agent=agent,
            suite=_cases(),
            scorers=[ExactMatchScorer()],
        )
        assert report.total == 3
        assert agent.query.call_count == 3

    async def test_applies_all_scorers(self) -> None:
        agent = _mock_agent({"capital of France": "Paris is the capital"})
        runner = EvalRunner()
        report = await runner.run(
            agent=agent,
            suite=[EvalCase(id="c1", input="capital of France", expected="Paris")],
            scorers=[ExactMatchScorer(), ContainsScorer()],
        )
        result = report.results[0]
        assert "exact_match" in result.scores
        assert "contains" in result.scores
        assert result.scores["exact_match"].score == 0.0  # not exact
        assert result.scores["contains"].score == 1.0  # contains "Paris"

    async def test_handles_agent_error(self) -> None:
        agent = MagicMock()
        agent.query = AsyncMock(side_effect=RuntimeError("boom"))
        runner = EvalRunner()
        report = await runner.run(
            agent=agent,
            suite=[EvalCase(id="c1", input="test", expected="ok")],
            scorers=[ExactMatchScorer()],
        )
        assert report.total == 1
        assert report.results[0].error is not None
        assert "boom" in report.results[0].error

    async def test_records_latency(self) -> None:
        agent = _mock_agent({"hi": "hello"})
        runner = EvalRunner()
        report = await runner.run(
            agent=agent,
            suite=[EvalCase(id="c1", input="hi", expected="hello")],
            scorers=[ExactMatchScorer()],
        )
        assert report.results[0].latency_ms >= 0

    async def test_pass_rate(self) -> None:
        agent = _mock_agent({
            "capital of France": "Paris",
            "2+2": "wrong answer",
        })
        runner = EvalRunner()
        report = await runner.run(
            agent=agent,
            suite=[
                EvalCase(id="c1", input="capital of France", expected="Paris"),
                EvalCase(id="c2", input="2+2", expected="4"),
            ],
            scorers=[ExactMatchScorer()],
        )
        assert report.passed == 1
        assert report.failed == 1

    async def test_empty_suite(self) -> None:
        agent = _mock_agent()
        runner = EvalRunner()
        report = await runner.run(agent=agent, suite=[], scorers=[ExactMatchScorer()])
        assert report.total == 0
        assert report.pass_rate == 0.0

    async def test_returns_eval_report(self) -> None:
        agent = _mock_agent({"hi": "hi"})
        runner = EvalRunner()
        report = await runner.run(
            agent=agent,
            suite=[EvalCase(id="c1", input="hi", expected="hi")],
            scorers=[ExactMatchScorer()],
        )
        assert isinstance(report, EvalReport)


# ---------------------------------------------------------------------------
# Reporters
# ---------------------------------------------------------------------------


class TestConsoleReporter:

    def test_format_report(self) -> None:
        from swarmline.eval.types import EvalResult

        case = EvalCase(id="c1", input="hi", expected="hello")
        result = EvalResult(
            case=case,
            output="hello",
            scores={"exact": ScorerResult(score=1.0, reason="match")},
        )
        report = EvalReport(results=(result,))
        reporter = ConsoleReporter()
        output = reporter.format(report)
        assert "c1" in output
        assert "1.0" in output or "100" in output

    def test_format_empty_report(self) -> None:
        report = EvalReport(results=())
        reporter = ConsoleReporter()
        output = reporter.format(report)
        assert "0" in output


class TestJsonReporter:

    def test_format_returns_valid_json(self) -> None:
        from swarmline.eval.types import EvalResult

        case = EvalCase(id="c1", input="hi", expected="hello")
        result = EvalResult(
            case=case,
            output="hello",
            scores={"exact": ScorerResult(score=0.9, reason="close")},
        )
        report = EvalReport(results=(result,))
        reporter = JsonReporter()
        output = reporter.format(report)
        data = json.loads(output)
        assert data["total"] == 1
        assert "results" in data

    def test_format_empty(self) -> None:
        report = EvalReport(results=())
        reporter = JsonReporter()
        data = json.loads(reporter.format(report))
        assert data["total"] == 0
