#!/usr/bin/env python3
"""Example 32: Agent Evaluation Framework.

Demonstrates how to evaluate an agent's quality using
EvalRunner with multiple scorers and reporters.

Usage:
    python examples/32_agent_evaluation.py
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from swarmline.eval.reporters import ConsoleReporter, JsonReporter
from swarmline.eval.runner import EvalRunner
from swarmline.eval.scorers import ContainsScorer, CostScorer, ExactMatchScorer, LatencyScorer
from swarmline.eval.types import EvalCase


def create_mock_agent() -> MagicMock:
    """Create a mock agent for demonstration."""
    responses = {
        "What is the capital of France?": "The capital of France is Paris.",
        "What is 2+2?": "4",
        "What is the capital of Japan?": "Tokyo is the capital of Japan.",
        "Who painted the Mona Lisa?": "Leonardo da Vinci painted the Mona Lisa.",
        "What is the speed of light?": "Approximately 300,000 km/s.",
    }
    agent = MagicMock()

    async def query(prompt: str) -> MagicMock:
        result = MagicMock()
        result.text = responses.get(prompt, "I don't know.")
        result.ok = True
        return result

    agent.query = AsyncMock(side_effect=query)
    return agent


# Define evaluation suite
EVAL_SUITE = [
    EvalCase(
        id="geo-france",
        input="What is the capital of France?",
        expected="Paris",
        context={"latency_ms": 120, "cost_usd": 0.002},
        tags=("geography", "easy"),
    ),
    EvalCase(
        id="math-basic",
        input="What is 2+2?",
        expected="4",
        context={"latency_ms": 50, "cost_usd": 0.001},
        tags=("math", "easy"),
    ),
    EvalCase(
        id="geo-japan",
        input="What is the capital of Japan?",
        expected="Tokyo",
        context={"latency_ms": 180, "cost_usd": 0.003},
        tags=("geography", "easy"),
    ),
    EvalCase(
        id="art-mona-lisa",
        input="Who painted the Mona Lisa?",
        expected="da Vinci",
        context={"latency_ms": 250, "cost_usd": 0.004},
        tags=("art", "medium"),
    ),
    EvalCase(
        id="science-light",
        input="What is the speed of light?",
        expected="300,000",
        context={"latency_ms": 300, "cost_usd": 0.005},
        tags=("science", "medium"),
    ),
]


async def main() -> None:
    agent = create_mock_agent()

    # Configure scorers
    scorers = [
        ExactMatchScorer(),
        ContainsScorer(),
        LatencyScorer(max_ms=500),
        CostScorer(max_cost_usd=0.01),
    ]

    # Run evaluation
    runner = EvalRunner()
    report = await runner.run(agent=agent, suite=EVAL_SUITE, scorers=scorers)

    # Console report
    print(ConsoleReporter().format(report))
    print()

    # JSON report (useful for CI/CD)
    print("--- JSON Report ---")
    print(JsonReporter(indent=2).format(report))


if __name__ == "__main__":
    asyncio.run(main())
