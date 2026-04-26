"""Unit tests for PartitionedBudgetTracker."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from swarmline.pipeline.partitioned_budget import (
    PartitionedBudgetTracker,
    _NamespacedBusWrapper,
)
from swarmline.pipeline.budget import BudgetTracker
from swarmline.pipeline.types import BudgetPolicy, CostRecord


class _FakeEventBus:
    """Minimal event bus fake for testing emit calls."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, event_type: str, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))


class TestPartitionCreation:
    def test_create_partition_returns_budget_tracker(self) -> None:
        tracker = PartitionedBudgetTracker(
            global_policy=BudgetPolicy(max_total_usd=100.0)
        )
        partition = tracker.create_partition("goal-a", BudgetPolicy(max_total_usd=50.0))
        assert isinstance(partition, BudgetTracker)

    def test_get_partition_returns_same_instance(self) -> None:
        tracker = PartitionedBudgetTracker(
            global_policy=BudgetPolicy(max_total_usd=100.0)
        )
        created = tracker.create_partition("goal-a", BudgetPolicy(max_total_usd=50.0))
        fetched = tracker.get_partition("goal-a")
        assert fetched is created

    def test_get_partition_unknown_returns_none(self) -> None:
        tracker = PartitionedBudgetTracker(
            global_policy=BudgetPolicy(max_total_usd=100.0)
        )
        assert tracker.get_partition("unknown") is None

    def test_list_partitions_returns_namespace_names(self) -> None:
        tracker = PartitionedBudgetTracker(
            global_policy=BudgetPolicy(max_total_usd=100.0)
        )
        tracker.create_partition("goal-a", BudgetPolicy(max_total_usd=50.0))
        tracker.create_partition("goal-b", BudgetPolicy(max_total_usd=30.0))
        assert tracker.list_partitions() == ["goal-a", "goal-b"]

    def test_list_partitions_empty_initially(self) -> None:
        tracker = PartitionedBudgetTracker(
            global_policy=BudgetPolicy(max_total_usd=100.0)
        )
        assert tracker.list_partitions() == []


class TestPerGoalRecording:
    def test_record_accumulates_in_partition(self) -> None:
        tracker = PartitionedBudgetTracker(
            global_policy=BudgetPolicy(max_total_usd=100.0)
        )
        tracker.create_partition("goal-a", BudgetPolicy(max_total_usd=50.0))
        tracker.record(
            "goal-a", CostRecord(agent_id="dev1", task_id="t1", cost_usd=10.0)
        )
        assert tracker.partition_cost("goal-a") == pytest.approx(10.0)

    def test_record_rolls_up_to_total(self) -> None:
        tracker = PartitionedBudgetTracker(
            global_policy=BudgetPolicy(max_total_usd=100.0)
        )
        tracker.create_partition("goal-a", BudgetPolicy(max_total_usd=50.0))
        tracker.record(
            "goal-a", CostRecord(agent_id="dev1", task_id="t1", cost_usd=10.0)
        )
        assert tracker.total_cost() == pytest.approx(10.0)

    def test_record_in_one_partition_does_not_affect_another(self) -> None:
        tracker = PartitionedBudgetTracker(
            global_policy=BudgetPolicy(max_total_usd=100.0)
        )
        tracker.create_partition("goal-a", BudgetPolicy(max_total_usd=50.0))
        tracker.create_partition("goal-b", BudgetPolicy(max_total_usd=50.0))
        tracker.record(
            "goal-a", CostRecord(agent_id="dev1", task_id="t1", cost_usd=10.0)
        )
        assert tracker.partition_cost("goal-b") == pytest.approx(0.0)

    def test_partition_cost_unknown_namespace_returns_zero(self) -> None:
        tracker = PartitionedBudgetTracker(
            global_policy=BudgetPolicy(max_total_usd=100.0)
        )
        assert tracker.partition_cost("nonexistent") == pytest.approx(0.0)


