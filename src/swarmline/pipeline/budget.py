"""Budget tracker — cost accumulation and enforcement for pipeline execution."""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from swarmline.pipeline.types import BudgetPolicy, CostRecord


class BudgetExceededError(RuntimeError):
    """Raised when execution exceeds the configured budget."""

    def __init__(self, current: float, limit: float) -> None:
        self.current = current
        self.limit = limit
        super().__init__(f"Budget exceeded: ${current:.4f} / ${limit:.4f}")


class BudgetTracker:
    """In-memory cost tracker with budget enforcement.

    Tracks per-execution costs, checks against policy limits,
    and can wrap an AgentRunner to auto-track costs.
    """

    def __init__(
        self,
        policy: BudgetPolicy,
        *,
        event_bus: Any | None = None,
    ) -> None:
        self._policy = policy
        self._bus = event_bus
        self._records: list[CostRecord] = []
        self._warned = False

    def record(self, cost: CostRecord) -> None:
        """Record a cost entry and check warning threshold."""
        self._records.append(cost)
        self._check_warning()

    def total_cost(self) -> float:
        """Total accumulated cost in USD."""
        return sum(r.cost_usd for r in self._records)

    def phase_cost(self, phase_id: str) -> float:
        """Cost for a specific phase."""
        return sum(r.cost_usd for r in self._records if r.phase_id == phase_id)

    def agent_cost(self, agent_id: str) -> float:
        """Cost for a specific agent."""
        return sum(r.cost_usd for r in self._records if r.agent_id == agent_id)

    def check_budget(self) -> bool:
        """True if within budget, False if exceeded."""
        return not self.is_exceeded()

    def is_exceeded(self) -> bool:
        """True if any budget limit is exceeded (total, per-agent, or per-phase)."""
        p = self._policy
        if p.max_total_usd is not None and self.total_cost() >= p.max_total_usd:
            return True
        # Check per-agent limits
        if p.max_per_agent_usd is not None:
            agents = {r.agent_id for r in self._records if r.agent_id}
            for agent_id in agents:
                if self.agent_cost(agent_id) >= p.max_per_agent_usd:
                    return True
        # Check per-phase limits
        if p.max_per_phase_usd is not None:
            phases = {r.phase_id for r in self._records if r.phase_id}
            for phase_id in phases:
                if self.phase_cost(phase_id) >= p.max_per_phase_usd:
                    return True
        return False

    def is_agent_exceeded(self, agent_id: str) -> bool:
        """True if agent-specific budget limit is exceeded."""
        p = self._policy
        if p.max_per_agent_usd is not None:
            return self.agent_cost(agent_id) >= p.max_per_agent_usd
        return False

    def is_phase_exceeded(self, phase_id: str) -> bool:
        """True if phase-specific budget limit is exceeded."""
        p = self._policy
        if p.max_per_phase_usd is not None:
            return self.phase_cost(phase_id) >= p.max_per_phase_usd
        return False

    def get_all_records(self) -> list[CostRecord]:
        """Return all recorded cost entries."""
        return list(self._records)

    def wrap_runner(
        self,
        runner: Callable[..., Awaitable[str]],
        *,
        phase_id: str | None = None,
        cost_extractor: Callable[[str], float] | None = None,
    ) -> Callable[..., Awaitable[str]]:
        """Wrap an AgentRunner with budget tracking.

        The wrapper:
        1. Checks budget before each call (raises BudgetExceededError)
        2. Measures execution duration
        3. Records a CostRecord after the call

        Args:
            cost_extractor: Optional function that extracts cost (USD) from
                the runner result string. If not provided, cost_usd defaults
                to 0.0 (duration-only tracking).
        """
        tracker = self

        async def wrapped(
            agent_id: str, task_id: str, goal: str, system_prompt: str,
        ) -> str:
            if tracker.is_exceeded():
                raise BudgetExceededError(
                    tracker.total_cost(), tracker._policy.max_total_usd or 0.0,
                )
            if tracker.is_agent_exceeded(agent_id):
                raise BudgetExceededError(
                    tracker.agent_cost(agent_id),
                    tracker._policy.max_per_agent_usd or 0.0,
                )

            start = time.monotonic()
            result = await runner(agent_id, task_id, goal, system_prompt)
            duration = time.monotonic() - start

            cost_usd = cost_extractor(result) if cost_extractor else 0.0
            tracker.record(CostRecord(
                agent_id=agent_id,
                task_id=task_id,
                phase_id=phase_id,
                duration_seconds=duration,
                cost_usd=cost_usd,
            ))
            return result

        return wrapped

    def _check_warning(self) -> None:
        """Emit warning event if threshold exceeded (once)."""
        if self._warned or self._bus is None:
            return
        p = self._policy
        if p.max_total_usd is None or p.max_total_usd <= 0:
            return
        pct = (self.total_cost() / p.max_total_usd) * 100
        if pct >= p.warn_at_percent:
            self._warned = True
            # Fire-and-forget — don't block on event bus
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._bus.emit("pipeline.budget.warning", {
                    "current_usd": self.total_cost(),
                    "limit_usd": p.max_total_usd,
                    "percent": pct,
                }))
            except RuntimeError:
                pass  # no running loop — skip warning event
