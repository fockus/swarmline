"""E2E: research -> plan(blackboard) -> workers(scoped, result-only) ->
replan -> finalize(contract), threading the EXISTING H6 pieces end-to-end.

H6 supervisor-orchestrator, Task 5 (REQ-013 spirit). FAKES only for the
subagent orchestrator / verification predicate — no live LLM, no network.
Threads real, non-mocked collaborators:

  1. `plan_via_subagent` (planner-as-subagent, "research" leg, REQ-007)
     builds the shared `Plan` from a subagent's output ONLY.
  2. `Blackboard` + `create_spawn_subagent_tool` scope a worker to exactly
     one step and record a result-only `Report` (REQ-004/005/006).
  3. The worker's first attempt fails -> `SupervisorState.replan_on_blocker`
     decomposes the blocked step (ADaPT decompose-on-failure, REQ-008).
  4. A retry worker spawn succeeds.
  5. `create_finalize_tool`, gated on a `LedgerCodeVerifier` predicate over
     the SAME `VerificationLedger`, BLOCKS before the retry lands and
     reports done once it does (REQ-011) — proving the full loop composes
     without inventing any parallel mechanism.
"""

from __future__ import annotations

import json

import pytest

from swarmline.orchestration.subagent_types import (
    SubagentResult,
    SubagentSpec,
    SubagentStatus,
)
from swarmline.orchestration.supervisor.blackboard import Blackboard
from swarmline.orchestration.supervisor.finalize import create_finalize_tool
from swarmline.orchestration.supervisor.replan import plan_via_subagent
from swarmline.orchestration.supervisor.state import SupervisorState
from swarmline.orchestration.supervisor.tools import create_spawn_subagent_tool
from swarmline.orchestration.types import PlanStep
from swarmline.runtime.types import Message
from swarmline.verification.capture import capture_ledger
from swarmline.verification.verifiers import LedgerCodeVerifier

pytestmark = pytest.mark.integration


class _QueueOrchestrator:
    """Fake `SubagentSpawner`: FIFO-queued results, a fresh agent_id minted
    per `spawn()` call. Shared across the planner AND every worker in this
    test — exactly how one real orchestrator instance would be used in
    production (one spawn/wait surface, many callers)."""

    def __init__(self, results: list[SubagentResult]) -> None:
        self._queue = list(results)
        self.spawned: list[tuple[SubagentSpec, str]] = []
        self._pending: dict[str, SubagentResult] = {}
        self._n = 0

    async def spawn(self, spec: SubagentSpec, task: str) -> str:
        self.spawned.append((spec, task))
        self._n += 1
        agent_id = f"agent-{self._n}"
        self._pending[agent_id] = self._queue.pop(0)
        return agent_id

    async def wait(self, agent_id: str) -> SubagentResult:
        return self._pending.pop(agent_id)


class _FixedDecomposer:
    """Fake `Decomposer`: returns canned sub-steps, records what it saw."""

    def __init__(self, subs: tuple[PlanStep, ...]) -> None:
        self._subs = subs
        self.seen: list[PlanStep] = []

    async def decompose(self, step: PlanStep) -> tuple[PlanStep, ...]:
        self.seen.append(step)
        return self._subs


class TestSupervisorEndToEnd:
    @pytest.mark.asyncio
    async def test_research_plan_workers_replan_finalize_end_to_end(self) -> None:
        # --- 1. research -> plan (planner-as-subagent, REQ-007) ---
        plan_json = json.dumps(
            {
                "type": "plan",
                "goal": "Ship the feature",
                "steps": [
                    {"id": "step-1", "title": "Research the approach"},
                    {"id": "step-2", "title": "Implement the feature"},
                ],
            }
        )
        results = [
            SubagentResult(
                agent_id="planner",
                status=SubagentStatus(state="completed"),
                output=plan_json,
                messages=[
                    Message(role="assistant", content="SECRET_PLANNER_REASONING")
                ],
            ),
            SubagentResult(
                agent_id="coder-1",
                status=SubagentStatus(state="failed"),
                output="blocked: missing dependency",
                messages=[
                    Message(role="assistant", content="SECRET_WORKER_TRANSCRIPT_1")
                ],
            ),
            SubagentResult(
                agent_id="coder-2",
                status=SubagentStatus(state="completed"),
                output="implemented successfully",
                messages=[
                    Message(role="assistant", content="SECRET_WORKER_TRANSCRIPT_2")
                ],
            ),
        ]
        orchestrator = _QueueOrchestrator(results)

        planner_spec = SubagentSpec(
            name="planner", system_prompt="You are the planner."
        )
        plan = await plan_via_subagent(orchestrator, planner_spec, "plan the feature")

        assert plan.goal == "Ship the feature"
        assert [s.id for s in plan.steps] == ["step-1", "step-2"]
        assert "SECRET_PLANNER_REASONING" not in repr(plan)

        # --- 2. blackboard + scoped worker spawn (REQ-004/005/006) ---
        state = SupervisorState(blackboard=Blackboard(plan=plan))
        spawn = create_spawn_subagent_tool(state, orchestrator)

        await spawn(
            {"role": "coder", "task": "implement step-2", "step_ids": ["step-2"]}
        )
        failed_report = state.reports[-1]
        assert failed_report.status == "failed"
        assert "SECRET_WORKER_TRANSCRIPT_1" not in repr(state.reports)

        # --- 3. replan on the blocker (ADaPT decompose-on-failure, REQ-008) ---
        added_substep = PlanStep(
            id="step-2a", description="install the missing dependency"
        )
        decomposer = _FixedDecomposer((added_substep,))
        replanned = await state.replan_on_blocker(failed_report, decomposer)

        assert replanned is True
        step_2 = next(s for s in state.blackboard.plan.steps if s.id == "step-2")
        assert step_2.substeps == [added_substep]

        # --- 4. finalize gated on the contract: BLOCKED before the retry ---
        ledger = capture_ledger(
            ["a worker completed the implementation"], id_prefix="sc"
        )

        async def implementation_done(ctx: object) -> tuple[bool, str]:
            assert isinstance(ctx, SupervisorState)
            completed = [r for r in ctx.reports if r.status == "completed"]
            return (len(completed) >= 1, f"{len(completed)} completed report(s)")

        verifier = LedgerCodeVerifier({"sc-0": implementation_done})
        finalize = create_finalize_tool(state, verifier=verifier, ledger=ledger)

        blocked = await finalize({})
        assert "BLOCKED" in blocked
        assert "sc-0" in blocked

        # --- retry worker (scoped to the SAME step) succeeds ---
        await spawn({"role": "coder", "task": "retry step-2", "step_ids": ["step-2"]})
        assert state.reports[-1].status == "completed"
        assert "SECRET_WORKER_TRANSCRIPT_2" not in repr(state.reports)

        # --- 5. finalize now reports done, gated by the SAME contract ---
        done = await finalize({})
        assert "BLOCKED" not in done
        assert plan.id in done

        # Idempotent: re-calling finalize after done stays done.
        again = await finalize({})
        assert "BLOCKED" not in again
        assert ledger.results == ()
