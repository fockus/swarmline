"""Тесты Plan types и state machine — TDD: RED → GREEN.

Контрактные тесты для PlanStep, Plan, PlanStore Protocol.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class TestPlanStep:
    """Валидация PlanStep dataclass."""

    def test_create_step(self) -> None:
        from cognitia.orchestration.types import PlanStep

        step = PlanStep(id="s1", description="Найти вклады")
        assert step.id == "s1"
        assert step.status == "pending"
        assert step.result is None
        assert step.substeps == []

    def test_step_complete(self) -> None:
        from cognitia.orchestration.types import PlanStep

        step = PlanStep(id="s1", description="task")
        updated = step.complete("Найдено 5 вкладов")
        assert updated.status == "completed"
        assert updated.result == "Найдено 5 вкладов"
        # Оригинал не мутировался
        assert step.status == "pending"

    def test_step_fail(self) -> None:
        from cognitia.orchestration.types import PlanStep

        step = PlanStep(id="s1", description="task")
        updated = step.fail("API недоступен")
        assert updated.status == "failed"
        assert updated.result == "API недоступен"

    def test_step_skip(self) -> None:
        from cognitia.orchestration.types import PlanStep

        step = PlanStep(id="s1", description="task")
        updated = step.skip("Не требуется")
        assert updated.status == "skipped"

    def test_step_start(self) -> None:
        from cognitia.orchestration.types import PlanStep

        step = PlanStep(id="s1", description="task")
        updated = step.start()
        assert updated.status == "in_progress"


class TestPlan:
    """Валидация Plan dataclass и state machine."""

    def test_create_plan(self) -> None:
        from cognitia.orchestration.types import Plan, PlanStep

        plan = Plan(
            id="p1",
            goal="Подобрать вклад",
            steps=[PlanStep(id="s1", description="step1")],
            created_at=_now(),
        )
        assert plan.id == "p1"
        assert plan.status == "draft"
        assert plan.approved_by is None
        assert len(plan.steps) == 1

    def test_approve_by_user(self) -> None:
        """draft → approved (by user)."""
        from cognitia.orchestration.types import Plan, PlanStep

        plan = Plan(id="p1", goal="g", steps=[PlanStep(id="s1", description="s")], created_at=_now())
        approved = plan.approve(by="user")
        assert approved.status == "approved"
        assert approved.approved_by == "user"

    def test_approve_by_system(self) -> None:
        """draft → approved (by system = programmatic)."""
        from cognitia.orchestration.types import Plan, PlanStep

        plan = Plan(id="p1", goal="g", steps=[PlanStep(id="s1", description="s")], created_at=_now())
        approved = plan.approve(by="system")
        assert approved.status == "approved"
        assert approved.approved_by == "system"

    def test_approve_by_agent(self) -> None:
        """draft → approved (by agent = auto-approve)."""
        from cognitia.orchestration.types import Plan, PlanStep

        plan = Plan(id="p1", goal="g", steps=[PlanStep(id="s1", description="s")], created_at=_now())
        approved = plan.approve(by="agent")
        assert approved.approved_by == "agent"

    def test_start_execution(self) -> None:
        """approved → executing."""
        from cognitia.orchestration.types import Plan, PlanStep

        plan = Plan(id="p1", goal="g", steps=[PlanStep(id="s1", description="s")], created_at=_now())
        plan = plan.approve(by="system")
        executing = plan.start_execution()
        assert executing.status == "executing"

    def test_complete_plan(self) -> None:
        """executing → completed."""
        from cognitia.orchestration.types import Plan, PlanStep

        plan = Plan(id="p1", goal="g", steps=[PlanStep(id="s1", description="s")], created_at=_now())
        plan = plan.approve(by="system").start_execution()
        completed = plan.mark_completed()
        assert completed.status == "completed"

    def test_cancel_plan(self) -> None:
        """Любой статус → cancelled."""
        from cognitia.orchestration.types import Plan, PlanStep

        plan = Plan(id="p1", goal="g", steps=[PlanStep(id="s1", description="s")], created_at=_now())
        cancelled = plan.cancel()
        assert cancelled.status == "cancelled"

    # --- Invalid transitions ---

    def test_approve_non_draft_raises(self) -> None:
        """approved → approve → ValueError."""
        from cognitia.orchestration.types import Plan, PlanStep

        plan = Plan(id="p1", goal="g", steps=[PlanStep(id="s1", description="s")], created_at=_now())
        plan = plan.approve(by="user")
        with pytest.raises(ValueError, match="draft"):
            plan.approve(by="user")

    def test_start_non_approved_raises(self) -> None:
        """draft → start_execution → ValueError."""
        from cognitia.orchestration.types import Plan, PlanStep

        plan = Plan(id="p1", goal="g", steps=[PlanStep(id="s1", description="s")], created_at=_now())
        with pytest.raises(ValueError, match="approved"):
            plan.start_execution()

    def test_complete_non_executing_raises(self) -> None:
        """approved → mark_completed → ValueError."""
        from cognitia.orchestration.types import Plan, PlanStep

        plan = Plan(id="p1", goal="g", steps=[PlanStep(id="s1", description="s")], created_at=_now())
        plan = plan.approve(by="system")
        with pytest.raises(ValueError, match="executing"):
            plan.mark_completed()

    def test_update_step(self) -> None:
        """Обновить конкретный шаг в плане."""
        from cognitia.orchestration.types import Plan, PlanStep

        plan = Plan(
            id="p1", goal="g",
            steps=[PlanStep(id="s1", description="a"), PlanStep(id="s2", description="b")],
            created_at=_now(),
        )
        updated_step = plan.steps[0].complete("done")
        updated_plan = plan.update_step(updated_step)
        assert updated_plan.steps[0].status == "completed"
        assert updated_plan.steps[1].status == "pending"

    def test_update_step_not_found(self) -> None:
        """Обновление несуществующего шага → ValueError."""
        from cognitia.orchestration.types import Plan, PlanStep

        plan = Plan(id="p1", goal="g", steps=[PlanStep(id="s1", description="a")], created_at=_now())
        fake_step = PlanStep(id="s999", description="x").complete("y")
        with pytest.raises(ValueError, match="s999"):
            plan.update_step(fake_step)


class TestPlanStoreProtocol:
    """Контрактные тесты для PlanStore Protocol."""

    def test_runtime_checkable(self) -> None:
        from cognitia.orchestration.protocols import PlanStore

        class FakeStore:
            async def save(self, plan) -> None:
                pass

            async def load(self, plan_id: str) -> object:
                return None

            async def list_plans(self, user_id: str, topic_id: str) -> list:
                return []

            async def update_step(self, plan_id: str, step) -> None:
                pass

        assert isinstance(FakeStore(), PlanStore)

    def test_incomplete_not_instance(self) -> None:
        from cognitia.orchestration.protocols import PlanStore

        class Incomplete:
            async def save(self, plan) -> None:
                pass

        assert not isinstance(Incomplete(), PlanStore)

    def test_protocol_max_methods(self) -> None:
        from cognitia.orchestration.protocols import PlanStore

        methods = [n for n in dir(PlanStore) if not n.startswith("_") and callable(getattr(PlanStore, n, None))]
        assert len(methods) <= 4, f"ISP: {len(methods)} > 4"

    def test_no_freedom_imports(self) -> None:
        import inspect

        import cognitia.orchestration.protocols as p
        import cognitia.orchestration.types as t

        assert "freedom_agent" not in inspect.getsource(t)
        assert "freedom_agent" not in inspect.getsource(p)
