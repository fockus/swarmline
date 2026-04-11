"""Partitioned budget tracker — per-goal sub-budgets with global rollup."""

from __future__ import annotations

import asyncio
from typing import Any

from swarmline.pipeline.budget import BudgetTracker
from swarmline.pipeline.types import BudgetPolicy, CostRecord


class _NamespacedBusWrapper:
    """Wraps an event bus to prefix all events with 'namespace:'."""

    def __init__(self, bus: Any | None, namespace: str) -> None:
        self._bus = bus
        self._ns = namespace

    async def emit(self, event_type: str, data: dict[str, Any]) -> None:
        if self._bus is not None:
            await self._bus.emit(f"{self._ns}:{event_type}", {**data, "namespace": self._ns})


class PartitionedBudgetTracker:
    """Budget tracker with per-goal sub-budgets rolling up to a global limit.

    Each partition is an independent BudgetTracker with its own policy.
    Exceeding a partition budget fires a namespaced event but does NOT halt other partitions.
    The global tracker aggregates all partition costs for overall limit enforcement.
    """

    def __init__(
        self,
        global_policy: BudgetPolicy,
        *,
        event_bus: Any | None = None,
    ) -> None:
        self._global_policy = global_policy
        self._bus = event_bus
        self._partitions: dict[str, BudgetTracker] = {}
        self._partition_policies: dict[str, BudgetPolicy] = {}
        self._global_records: list[CostRecord] = []
        self._global_warned = False

    def create_partition(self, namespace: str, policy: BudgetPolicy) -> BudgetTracker:
        """Create a child BudgetTracker for this namespace."""
        wrapper = _NamespacedBusWrapper(self._bus, namespace)
        partition = BudgetTracker(policy, event_bus=wrapper)
        self._partitions[namespace] = partition
        self._partition_policies[namespace] = policy
        return partition

    def get_partition(self, namespace: str) -> BudgetTracker | None:
        """Get a partition by namespace. Returns None if not found."""
        return self._partitions.get(namespace)

    def list_partitions(self) -> list[str]:
        """Return all partition namespace names."""
        return list(self._partitions.keys())

    def record(self, namespace: str, cost: CostRecord) -> None:
        """Record cost in partition (if exists) AND in global records."""
        partition = self._partitions.get(namespace)
        if partition is not None:
            partition.record(cost)
            self._check_partition_exceeded(namespace, partition)
        self._global_records.append(cost)
        self._check_global_warning()

    def total_cost(self) -> float:
        """Total accumulated cost across all partitions (USD)."""
        return sum(r.cost_usd for r in self._global_records)

    def partition_cost(self, namespace: str) -> float:
        """Cost for a specific partition."""
        partition = self._partitions.get(namespace)
        return partition.total_cost() if partition else 0.0

    def is_exceeded(self) -> bool:
        """True if global budget limit is exceeded."""
        p = self._global_policy
        return p.max_total_usd is not None and self.total_cost() >= p.max_total_usd

    def is_partition_exceeded(self, namespace: str) -> bool:
        """True if partition-specific budget is exceeded."""
        partition = self._partitions.get(namespace)
        return partition.is_exceeded() if partition else False

    def _check_partition_exceeded(self, namespace: str, partition: BudgetTracker) -> None:
        """Emit namespaced exceeded event when partition budget is blown."""
        if self._bus is None:
            return
        if not partition.is_exceeded():
            return
        # Use stored policy from create_partition instead of accessing private attr
        policy = self._partition_policies.get(namespace)
        limit = policy.max_total_usd if policy else None
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._bus.emit(f"{namespace}:budget_exceeded", {
                "namespace": namespace,
                "current_usd": partition.total_cost(),
                "limit_usd": limit,
            }))
        except RuntimeError:
            pass  # no running loop

    def _check_global_warning(self) -> None:
        """Emit global warning event if threshold exceeded (once)."""
        if self._global_warned or self._bus is None:
            return
        p = self._global_policy
        if p.max_total_usd is None or p.max_total_usd <= 0:
            return
        pct = (self.total_cost() / p.max_total_usd) * 100
        if pct >= p.warn_at_percent:
            self._global_warned = True
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._bus.emit("global:budget_warning", {
                    "current_usd": self.total_cost(),
                    "limit_usd": p.max_total_usd,
                    "percent": pct,
                }))
            except RuntimeError:
                pass  # no running loop