class TestGlobalRollup:
    def test_total_cost_sums_across_partitions(self) -> None:
        tracker = PartitionedBudgetTracker(
            global_policy=BudgetPolicy(max_total_usd=100.0)
        )
        tracker.create_partition("goal-a", BudgetPolicy(max_total_usd=50.0))
        tracker.create_partition("goal-b", BudgetPolicy(max_total_usd=50.0))
        tracker.record(
            "goal-a", CostRecord(agent_id="dev1", task_id="t1", cost_usd=30.0)
        )
        tracker.record(
            "goal-b", CostRecord(agent_id="dev2", task_id="t2", cost_usd=40.0)
        )
        assert tracker.total_cost() == pytest.approx(70.0)

    def test_is_exceeded_true_when_global_limit_hit(self) -> None:
        tracker = PartitionedBudgetTracker(
            global_policy=BudgetPolicy(max_total_usd=50.0)
        )
        tracker.create_partition("goal-a", BudgetPolicy(max_total_usd=100.0))
        tracker.record(
            "goal-a", CostRecord(agent_id="dev1", task_id="t1", cost_usd=50.0)
        )
        assert tracker.is_exceeded() is True

    def test_is_exceeded_false_when_within_limit(self) -> None:
        tracker = PartitionedBudgetTracker(
            global_policy=BudgetPolicy(max_total_usd=100.0)
        )
        tracker.create_partition("goal-a", BudgetPolicy(max_total_usd=50.0))
        tracker.record(
            "goal-a", CostRecord(agent_id="dev1", task_id="t1", cost_usd=30.0)
        )
        assert tracker.is_exceeded() is False

    def test_is_exceeded_false_when_no_limit(self) -> None:
        tracker = PartitionedBudgetTracker(global_policy=BudgetPolicy())
        tracker.create_partition("goal-a", BudgetPolicy())
        tracker.record(
            "goal-a", CostRecord(agent_id="dev1", task_id="t1", cost_usd=999.0)
        )
        assert tracker.is_exceeded() is False

    def test_is_partition_exceeded_true_when_partition_limit_hit(self) -> None:
        tracker = PartitionedBudgetTracker(
            global_policy=BudgetPolicy(max_total_usd=200.0)
        )
        tracker.create_partition("goal-a", BudgetPolicy(max_total_usd=20.0))
        tracker.record(
            "goal-a", CostRecord(agent_id="dev1", task_id="t1", cost_usd=25.0)
        )
        assert tracker.is_partition_exceeded("goal-a") is True

    def test_is_partition_exceeded_false_for_unknown_namespace(self) -> None:
        tracker = PartitionedBudgetTracker(
            global_policy=BudgetPolicy(max_total_usd=100.0)
        )
        assert tracker.is_partition_exceeded("unknown") is False

    def test_partition_exceeded_does_not_affect_other_partition(self) -> None:
        tracker = PartitionedBudgetTracker(
            global_policy=BudgetPolicy(max_total_usd=200.0)
        )
        tracker.create_partition("goal-a", BudgetPolicy(max_total_usd=10.0))
        tracker.create_partition("goal-b", BudgetPolicy(max_total_usd=100.0))
        tracker.record(
            "goal-a", CostRecord(agent_id="dev1", task_id="t1", cost_usd=15.0)
        )
        assert tracker.is_partition_exceeded("goal-a") is True
        assert tracker.is_partition_exceeded("goal-b") is False


