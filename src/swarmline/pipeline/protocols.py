"""Pipeline protocols — quality gates, cost tracking, goal decomposition."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from swarmline.pipeline.types import CostRecord, GateResult, Goal


@runtime_checkable
class QualityGate(Protocol):
    """Verification checkpoint between pipeline phases. ISP: 1 method."""

    async def check(self, phase_id: str, results: dict[str, Any]) -> GateResult: ...


@runtime_checkable
class CostTracker(Protocol):
    """Track and enforce execution costs. ISP: 3 methods."""

    def record(self, cost: CostRecord) -> None: ...
    def total_cost(self) -> float: ...
    def check_budget(self) -> bool: ...


@runtime_checkable
class GoalDecomposer(Protocol):
    """Decompose a high-level goal into sub-goals/tasks. ISP: 1 method."""

    async def decompose(self, goal: Goal) -> list[Goal]: ...
