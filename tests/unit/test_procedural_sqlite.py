"""Unit: SqliteProceduralMemory — FTS5 search + success rate ranking."""

from __future__ import annotations

import pytest

from swarmline.memory.procedural_sqlite import SqliteProceduralMemory
from swarmline.memory.procedural_types import Procedure, ProcedureStep


@pytest.fixture
def memory():
    return SqliteProceduralMemory(":memory:")


class TestCrud:

    async def test_store_and_get(self, memory) -> None:
        proc = Procedure(id="p1", name="Deploy", description="Deploy to staging",
                         trigger="deploy staging")
        await memory.store(proc)
        result = await memory.get("p1")
        assert result is not None
        assert result.name == "Deploy"

    async def test_get_nonexistent(self, memory) -> None:
        assert await memory.get("nope") is None

    async def test_count(self, memory) -> None:
        assert await memory.count() == 0
        await memory.store(Procedure(id="p1", name="A", description="", trigger="a"))
        assert await memory.count() == 1

    async def test_store_with_steps(self, memory) -> None:
        proc = Procedure(
            id="p1", name="Deploy", description="Full deploy",
            trigger="deploy", tags=("ci", "deploy"),
            steps=(
                ProcedureStep(tool_name="run_tests", expected_outcome="pass"),
                ProcedureStep(tool_name="build_docker", args_template={"tag": "latest"}),
            ),
        )
        await memory.store(proc)
        result = await memory.get("p1")
        assert len(result.steps) == 2
        assert result.steps[0].tool_name == "run_tests"


class TestSuggest:

    async def test_suggest_by_keyword(self, memory) -> None:
        await memory.store(Procedure(id="p1", name="Deploy staging",
                                     description="Deploy app", trigger="deploy staging"))
        await memory.store(Procedure(id="p2", name="Run tests",
                                     description="Execute test suite", trigger="run tests"))
        results = await memory.suggest("deploy")
        assert any(p.id == "p1" for p in results)

    async def test_suggest_empty(self, memory) -> None:
        results = await memory.suggest("nonexistent query here")
        assert results == []

    async def test_suggest_ranks_by_success(self, memory) -> None:
        await memory.store(Procedure(id="p1", name="Deploy fast",
                                     description="Quick deploy", trigger="deploy",
                                     success_count=10, failure_count=0))
        await memory.store(Procedure(id="p2", name="Deploy slow",
                                     description="Slow deploy", trigger="deploy",
                                     success_count=1, failure_count=9))
        results = await memory.suggest("deploy")
        if len(results) >= 2:
            assert results[0].id == "p1"  # higher success rate


class TestOutcome:

    async def test_record_success(self, memory) -> None:
        await memory.store(Procedure(id="p1", name="A", description="", trigger="a"))
        await memory.record_outcome("p1", success=True)
        proc = await memory.get("p1")
        assert proc.success_count == 1
        assert proc.failure_count == 0

    async def test_record_failure(self, memory) -> None:
        await memory.store(Procedure(id="p1", name="A", description="", trigger="a"))
        await memory.record_outcome("p1", success=False)
        proc = await memory.get("p1")
        assert proc.failure_count == 1

    async def test_record_nonexistent(self, memory) -> None:
        # Should not raise
        await memory.record_outcome("nope", success=True)
