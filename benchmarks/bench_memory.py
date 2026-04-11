#!/usr/bin/env python3
"""Benchmark: memory provider throughput.

Measures write and read operations per second for each memory backend.

Usage:
    python benchmarks/bench_memory.py
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from swarmline.memory.episodic import InMemoryEpisodicMemory
from swarmline.memory.episodic_types import Episode


async def bench_episodic_write(store: InMemoryEpisodicMemory, n: int = 1000) -> float:
    """Measure episodes/sec for write operations."""
    start = time.perf_counter()
    for i in range(n):
        ep = Episode(
            id=f"ep-{i}",
            summary=f"Benchmark episode {i} with some detail text",
            tools_used=("web_search", "code_sandbox"),
            outcome="success",
            tags=("bench", "test"),
            session_id=f"sess-{i}",
            timestamp=datetime.now(UTC),
        )
        await store.store(ep)
    elapsed = time.perf_counter() - start
    return n / elapsed


async def bench_episodic_recall(store: InMemoryEpisodicMemory, queries: int = 100) -> float:
    """Measure queries/sec for recall operations."""
    start = time.perf_counter()
    for i in range(queries):
        await store.recall(f"benchmark episode {i % 10}", top_k=5)
    elapsed = time.perf_counter() - start
    return queries / elapsed


async def bench_episodic_recent(store: InMemoryEpisodicMemory, n: int = 100) -> float:
    start = time.perf_counter()
    for _ in range(n):
        await store.recall_recent(n=10)
    elapsed = time.perf_counter() - start
    return n / elapsed


async def main() -> None:
    print("Swarmline Memory Benchmark")
    print("=" * 50)

    store = InMemoryEpisodicMemory()

    write_ops = await bench_episodic_write(store, 1000)
    print(f"Episodic Write:   {write_ops:,.0f} ops/sec (1000 episodes)")

    recall_ops = await bench_episodic_recall(store, 100)
    print(f"Episodic Recall:  {recall_ops:,.0f} ops/sec (100 queries, top_k=5)")

    recent_ops = await bench_episodic_recent(store, 100)
    print(f"Episodic Recent:  {recent_ops:,.0f} ops/sec (100 queries, n=10)")


if __name__ == "__main__":
    asyncio.run(main())