class TestNamespacedEvents:
    async def test_warning_event_has_namespace_prefix(self) -> None:
        bus = _FakeEventBus()
        tracker = PartitionedBudgetTracker(
            global_policy=BudgetPolicy(max_total_usd=100.0),
            event_bus=bus,
        )
        tracker.create_partition(
            "goal-a", BudgetPolicy(max_total_usd=10.0, warn_at_percent=50.0)
        )
        tracker.record(
            "goal-a", CostRecord(agent_id="dev1", task_id="t1", cost_usd=6.0)
        )
        # Let event bus fire-and-forget tasks complete
        await asyncio.sleep(0.01)
        # BudgetTracker emits "pipeline.budget.warning"; wrapper prefixes with namespace
        warning_events = [e for e in bus.events if "pipeline.budget.warning" in e[0]]
        assert len(warning_events) >= 1
        assert warning_events[0][0] == "goal-a:pipeline.budget.warning"
        assert warning_events[0][1]["namespace"] == "goal-a"

    async def test_exceeded_event_has_namespace_prefix(self) -> None:
        bus = _FakeEventBus()
        tracker = PartitionedBudgetTracker(
            global_policy=BudgetPolicy(max_total_usd=200.0),
            event_bus=bus,
        )
        tracker.create_partition(
            "goal-a", BudgetPolicy(max_total_usd=10.0, warn_at_percent=80.0)
        )
        # First record: triggers warning at 90%
        tracker.record(
            "goal-a", CostRecord(agent_id="dev1", task_id="t1", cost_usd=9.0)
        )
        # Second record: exceeds budget
        tracker.record(
            "goal-a", CostRecord(agent_id="dev1", task_id="t2", cost_usd=5.0)
        )
        await asyncio.sleep(0.01)
        exceeded_events = [e for e in bus.events if "budget_exceeded" in e[0]]
        assert len(exceeded_events) >= 1
        assert exceeded_events[0][0] == "goal-a:budget_exceeded"

    async def test_other_partitions_continue_after_one_exceeds(self) -> None:
        bus = _FakeEventBus()
        tracker = PartitionedBudgetTracker(
            global_policy=BudgetPolicy(max_total_usd=200.0),
            event_bus=bus,
        )
        tracker.create_partition("goal-a", BudgetPolicy(max_total_usd=10.0))
        tracker.create_partition("goal-b", BudgetPolicy(max_total_usd=100.0))
        # Exceed goal-a
        tracker.record(
            "goal-a", CostRecord(agent_id="dev1", task_id="t1", cost_usd=15.0)
        )
        assert tracker.is_partition_exceeded("goal-a") is True
        # goal-b still works fine
        tracker.record(
            "goal-b", CostRecord(agent_id="dev2", task_id="t2", cost_usd=5.0)
        )
        assert tracker.is_partition_exceeded("goal-b") is False
        assert tracker.partition_cost("goal-b") == pytest.approx(5.0)

    async def test_global_warning_event_fires(self) -> None:
        bus = _FakeEventBus()
        tracker = PartitionedBudgetTracker(
            global_policy=BudgetPolicy(max_total_usd=100.0, warn_at_percent=50.0),
            event_bus=bus,
        )
        tracker.create_partition("goal-a", BudgetPolicy(max_total_usd=100.0))
        tracker.record(
            "goal-a", CostRecord(agent_id="dev1", task_id="t1", cost_usd=60.0)
        )
        await asyncio.sleep(0.01)
        global_warnings = [e for e in bus.events if e[0] == "global:budget_warning"]
        assert len(global_warnings) >= 1


class TestBackwardCompat:
    def test_without_partitions_total_cost_works(self) -> None:
        tracker = PartitionedBudgetTracker(
            global_policy=BudgetPolicy(max_total_usd=100.0)
        )
        # Record directly with a namespace that has no partition
        tracker.record(
            "orphan", CostRecord(agent_id="dev1", task_id="t1", cost_usd=5.0)
        )
        assert tracker.total_cost() == pytest.approx(5.0)

    def test_without_partitions_is_exceeded_works(self) -> None:
        tracker = PartitionedBudgetTracker(
            global_policy=BudgetPolicy(max_total_usd=10.0)
        )
        tracker.record(
            "orphan", CostRecord(agent_id="dev1", task_id="t1", cost_usd=15.0)
        )
        assert tracker.is_exceeded() is True


class TestNamespacedBusWrapper:
    async def test_prefixes_event_type(self) -> None:
        bus = _FakeEventBus()
        wrapper = _NamespacedBusWrapper(bus, "goal-a")
        await wrapper.emit("budget_warning", {"amount": 5.0})
        assert len(bus.events) == 1
        assert bus.events[0][0] == "goal-a:budget_warning"
        assert bus.events[0][1]["namespace"] == "goal-a"

    async def test_no_op_when_bus_is_none(self) -> None:
        wrapper = _NamespacedBusWrapper(None, "goal-a")
        # Should not raise
        await wrapper.emit("budget_warning", {"amount": 5.0})
