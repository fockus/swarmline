#!/usr/bin/env python3
"""Benchmark: context building performance.

Measures how fast context packs are assembled from various sources.

Usage:
    python benchmarks/bench_context.py
"""

from __future__ import annotations

import asyncio
import time

from swarmline.eval.runner import EvalRunner
from swarmline.eval.scorers import ExactMatchScorer, ContainsScorer
from swarmline.eval.types import EvalCase
from unittest.mock import AsyncMock, MagicMock


def _mock_agent(n: int) -> MagicMock:
    agent = MagicMock()
    counter = {"i": 0}

    async def _query(prompt: str) -> MagicMock:
        r = MagicMock()
        r.text = f"response-{counter['i']}"
        r.ok = True
        r.error = None
        counter["i"] += 1
        return r

    agent.query = AsyncMock(side_effect=_query)
    return agent


async def bench_eval_runner(n_cases: int = 100) -> float:
    """Measure eval throughput (cases/sec) with mock agent."""
    suite = [
        EvalCase(id=f"c{i}", input=f"prompt {i}", expected=f"response-{i}")
        for i in range(n_cases)
    ]
    agent = _mock_agent(n_cases)
    runner = EvalRunner()
    scorers = [ExactMatchScorer(), ContainsScorer()]

    start = time.perf_counter()
    await runner.run(agent=agent, suite=suite, scorers=scorers)
    elapsed = time.perf_counter() - start
    return n_cases / elapsed


async def main() -> None:
    print("Swarmline Framework Benchmark")
    print("=" * 50)

    eval_ops = await bench_eval_runner(100)
    print(f"Eval Runner:      {eval_ops:,.0f} cases/sec (100 cases, 2 scorers)")

    eval_ops_large = await bench_eval_runner(500)
    print(f"Eval Runner:      {eval_ops_large:,.0f} cases/sec (500 cases, 2 scorers)")


if __name__ == "__main__":
    asyncio.run(main())
