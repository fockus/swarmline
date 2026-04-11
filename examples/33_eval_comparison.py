#!/usr/bin/env python3
"""Example 33: A/B Eval Comparison.

Demonstrates comparing evaluation results between two agent configurations
(e.g., different models, prompts, or temperature settings).

Usage:
    python examples/33_eval_comparison.py
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from swarmline.eval.compare import EvalComparator
from swarmline.eval.runner import EvalRunner
from swarmline.eval.scorers import ContainsScorer, ExactMatchScorer
from swarmline.eval.types import EvalCase


SUITE = [
    EvalCase(id="geo-1", input="Capital of France?", expected="Paris"),
    EvalCase(id="math-1", input="What is 2+2?", expected="4"),
    EvalCase(id="geo-2", input="Capital of Japan?", expected="Tokyo"),
    EvalCase(id="science-1", input="Boiling point of water?", expected="100"),
]


def _mock_agent(responses: dict[str, str]) -> MagicMock:
    agent = MagicMock()

    async def query(prompt: str) -> MagicMock:
        r = MagicMock()
        r.text = responses.get(prompt, "I don't know")
        r.ok = True
        return r

    agent.query = AsyncMock(side_effect=query)
    return agent


async def main() -> None:
    # "Model A" — mediocre answers
    agent_a = _mock_agent({
        "Capital of France?": "I think it's Paris, the city of lights.",
        "What is 2+2?": "4",
        "Capital of Japan?": "Kyoto maybe?",
        "Boiling point of water?": "Around 100 degrees.",
    })

    # "Model B" — improved answers
    agent_b = _mock_agent({
        "Capital of France?": "Paris",
        "What is 2+2?": "4",
        "Capital of Japan?": "Tokyo",
        "Boiling point of water?": "100 degrees Celsius at sea level.",
    })

    scorers = [ExactMatchScorer(), ContainsScorer()]
    runner = EvalRunner()

    report_a = await runner.run(agent=agent_a, suite=SUITE, scorers=scorers)
    report_b = await runner.run(agent=agent_b, suite=SUITE, scorers=scorers)

    print("=== Model A ===")
    print(f"Pass rate: {report_a.pass_rate:.0%}, Mean: {report_a.mean_score:.2f}\n")

    print("=== Model B ===")
    print(f"Pass rate: {report_b.pass_rate:.0%}, Mean: {report_b.mean_score:.2f}\n")

    # Compare
    diff = EvalComparator.compare(report_a, report_b)
    print("=== A/B Comparison ===")
    print(diff.format_summary())


if __name__ == "__main__":
    asyncio.run(main())
