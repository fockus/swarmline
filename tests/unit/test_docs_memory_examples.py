"""Offline example-tests mirroring the doc snippets in docs/memory.md and docs/memory-bank.md.

Stage A4 — Docs for uniques: tiered memory-bank (L0/L1/L2) + procedural memory.
All tests are fully offline (no LLM, no API keys, no network).
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class _DictProvider:
    """Minimal dict-backed MemoryBankProvider for offline tests."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def read_file(self, path: str) -> str | None:
        return self._store.get(path)

    async def write_file(self, path: str, content: str) -> None:
        self._store[path] = content

    async def append_to_file(self, path: str, content: str) -> None:
        self._store[path] = self._store.get(path, "") + content

    async def list_files(self, prefix: str = "") -> list[str]:
        return [p for p in self._store if p.startswith(prefix)]

    async def delete_file(self, path: str) -> None:
        self._store.pop(path, None)


# ---------------------------------------------------------------------------
# Test 1: Public exports importable
# ---------------------------------------------------------------------------


def test_memory_public_exports_are_importable() -> None:
    """Top-level imports from swarmline.memory and swarmline.memory_bank must resolve."""
    from swarmline.memory import InMemoryProceduralMemory, Procedure, ProcedureStep  # noqa: F401
    from swarmline.memory_bank import SimpleTierGenerator, TieredContextManager  # noqa: F401

    assert InMemoryProceduralMemory is not None
    assert Procedure is not None
    assert ProcedureStep is not None
    assert TieredContextManager is not None
    assert SimpleTierGenerator is not None


# ---------------------------------------------------------------------------
# Test 2: success_rate property (doc snippet assertion)
# ---------------------------------------------------------------------------


def test_procedural_memory_example_success_rate_property() -> None:
    """Procedure.success_rate == success_count / total_uses (3/(3+1) == 0.75)."""
    from swarmline.memory import Procedure

    proc = Procedure(
        id="p1",
        name="deploy",
        description="deploy app",
        trigger="deploy app to staging",
        success_count=3,
        failure_count=1,
    )

    assert proc.success_rate == 0.75


def test_procedural_memory_example_success_rate_zero_uses() -> None:
    """success_rate must be 0.0 (not ZeroDivisionError) when total_uses == 0."""
    from swarmline.memory import Procedure

    proc = Procedure(
        id="p0",
        name="new-proc",
        description="never used",
        trigger="new task",
    )

    assert proc.success_rate == 0.0


# ---------------------------------------------------------------------------
# Test 3: Ranking by success_rate (the reinforcement-learning core of procedural memory)
# ---------------------------------------------------------------------------


async def test_procedural_memory_example_ranks_by_success_rate() -> None:
    """suggest() returns the procedure with higher success_rate first when overlap is equal."""
    from swarmline.memory import InMemoryProceduralMemory, Procedure

    memory = InMemoryProceduralMemory()

    # Both procedures share the same trigger words → equal word-overlap with any query
    proc_low = Procedure(
        id="low",
        name="deploy-low",
        description="deploy variant low success",
        trigger="deploy to staging",
    )
    proc_high = Procedure(
        id="high",
        name="deploy-high",
        description="deploy variant high success",
        trigger="deploy to staging",
    )

    await memory.store(proc_low)
    await memory.store(proc_high)

    # proc_high: 3 successes (rate=1.0); proc_low: 1 success (rate=0.5)
    await memory.record_outcome("high", success=True)
    await memory.record_outcome("high", success=True)
    await memory.record_outcome("high", success=True)
    await memory.record_outcome("low", success=True)
    await memory.record_outcome("low", success=False)

    results = await memory.suggest("deploy to staging", top_k=2)

    assert len(results) == 2
    assert results[0].id == "high", "Higher success_rate must rank first"


# ---------------------------------------------------------------------------
# Test 4: TieredContextManager generates L0 and L1 tiers after on_file_written
# ---------------------------------------------------------------------------


async def test_tiered_context_example_generates_tiers_on_write() -> None:
    """After on_file_written, get_tiered returns non-empty L0 and L1 content."""
    from swarmline.memory_bank import SimpleTierGenerator, TieredContextManager

    provider = _DictProvider()
    manager = TieredContextManager(provider, SimpleTierGenerator())

    content = "# Project Status\nPhase: MVP. DB: PostgreSQL. Deploy: Docker."
    # Mirror the docs flow: app writes the original, then the hook fires.
    await provider.write_file("STATUS.md", content)
    await manager.on_file_written("STATUS.md", content)

    l0 = await manager.get_tiered("STATUS.md", "L0")
    l1 = await manager.get_tiered("STATUS.md", "L1")
    l2 = await manager.get_tiered("STATUS.md", "L2")

    assert l0 is not None, "L0 tier must be generated"
    assert len(l0) > 0, "L0 content must be non-empty"
    assert l1 is not None, "L1 tier must be generated"
    assert len(l1) > 0, "L1 content must be non-empty"
    assert l2 == content, "L2 must return the original file content"


# ---------------------------------------------------------------------------
# Test 5: build_context returns index with file entry + L1 detail
# ---------------------------------------------------------------------------


async def test_tiered_context_example_build_context_returns_index_and_detail() -> None:
    """build_context() returns a string with the Memory Bank Index header and file entry."""
    from swarmline.memory_bank import SimpleTierGenerator, TieredContextManager

    provider = _DictProvider()
    manager = TieredContextManager(provider, SimpleTierGenerator())

    content = "# Architecture Decisions\nUse async SQLAlchemy for all DB access."
    await manager.on_file_written("decisions.md", content)

    context = await manager.build_context(budget_tokens=4000)

    assert "Memory Bank Index" in context, "Context must include the L0 index header"
    assert "decisions.md" in context, "Context must reference the written file"
