"""Тесты InMemoryPlanStore — TDD: RED → GREEN.

CRUD операции, edge cases, multi-tenant.
"""

from __future__ import annotations

from datetime import datetime, timezone

from cognitia.orchestration.types import Plan, PlanStep


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _make_plan(plan_id: str = "p1", goal: str = "test") -> Plan:
    return Plan(
        id=plan_id,
        goal=goal,
        steps=[PlanStep(id="s1", description="step 1"), PlanStep(id="s2", description="step 2")],
        created_at=_now(),
    )


class TestInMemoryPlanStoreCRUD:
    """Базовые CRUD операции."""

    async def test_save_and_load(self) -> None:
        from cognitia.orchestration.plan_store import InMemoryPlanStore

        store = InMemoryPlanStore()
        plan = _make_plan()
        await store.save(plan)

        loaded = await store.load("p1")
        assert loaded is not None
        assert loaded.id == "p1"
        assert loaded.goal == "test"

    async def test_load_nonexistent(self) -> None:
        from cognitia.orchestration.plan_store import InMemoryPlanStore

        store = InMemoryPlanStore()
        result = await store.load("missing")
        assert result is None

    async def test_list_plans(self) -> None:
        from cognitia.orchestration.plan_store import InMemoryPlanStore

        store = InMemoryPlanStore()
        plan1 = _make_plan("p1", "goal 1")
        plan2 = _make_plan("p2", "goal 2")

        store.set_namespace("u1", "t1")
        await store.save(plan1)
        await store.save(plan2)

        plans = await store.list_plans(user_id="u1", topic_id="t1")
        assert len(plans) == 2

    async def test_update_step(self) -> None:
        from cognitia.orchestration.plan_store import InMemoryPlanStore

        store = InMemoryPlanStore()
        plan = _make_plan()
        await store.save(plan)

        updated_step = PlanStep(id="s1", description="step 1").complete("done")
        await store.update_step("p1", updated_step)

        loaded = await store.load("p1")
        assert loaded is not None
        assert loaded.steps[0].status == "completed"
        assert loaded.steps[1].status == "pending"

    async def test_save_overwrites(self) -> None:
        """Повторный save перезаписывает план."""
        from cognitia.orchestration.plan_store import InMemoryPlanStore

        store = InMemoryPlanStore()
        plan = _make_plan()
        await store.save(plan)

        updated = plan.approve(by="system")
        await store.save(updated)

        loaded = await store.load("p1")
        assert loaded is not None
        assert loaded.status == "approved"

    async def test_update_step_missing_plan(self) -> None:
        """update_step для несуществующего плана → graceful."""
        from cognitia.orchestration.plan_store import InMemoryPlanStore

        store = InMemoryPlanStore()
        step = PlanStep(id="s1", description="x").complete("y")
        # Не бросает исключение
        await store.update_step("missing", step)

    async def test_isinstance_protocol(self) -> None:
        from cognitia.orchestration.plan_store import InMemoryPlanStore
        from cognitia.orchestration.protocols import PlanStore

        store = InMemoryPlanStore()
        assert isinstance(store, PlanStore)
