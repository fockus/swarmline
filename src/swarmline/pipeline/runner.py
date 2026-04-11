"""PipelineRunner — convenience wrapper for common pipeline patterns."""

from __future__ import annotations

from typing import Any, Callable

from swarmline.pipeline.pipeline import Pipeline
from swarmline.pipeline.types import PhaseResult, PipelineResult


class PipelineRunner:
    """Convenience wrapper for running pipelines with common patterns.

    Usage::

        runner = PipelineRunner(pipeline)
        result = await runner.run_all("Build the system")
    """

    def __init__(self, pipeline: Pipeline) -> None:
        self._pipeline = pipeline
        self._on_phase_complete: list[Callable[..., Any]] = []
        self._on_budget_warning: list[Callable[..., Any]] = []

    async def run_all(self, goal: str) -> PipelineResult:
        """Run all phases sequentially."""
        return await self._pipeline.run(goal)

    async def run_phase(self, phase_id: str) -> PhaseResult:
        """Run a single phase by ID."""
        return await self._pipeline.run_phase(phase_id)

    async def run_until_gate_fail(self, goal: str) -> PipelineResult:
        """Run phases until first gate failure.

        This is the default behavior of Pipeline.run() —
        phases stop on first failure. Alias for clarity.
        """
        return await self._pipeline.run(goal)

    def on_phase_complete(self, callback: Callable[..., Any]) -> None:
        """Register a callback for phase completion events.

        If the pipeline has an event bus, subscribes to
        ``pipeline.phase.completed``.
        """
        self._on_phase_complete.append(callback)
        bus = self._pipeline._bus
        if bus is not None:
            bus.subscribe("pipeline.phase.completed", callback)

    def on_budget_warning(self, callback: Callable[..., Any]) -> None:
        """Register a callback for budget warning events.

        Subscribes to ``pipeline.budget.warning``.
        """
        self._on_budget_warning.append(callback)
        bus = self._pipeline._bus
        if bus is not None:
            bus.subscribe("pipeline.budget.warning", callback)

    async def stop(self) -> None:
        """Stop the pipeline."""
        await self._pipeline.stop()

    def get_status(self) -> dict[str, Any]:
        """Get current pipeline status."""
        return self._pipeline.get_status()
