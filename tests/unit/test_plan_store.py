"""Contract tests for PlanStore backends: InMemory, SQLite, PostgreSQL.

TDD: tests must pass for ANY correct PlanStore implementation.
Backends are parametrized via fixtures.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from swarmline.orchestration.plan_store import (
    InMemoryPlanStore,
    _dict_to_step,
    _plan_to_row,
    _row_to_plan,
    _step_to_dict,
)
from swarmline.orchestration.types import Plan, PlanStep


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _make_plan(plan_id: str = "p1", goal: str = "test") -> Plan:
    return Plan(
        id=plan_id,
        goal=goal,
        steps=[PlanStep(id="s1", description="step 1"), PlanStep(id="s2", description="step 2")],
        created_at=_now(),
    )


def _make_plan_with_substeps() -> Plan:
    """Plan with nested substeps and DoD criteria."""
    return Plan(
        id="complex",
        goal="complex goal",
        steps=[
            PlanStep(
                id="s1",
                description="parent step",
                dod_criteria=("criterion A", "criterion B"),
                substeps=[
                    PlanStep(id="s1.1", description="child step 1"),
                    PlanStep(id="s1.2", description="child step 2", dod_criteria=("nested DoD",)),
                ],
            ),
            PlanStep(id="s2", description="simple step"),
        ],
        created_at=_now(),
    )


# ---------------------------------------------------------------------------
# Serialization roundtrip tests
# ---------------------------------------------------------------------------


class TestSerialization:
    """Tests for _step_to_dict / _dict_to_step / _plan_to_row / _row_to_plan."""

    def test_step_roundtrip_simple(self) -> None:
        """Simple PlanStep survives serialization roundtrip."""
        step = PlanStep(id="s1", description="do thing", status="completed", result="done")
        data = _step_to_dict(step)
        restored = _dict_to_step(data)
        assert restored.id == step.id
        assert restored.description == step.description
        assert restored.status == step.status
        assert restored.result == step.result

    def test_step_roundtrip_with_substeps(self) -> None:
        """PlanStep with nested substeps survives roundtrip."""
        step = PlanStep(
            id="parent",
            description="parent",
            substeps=[
                PlanStep(id="child1", description="c1"),
                PlanStep(
                    id="child2",
                    description="c2",
                    substeps=[PlanStep(id="grandchild", description="gc")],
                ),
            ],
        )
        data = _step_to_dict(step)
        restored = _dict_to_step(data)
        assert len(restored.substeps) == 2
        assert restored.substeps[1].substeps[0].id == "grandchild"

    def test_step_roundtrip_with_dod(self) -> None:
        """DoD criteria and verification state survive roundtrip."""
        step = PlanStep(
            id="s1",
            description="d",
            dod_criteria=("A", "B", "C"),
            dod_verified=True,
            verification_log="all good",
        )
        data = _step_to_dict(step)
        restored = _dict_to_step(data)
        assert restored.dod_criteria == ("A", "B", "C")
        assert restored.dod_verified is True
        assert restored.verification_log == "all good"

    def test_plan_to_row_and_back(self) -> None:
        """Plan → row dict → Plan roundtrip via mock row."""
        plan = _make_plan_with_substeps()
        row_dict = _plan_to_row(plan, "user1", "topic1")

        # Simulate a DB row as a namedtuple-like object
        class FakeRow:
            pass

        fake = FakeRow()
        for k, v in row_dict.items():
            setattr(fake, k, v)

        restored = _row_to_plan(fake)
        assert restored.id == plan.id
        assert restored.goal == plan.goal
        assert restored.status == plan.status
        assert restored.approved_by == plan.approved_by
        assert len(restored.steps) == 2
        assert len(restored.steps[0].substeps) == 2
        assert restored.steps[0].dod_criteria == ("criterion A", "criterion B")

    def test_plan_approved_by_survives_roundtrip(self) -> None:
        """approved_by field persists through serialization."""
        plan = _make_plan().approve(by="user")
        row_dict = _plan_to_row(plan, "", "")

        class FakeRow:
            pass

        fake = FakeRow()
        for k, v in row_dict.items():
            setattr(fake, k, v)

        restored = _row_to_plan(fake)
        assert restored.approved_by == "user"
        assert restored.status == "approved"


# ---------------------------------------------------------------------------
# Contract tests (parametrized by backend)
# ---------------------------------------------------------------------------


@pytest.fixture(params=["inmemory", "sqlite"])
async def plan_store(request: pytest.FixtureRequest, tmp_path):
    """Create a PlanStore backend for testing."""
    if request.param == "inmemory":
        store = InMemoryPlanStore()
        store.set_namespace("u1", "t1")
        yield store

    elif request.param == "sqlite":
        pytest.importorskip("aiosqlite", reason="aiosqlite not installed")
        pytest.importorskip("sqlalchemy", reason="sqlalchemy not installed")
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from swarmline.orchestration.plan_store import SQLITE_PLAN_SCHEMA, SQLitePlanStore

        db_path = tmp_path / "test_plans.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        sf = async_sessionmaker(engine, expire_on_commit=False)

        # Create schema
        async with sf() as session:
            for stmt in SQLITE_PLAN_SCHEMA.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    await session.execute(text(stmt))
            await session.commit()

        store = SQLitePlanStore(sf)
        store.set_namespace("u1", "t1")
        yield store

        await engine.dispose()


class TestPlanStoreContract:
    """Contract tests that must pass for ANY PlanStore implementation."""

    async def test_save_and_load(self, plan_store) -> None:
        """Save a plan and load it back."""
        plan = _make_plan()
        await plan_store.save(plan)

        loaded = await plan_store.load("p1")
        assert loaded is not None
        assert loaded.id == "p1"
        assert loaded.goal == "test"
        assert len(loaded.steps) == 2

    async def test_load_nonexistent(self, plan_store) -> None:
        """Loading a nonexistent plan returns None."""
        result = await plan_store.load("missing")
        assert result is None

    async def test_save_overwrites(self, plan_store) -> None:
        """Saving an existing plan overwrites it."""
        plan = _make_plan()
        await plan_store.save(plan)

        updated = plan.approve(by="system")
        await plan_store.save(updated)

        loaded = await plan_store.load("p1")
        assert loaded is not None
        assert loaded.status == "approved"

    async def test_list_plans_by_namespace(self, plan_store) -> None:
        """list_plans filters by (user_id, topic_id)."""
        plan1 = _make_plan("p1", "goal 1")
        plan2 = _make_plan("p2", "goal 2")
        await plan_store.save(plan1)
        await plan_store.save(plan2)

        plans = await plan_store.list_plans(user_id="u1", topic_id="t1")
        assert len(plans) == 2

    async def test_list_plans_empty(self, plan_store) -> None:
        """list_plans returns empty list when no plans match."""
        plans = await plan_store.list_plans(user_id="nonexistent", topic_id="")
        assert plans == []

    async def test_update_step(self, plan_store) -> None:
        """Atomically update a single step within a plan."""
        plan = _make_plan()
        await plan_store.save(plan)

        completed_step = PlanStep(id="s1", description="step 1").complete("done")
        await plan_store.update_step("p1", completed_step)

        loaded = await plan_store.load("p1")
        assert loaded is not None
        assert loaded.steps[0].status == "completed"
        assert loaded.steps[0].result == "done"
        assert loaded.steps[1].status == "pending"

    async def test_update_step_missing_plan(self, plan_store) -> None:
        """update_step for nonexistent plan is a no-op."""
        step = PlanStep(id="s1", description="x").complete("y")
        await plan_store.update_step("missing", step)  # no exception

    async def test_isinstance_protocol(self, plan_store) -> None:
        """Store implements PlanStore protocol."""
        from swarmline.orchestration.protocols import PlanStore

        assert isinstance(plan_store, PlanStore)

    async def test_load_respects_current_namespace(self, plan_store) -> None:
        store = plan_store
        plan = _make_plan()
        await store.save(plan)

        store.set_namespace("other", "topic")
        assert await store.load(plan.id) is None

    async def test_update_step_respects_current_namespace(self, plan_store) -> None:
        store = plan_store
        plan = _make_plan()
        await store.save(plan)

        store.set_namespace("other", "topic")
        await store.update_step(plan.id, PlanStep(id="s1", description="step 1").complete("done"))
        assert await store.load(plan.id) is None

    async def test_substeps_persist(self, plan_store) -> None:
        """Nested substeps survive save/load roundtrip."""
        plan = _make_plan_with_substeps()
        await plan_store.save(plan)

        loaded = await plan_store.load("complex")
        assert loaded is not None
        assert len(loaded.steps[0].substeps) == 2
        assert loaded.steps[0].substeps[0].id == "s1.1"
        assert loaded.steps[0].dod_criteria == ("criterion A", "criterion B")

    async def test_approved_by_persists(self, plan_store) -> None:
        """approved_by field persists through save/load."""
        plan = _make_plan().approve(by="user")
        await plan_store.save(plan)

        loaded = await plan_store.load("p1")
        assert loaded is not None
        assert loaded.approved_by == "user"
        assert loaded.status == "approved"

    async def test_multiple_plans_isolation(self, plan_store) -> None:
        """Multiple plans don't interfere with each other."""
        plan_a = _make_plan("a", "goal A")
        plan_b = _make_plan("b", "goal B")
        await plan_store.save(plan_a)
        await plan_store.save(plan_b)

        loaded_a = await plan_store.load("a")
        loaded_b = await plan_store.load("b")
        assert loaded_a is not None
        assert loaded_b is not None
        assert loaded_a.goal == "goal A"
        assert loaded_b.goal == "goal B"
