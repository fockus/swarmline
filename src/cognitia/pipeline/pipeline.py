"""Pipeline — phase-based execution with quality gates and budget control."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from cognitia.pipeline.budget import BudgetExceededError, BudgetTracker
from cognitia.pipeline.types import (
    GateResult,
    PhaseResult,
    PhaseStatus,
    PipelinePhase,
    PipelineResult,
)


class Pipeline:
    """Phase-based execution pipeline with quality gates.

    Runs phases sequentially. Between phases, quality gates
    are checked. Budget is enforced before each phase.

    Usage::

        pipeline = Pipeline(
            phases=[phase1, phase2, phase3],
            orchestrator=orch,
            task_board=board,
            gates={"phase2": [my_gate]},
            budget=tracker,
        )
        result = await pipeline.run("Build the system")
    """

    def __init__(
        self,
        phases: list[PipelinePhase],
        orchestrator: Any,
        task_board: Any,
        *,
        gates: dict[str, list[Any]] | None = None,
        budget: BudgetTracker | None = None,
        event_bus: Any | None = None,
    ) -> None:
        self._phases = sorted(phases, key=lambda p: p.order)
        self._orch = orchestrator
        self._board = task_board
        self._gates: dict[str, list[Any]] = gates or {}
        self._budget = budget
        self._bus = event_bus
        self._phase_results: list[PhaseResult] = []
        self._current_phase_id: str | None = None
        self._stopped = False
        self._current_run_id: str | None = None

    async def run(self, goal: str) -> PipelineResult:
        """Run all phases sequentially with gates between them."""
        start_time = time.monotonic()
        self._phase_results = []
        self._stopped = False

        await self._emit("pipeline.started", {"goal": goal, "phase_count": len(self._phases)})

        for phase in self._phases:
            if self._stopped:
                self._phase_results.append(PhaseResult(
                    phase_id=phase.id, status=PhaseStatus.SKIPPED,
                ))
                continue

            result = await self._run_single_phase(phase, goal)
            self._phase_results.append(result)

            if result.status == PhaseStatus.FAILED:
                # Record remaining phases as SKIPPED
                idx = self._phases.index(phase)
                for remaining in self._phases[idx + 1:]:
                    self._phase_results.append(PhaseResult(
                        phase_id=remaining.id, status=PhaseStatus.SKIPPED,
                    ))
                break

        total_duration = time.monotonic() - start_time
        status = "stopped" if self._stopped else (
            "failed" if any(r.status == PhaseStatus.FAILED for r in self._phase_results)
            else "completed"
        )

        pipeline_result = PipelineResult(
            phases=tuple(self._phase_results),
            total_duration_seconds=total_duration,
            total_cost_usd=self._budget.total_cost() if self._budget else 0.0,
            status=status,
        )
        await self._emit("pipeline.completed", {"status": status})
        return pipeline_result

    async def run_phase(self, phase_id: str) -> PhaseResult:
        """Run a single phase by ID."""
        phase = next((p for p in self._phases if p.id == phase_id), None)
        if phase is None:
            return PhaseResult(
                phase_id=phase_id, status=PhaseStatus.FAILED,
                error=f"Phase '{phase_id}' not found",
            )
        return await self._run_single_phase(phase, phase.goal)

    def get_status(self) -> dict[str, Any]:
        """Return current pipeline status."""
        return {
            "current_phase": self._current_phase_id,
            "stopped": self._stopped,
            "completed_phases": len(self._phase_results),
            "total_phases": len(self._phases),
            "phase_results": [
                {"phase_id": r.phase_id, "status": r.status.value}
                for r in self._phase_results
            ],
        }

    async def stop(self) -> None:
        """Stop the pipeline. Current phase finishes, remaining are skipped."""
        self._stopped = True
        if self._current_run_id is not None:
            try:
                await self._orch.stop(self._current_run_id)
            except (KeyError, RuntimeError):
                pass
        await self._emit("pipeline.stopped", {})

    async def _execute_phase_orchestration(self, phase: PipelinePhase, goal: str) -> str:
        """Run orchestration for a single phase. Returns run_id."""
        phase_goal = f"[{phase.name}] {goal}" if phase.goal == goal else phase.goal
        run_id = await self._orch.start(phase_goal)
        self._current_run_id = run_id

        # Wait for root agent to complete via protocol method (no private attr access)
        root_task_id = f"root-{run_id}"
        if hasattr(self._orch, "wait_for_task"):
            await self._orch.wait_for_task(root_task_id)
        return run_id

    async def _run_single_phase(
        self, phase: PipelinePhase, goal: str,
    ) -> PhaseResult:
        """Execute one phase: budget check → run → gates."""
        phase_start = time.monotonic()
        self._current_phase_id = phase.id

        await self._emit("pipeline.phase.started", {
            "phase_id": phase.id, "name": phase.name,
        })

        # Budget check
        if self._budget and self._budget.is_exceeded():
            result = PhaseResult(
                phase_id=phase.id, status=PhaseStatus.FAILED,
                error="Budget exceeded before phase start",
            )
            await self._emit("pipeline.phase.failed", {
                "phase_id": phase.id, "error": result.error,
            })
            return result

        if self._budget and self._budget.is_phase_exceeded(phase.id):
            result = PhaseResult(
                phase_id=phase.id, status=PhaseStatus.FAILED,
                error="Phase budget exceeded",
            )
            await self._emit("pipeline.phase.failed", {
                "phase_id": phase.id, "error": result.error,
            })
            return result

        # Run phase via orchestrator (with optional timeout)
        run_id: str | None = None
        try:
            phase_coro = self._execute_phase_orchestration(phase, goal)
            if phase.timeout_seconds and phase.timeout_seconds > 0:
                run_id = await asyncio.wait_for(phase_coro, timeout=phase.timeout_seconds)
            else:
                run_id = await phase_coro

        except TimeoutError:
            result = PhaseResult(
                phase_id=phase.id, status=PhaseStatus.FAILED,
                error=f"Phase timed out after {phase.timeout_seconds}s",
                duration_seconds=time.monotonic() - phase_start,
            )
            await self._emit("pipeline.phase.failed", {
                "phase_id": phase.id, "error": result.error,
            })
            return result
        except asyncio.CancelledError:
            result = PhaseResult(
                phase_id=phase.id, status=PhaseStatus.FAILED,
                error="Phase cancelled (pipeline stopped)",
                duration_seconds=time.monotonic() - phase_start,
            )
            await self._emit("pipeline.phase.failed", {
                "phase_id": phase.id, "error": result.error,
            })
            return result
        except BudgetExceededError as exc:
            result = PhaseResult(
                phase_id=phase.id, status=PhaseStatus.FAILED,
                error=str(exc),
                duration_seconds=time.monotonic() - phase_start,
            )
            await self._emit("pipeline.phase.failed", {
                "phase_id": phase.id, "error": result.error,
            })
            return result
        except Exception as exc:  # noqa: BLE001
            result = PhaseResult(
                phase_id=phase.id, status=PhaseStatus.FAILED,
                error=str(exc),
                duration_seconds=time.monotonic() - phase_start,
            )
            await self._emit("pipeline.phase.failed", {
                "phase_id": phase.id, "error": result.error,
            })
            return result

        # Run quality gates
        gate_results: list[GateResult] = []
        if phase.id in self._gates:
            for gate in self._gates[phase.id]:
                gr = await gate.check(phase.id, {"goal": phase.goal, "run_id": run_id})
                gate_results.append(gr)
                if not gr.passed:
                    result = PhaseResult(
                        phase_id=phase.id,
                        status=PhaseStatus.FAILED,
                        gate_results=tuple(gate_results),
                        duration_seconds=time.monotonic() - phase_start,
                        error=f"Gate '{gr.gate_name}' failed: {gr.details}",
                    )
                    await self._emit("pipeline.phase.failed", {
                        "phase_id": phase.id, "error": result.error,
                    })
                    return result

        duration = time.monotonic() - phase_start
        result = PhaseResult(
            phase_id=phase.id,
            status=PhaseStatus.COMPLETED,
            gate_results=tuple(gate_results),
            duration_seconds=duration,
        )
        await self._emit("pipeline.phase.completed", {"phase_id": phase.id})
        self._current_phase_id = None
        return result

    async def _emit(self, topic: str, data: dict[str, Any]) -> None:
        if self._bus is not None:
            await self._bus.emit(topic, data)
