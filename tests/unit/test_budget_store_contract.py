"""Contract tests for PersistentBudgetStore — cross-run budget tracking."""

from __future__ import annotations

import time

import pytest

from swarmline.pipeline.budget_store import (
    InMemoryPersistentBudgetStore,
    PersistentBudgetStore,
    SqlitePersistentBudgetStore,
)
from swarmline.pipeline.budget_types import (
    BudgetScope,
    BudgetScopeType,
    BudgetThreshold,
    BudgetWindow,
    ThresholdAction,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(params=["inmemory", "sqlite"])
def store(request, tmp_path):
    if request.param == "inmemory":
        return InMemoryPersistentBudgetStore()
    else:
        return SqlitePersistentBudgetStore(str(tmp_path / "test.db"))


def _scope(
    scope_type: BudgetScopeType = BudgetScopeType.AGENT,
    scope_id: str = "agent-1",
) -> BudgetScope:
    return BudgetScope(scope_type=scope_type, scope_id=scope_id)


# ---------------------------------------------------------------------------
# Protocol shape
# ---------------------------------------------------------------------------


class TestProtocolShape:

    def test_protocol_shape_isinstance(self, store) -> None:
        assert isinstance(store, PersistentBudgetStore)


# ---------------------------------------------------------------------------
# Record + get_usage
# ---------------------------------------------------------------------------


class TestRecordAndUsage:

    async def test_record_and_get_usage_lifetime(self, store) -> None:
        scope = _scope()
        await store.record_cost(scope, 1.50, "call-1")
        await store.record_cost(scope, 2.25, "call-2")
        await store.record_cost(scope, 0.75, "call-3")
        usage = await store.get_usage(scope, BudgetWindow.LIFETIME)
        assert usage == pytest.approx(4.50)

    async def test_get_usage_monthly_window(self, store) -> None:
        scope = _scope()
        # Record a cost with an old timestamp (last year) directly
        # We need to test that monthly window only sums current month costs.
        # Record current-month cost via the normal API.
        await store.record_cost(scope, 3.00, "current-month")

        # Inject an old cost directly into the backend for testing monthly filter.
        old_ts = time.time() - 60 * 60 * 24 * 45  # 45 days ago

        if isinstance(store, InMemoryPersistentBudgetStore):
            from swarmline.pipeline.budget_types import CostEvent
            import uuid

            store._costs.append(CostEvent(
                id=uuid.uuid4().hex[:12],
                scope=scope,
                amount_usd=10.00,
                description="old-cost",
                timestamp=old_ts,
            ))
        elif isinstance(store, SqlitePersistentBudgetStore):
            import uuid

            store._execute_sync(
                "INSERT INTO budget_costs (id, scope_type, scope_id, amount_usd, description, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex[:12], scope.scope_type.value, scope.scope_id, 10.00, "old-cost", old_ts),
            )

        monthly = await store.get_usage(scope, BudgetWindow.MONTHLY)
        lifetime = await store.get_usage(scope, BudgetWindow.LIFETIME)

        assert monthly == pytest.approx(3.00)
        assert lifetime == pytest.approx(13.00)


# ---------------------------------------------------------------------------
# Threshold checks
# ---------------------------------------------------------------------------


class TestThresholdChecks:

    async def test_check_threshold_ok(self, store) -> None:
        scope = _scope()
        store.register_threshold(BudgetThreshold(
            scope=scope,
            window=BudgetWindow.LIFETIME,
            limit_usd=100.0,
            warn_at_percent=80.0,
            hard_stop=True,
        ))
        await store.record_cost(scope, 10.0, "small")
        result = await store.check_threshold(scope, BudgetWindow.LIFETIME)
        assert result.action == ThresholdAction.OK
        assert result.usage_usd == pytest.approx(10.0)
        assert result.limit_usd == pytest.approx(100.0)
        assert result.percent == pytest.approx(10.0)

    async def test_check_threshold_warn(self, store) -> None:
        scope = _scope()
        store.register_threshold(BudgetThreshold(
            scope=scope,
            window=BudgetWindow.LIFETIME,
            limit_usd=100.0,
            warn_at_percent=80.0,
            hard_stop=True,
        ))
        await store.record_cost(scope, 85.0, "big")
        result = await store.check_threshold(scope, BudgetWindow.LIFETIME)
        assert result.action == ThresholdAction.WARN
        assert result.percent == pytest.approx(85.0)

    async def test_check_threshold_stop(self, store) -> None:
        scope = _scope()
        store.register_threshold(BudgetThreshold(
            scope=scope,
            window=BudgetWindow.LIFETIME,
            limit_usd=50.0,
            warn_at_percent=80.0,
            hard_stop=True,
        ))
        await store.record_cost(scope, 55.0, "over-limit")
        result = await store.check_threshold(scope, BudgetWindow.LIFETIME)
        assert result.action == ThresholdAction.STOP
        assert result.percent == pytest.approx(110.0)

    async def test_check_threshold_no_threshold_returns_ok(self, store) -> None:
        scope = _scope()
        await store.record_cost(scope, 10.0, "some cost")
        result = await store.check_threshold(scope, BudgetWindow.LIFETIME)
        assert result.action == ThresholdAction.OK
        assert result.limit_usd == 0.0
        assert result.percent == 0.0

    async def test_check_threshold_exceed_without_hard_stop_is_warn(self, store) -> None:
        scope = _scope()
        store.register_threshold(BudgetThreshold(
            scope=scope,
            window=BudgetWindow.LIFETIME,
            limit_usd=10.0,
            warn_at_percent=80.0,
            hard_stop=False,
        ))
        await store.record_cost(scope, 15.0, "over but soft")
        result = await store.check_threshold(scope, BudgetWindow.LIFETIME)
        assert result.action == ThresholdAction.WARN


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------


class TestIncidents:

    async def test_list_incidents_after_breach(self, store) -> None:
        scope = _scope()
        store.register_threshold(BudgetThreshold(
            scope=scope,
            window=BudgetWindow.LIFETIME,
            limit_usd=10.0,
            warn_at_percent=80.0,
            hard_stop=True,
        ))
        await store.record_cost(scope, 9.0, "approaching")
        await store.check_threshold(scope, BudgetWindow.LIFETIME)
        incidents = await store.list_incidents(scope)
        assert len(incidents) == 1
        assert incidents[0].action == ThresholdAction.WARN

    async def test_record_cost_creates_incident_on_breach(self, store) -> None:
        scope = _scope()
        store.register_threshold(BudgetThreshold(
            scope=scope,
            window=BudgetWindow.LIFETIME,
            limit_usd=10.0,
            warn_at_percent=80.0,
            hard_stop=True,
        ))
        await store.record_cost(scope, 11.0, "over-limit")
        # check_threshold triggers incident logging
        await store.check_threshold(scope, BudgetWindow.LIFETIME)
        incidents = await store.list_incidents(scope)
        assert len(incidents) >= 1
        assert any(i.action == ThresholdAction.STOP for i in incidents)

    async def test_list_incidents_empty_initially(self, store) -> None:
        scope = _scope()
        incidents = await store.list_incidents(scope)
        assert incidents == []


# ---------------------------------------------------------------------------
# Scope isolation
# ---------------------------------------------------------------------------


class TestScopeIsolation:

    async def test_multiple_scopes_independent(self, store) -> None:
        scope_a = _scope(scope_id="agent-a")
        scope_b = _scope(scope_id="agent-b")

        await store.record_cost(scope_a, 10.0, "a-cost")
        await store.record_cost(scope_b, 25.0, "b-cost")

        usage_a = await store.get_usage(scope_a, BudgetWindow.LIFETIME)
        usage_b = await store.get_usage(scope_b, BudgetWindow.LIFETIME)

        assert usage_a == pytest.approx(10.0)
        assert usage_b == pytest.approx(25.0)

    async def test_incidents_scoped(self, store) -> None:
        scope_a = _scope(scope_id="agent-a")
        scope_b = _scope(scope_id="agent-b")

        store.register_threshold(BudgetThreshold(
            scope=scope_a,
            window=BudgetWindow.LIFETIME,
            limit_usd=5.0,
        ))
        await store.record_cost(scope_a, 10.0, "over")
        await store.check_threshold(scope_a, BudgetWindow.LIFETIME)

        incidents_a = await store.list_incidents(scope_a)
        incidents_b = await store.list_incidents(scope_b)
        assert len(incidents_a) >= 1
        assert incidents_b == []
