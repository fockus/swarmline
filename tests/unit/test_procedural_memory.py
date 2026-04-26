"""Unit: procedural memory — learned tool sequences."""

from __future__ import annotations

from swarmline.memory.procedural_types import Procedure, ProcedureStep, ProceduralMemory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _proc(
    id: str = "p1",
    name: str = "Web Research",
    trigger: str = "research task",
    steps: tuple[ProcedureStep, ...] = (),
    tags: tuple[str, ...] = (),
    success: int = 0,
    failure: int = 0,
) -> Procedure:
    if not steps:
        steps = (
            ProcedureStep(tool_name="web_search", args_template={"query": "{topic}"}),
            ProcedureStep(tool_name="summarize", expected_outcome="summary text"),
        )
    return Procedure(
        id=id,
        name=name,
        description=f"Procedure: {name}",
        trigger=trigger,
        steps=steps,
        success_count=success,
        failure_count=failure,
        tags=tags,
    )


# ---------------------------------------------------------------------------
# Type tests
# ---------------------------------------------------------------------------


class TestProcedureTypes:
    def test_procedure_step_creation(self) -> None:
        step = ProcedureStep(tool_name="web_search", args_template={"q": "{query}"})
        assert step.tool_name == "web_search"
        assert step.args_template["q"] == "{query}"

    def test_procedure_success_rate(self) -> None:
        p = _proc(success=8, failure=2)
        assert abs(p.success_rate - 0.8) < 0.01

    def test_procedure_success_rate_zero(self) -> None:
        p = _proc()
        assert p.success_rate == 0.0

    def test_procedure_total_uses(self) -> None:
        p = _proc(success=5, failure=3)
        assert p.total_uses == 8

    def test_frozen(self) -> None:
        p = _proc()
        try:
            p.name = "changed"  # type: ignore[misc]
            assert False, "should be frozen"
        except AttributeError:
            pass


# ---------------------------------------------------------------------------
# InMemory implementation tests
# ---------------------------------------------------------------------------


class TestInMemoryProceduralMemory:
    async def _store(self):
        from swarmline.memory.procedural import InMemoryProceduralMemory

        return InMemoryProceduralMemory()

    async def test_store_and_count(self) -> None:
        store = await self._store()
        assert await store.count() == 0
        await store.store(_proc("p1"))
        assert await store.count() == 1

    async def test_get(self) -> None:
        store = await self._store()
        await store.store(_proc("p1", name="Research"))
        result = await store.get("p1")
        assert result is not None
        assert result.name == "Research"

    async def test_get_missing(self) -> None:
        store = await self._store()
        assert await store.get("nonexistent") is None

    async def test_suggest_by_trigger(self) -> None:
        store = await self._store()
        await store.store(_proc("p1", trigger="research task about science"))
        await store.store(_proc("p2", trigger="code debugging session"))
        results = await store.suggest("research task")
        assert len(results) >= 1
        assert results[0].id == "p1"

    async def test_suggest_top_k(self) -> None:
        store = await self._store()
        for i in range(10):
            await store.store(_proc(f"p{i}", trigger=f"coding task {i}"))
        results = await store.suggest("coding", top_k=3)
        assert len(results) <= 3

    async def test_suggest_ranks_by_success(self) -> None:
        store = await self._store()
        await store.store(_proc("low", trigger="data analysis", success=1, failure=9))
        await store.store(
            _proc("high", trigger="data analysis task", success=9, failure=1)
        )
        results = await store.suggest("data analysis")
        assert results[0].id == "high"

    async def test_record_outcome_success(self) -> None:
        store = await self._store()
        await store.store(_proc("p1", success=5, failure=0))
        await store.record_outcome("p1", success=True)
        p = await store.get("p1")
        assert p is not None
        assert p.success_count == 6

    async def test_record_outcome_failure(self) -> None:
        store = await self._store()
        await store.store(_proc("p1", success=5, failure=2))
        await store.record_outcome("p1", success=False)
        p = await store.get("p1")
        assert p is not None
        assert p.failure_count == 3

    async def test_record_outcome_missing_noop(self) -> None:
        store = await self._store()
        await store.record_outcome("missing", success=True)  # should not raise

    async def test_suggest_empty_store(self) -> None:
        store = await self._store()
        results = await store.suggest("anything")
        assert results == []

    async def test_implements_protocol(self) -> None:
        store = await self._store()
        assert isinstance(store, ProceduralMemory)
