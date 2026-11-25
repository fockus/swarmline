"""Tests for dynamic replan (ADaPT) + planner-as-subagent + single-threaded writes.

H6 supervisor-orchestrator, Task 4. Covers REQ-007/REQ-008/REQ-010. FAKES
only — no live LLM, no network.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest

from swarmline.orchestration.subagent_types import (
    SubagentResult,
    SubagentSpec,
    SubagentStatus,
)
from swarmline.orchestration.supervisor.blackboard import Blackboard
from swarmline.orchestration.supervisor.replan import (
    is_blocker,
    plan_via_subagent,
)
from swarmline.orchestration.supervisor.state import SupervisorState
from swarmline.orchestration.supervisor.tools import create_spawn_subagent_tool
from swarmline.orchestration.supervisor.types import Report
from swarmline.orchestration.types import Plan, PlanStep
from swarmline.runtime.types import Message


def _make_plan() -> Plan:
    return Plan(
        id="plan-1",
        goal="Ship feature X",
        steps=[
            PlanStep(id="step-1", description="Research"),
            PlanStep(id="step-2", description="Implement"),
            PlanStep(id="step-3", description="Verify"),
        ],
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
    )


class _FakeOrchestrator:
    """Fake SubagentSpawner: records spawn() calls, returns a canned result."""

    def __init__(self, result: SubagentResult, agent_id: str = "agent-planner") -> None:
        self.result = result
        self.agent_id = agent_id
        self.spawned: list[tuple[SubagentSpec, str]] = []

    async def spawn(self, spec: SubagentSpec, task: str) -> str:
        self.spawned.append((spec, task))
        return self.agent_id

    async def wait(self, agent_id: str) -> SubagentResult:
        assert agent_id == self.agent_id
        return self.result


class _FakeDecomposer:
    """Fake Decomposer: returns canned sub-steps, records the step it saw."""

    def __init__(self, subs: tuple[PlanStep, ...]) -> None:
        self.subs = subs
        self.seen: list[PlanStep] = []

    async def decompose(self, step: PlanStep) -> tuple[PlanStep, ...]:
        self.seen.append(step)
        return self.subs


class _GatedOrchestrator:
    """Fake SubagentSpawner whose `spawn()` releases its internal gate only
    once BOTH concurrent callers have entered — forces genuine overlap of
    the (unlocked) execution span instead of relying on timing."""

    def __init__(self) -> None:
        self.entered = 0
        self.max_entered = 0
        self._gate = asyncio.Event()

    async def spawn(self, spec: SubagentSpec, task: str) -> str:
        self.entered += 1
        self.max_entered = max(self.max_entered, self.entered)
        if self.entered >= 2:
            self._gate.set()
        else:
            await self._gate.wait()
        return f"agent-{task}"

    async def wait(self, agent_id: str) -> SubagentResult:
        return SubagentResult(
            agent_id=agent_id,
            status=SubagentStatus(state="completed"),
            output=f"{agent_id} done",
        )


def _ro_args(role: str, task: str, step_id: str) -> dict:
    return {"role": role, "task": task, "step_ids": [step_id], "read_only": True}


class TestReplanOnBlocker:
    @pytest.mark.asyncio
    async def test_supervisor_replans_on_worker_blocker(self) -> None:
        """Scenario 2 / REQ-008: a failed report triggers decompose-on-failure.

        Regression for the role/id identity-mismatch defect: `assignments` is
        keyed by `AgentHandle.id`, while `Report.worker` is the display ROLE
        — a DIFFERENT string in real usage. `replan_on_blocker` must join on
        `worker_id`, never `worker`.
        """
        bb = Blackboard(plan=_make_plan(), assignments={"id-123": ("step-2",)})
        state = SupervisorState(blackboard=bb)
        sub1 = PlanStep(id="step-2a", description="Implement part A")
        sub2 = PlanStep(id="step-2b", description="Implement part B")
        decomposer = _FakeDecomposer((sub1, sub2))
        report = Report(
            worker="coder",
            worker_id="id-123",
            summary="blocked on dependency",
            status="failed",
        )

        applied = await state.replan_on_blocker(report, decomposer)

        assert applied is True
        assert len(decomposer.seen) == 1
        assert decomposer.seen[0].id == "step-2"
        patched_step = next(s for s in state.blackboard.plan.steps if s.id == "step-2")
        assert patched_step.substeps == [sub1, sub2]

    @pytest.mark.asyncio
    async def test_replan_integration_through_spawn_subagent(self) -> None:
        """End-to-end spawn -> Report -> replan identity chain (real path).

        Proves the REAL `Report` produced by `tools.py` (not a hand-crafted
        one) — `worker_id=handle.id` — round-trips correctly through
        `replan_on_blocker`.
        """
        bb = Blackboard(plan=_make_plan())
        state = SupervisorState(blackboard=bb)
        failed_result = SubagentResult(
            agent_id="agent-blocked",
            status=SubagentStatus(state="failed"),
            output="could not proceed",
        )
        orchestrator = _FakeOrchestrator(failed_result, agent_id="agent-blocked")
        execute = create_spawn_subagent_tool(state, orchestrator)

        await execute({"role": "coder", "task": "implement", "step_ids": ["step-2"]})

        assert len(state.reports) == 1
        report = state.reports[0]
        assert report.worker == "coder"
        assert report.worker_id != ""
        assert report.worker_id != "coder"
        assert report.worker_id in state.blackboard.assignments

        sub = PlanStep(id="step-2a", description="Implement part A")
        decomposer = _FakeDecomposer((sub,))

        applied = await state.replan_on_blocker(report, decomposer)

        assert applied is True
        assert len(decomposer.seen) == 1
        assert decomposer.seen[0].id == "step-2"
        patched_step = next(s for s in state.blackboard.plan.steps if s.id == "step-2")
        assert patched_step.substeps == [sub]

    @pytest.mark.asyncio
    async def test_replan_no_assignment_is_noop(self) -> None:
        """A blocker Report whose `worker_id` has NO entry in `assignments`
        is a no-op — covers the `if not step_ids: return False` branch."""
        bb = Blackboard(plan=_make_plan(), assignments={"id-123": ("step-2",)})
        state = SupervisorState(blackboard=bb)
        decomposer = _FakeDecomposer(
            (PlanStep(id="step-2a", description="should never be applied"),)
        )
        report = Report(
            worker="coder", worker_id="id-unknown", summary="blocked", status="failed"
        )

        applied = await state.replan_on_blocker(report, decomposer)

        assert applied is False
        assert decomposer.seen == []
        assert state.blackboard is bb

    @pytest.mark.asyncio
    async def test_replan_assigned_step_not_in_plan_is_noop(self) -> None:
        """An assignment referencing a step id absent from the plan is a
        no-op, no crash — covers the `if step is None: return False` branch.
        """
        bb = Blackboard(plan=_make_plan(), assignments={"id-123": ("step-missing",)})
        state = SupervisorState(blackboard=bb)
        decomposer = _FakeDecomposer(
            (PlanStep(id="sub", description="should never be applied"),)
        )
        report = Report(
            worker="coder", worker_id="id-123", summary="blocked", status="failed"
        )

        applied = await state.replan_on_blocker(report, decomposer)

        assert applied is False
        assert decomposer.seen == []
        assert state.blackboard is bb

    @pytest.mark.asyncio
    async def test_replan_multi_step_worker_decomposes_first(self) -> None:
        """A worker owning multiple steps only has the FIRST assigned step
        decomposed — pins the documented minimal behavior."""
        bb = Blackboard(plan=_make_plan(), assignments={"id-123": ("step-2", "step-3")})
        state = SupervisorState(blackboard=bb)
        sub = PlanStep(id="step-2a", description="Implement part A")
        decomposer = _FakeDecomposer((sub,))
        report = Report(
            worker="coder", worker_id="id-123", summary="blocked", status="failed"
        )

        applied = await state.replan_on_blocker(report, decomposer)

        assert applied is True
        assert len(decomposer.seen) == 1
        assert decomposer.seen[0].id == "step-2"
        patched_step2 = next(s for s in state.blackboard.plan.steps if s.id == "step-2")
        patched_step3 = next(s for s in state.blackboard.plan.steps if s.id == "step-3")
        assert patched_step2.substeps == [sub]
        assert patched_step3.substeps == []

    @pytest.mark.asyncio
    async def test_non_blocker_report_is_a_noop(self) -> None:
        """A 'completed' report must not trigger a replan — plan is unchanged."""
        bb = Blackboard(plan=_make_plan(), assignments={"worker-a": ("step-2",)})
        state = SupervisorState(blackboard=bb)
        decomposer = _FakeDecomposer(
            (PlanStep(id="step-2a", description="should never be applied"),)
        )
        report = Report(worker="worker-a", summary="all good", status="completed")

        applied = await state.replan_on_blocker(report, decomposer)

        assert applied is False
        assert decomposer.seen == []
        assert state.blackboard is bb
        patched_step = next(s for s in state.blackboard.plan.steps if s.id == "step-2")
        assert patched_step.substeps == []

    def test_is_blocker_allow_list(self) -> None:
        assert is_blocker(Report(worker="w", summary="", status="failed")) is True
        assert is_blocker(Report(worker="w", summary="", status="completed")) is False
        assert is_blocker(Report(worker="w", summary="", status="cancelled")) is False
        assert is_blocker(Report(worker="w", summary="", status="pending")) is False
        assert is_blocker(Report(worker="w", summary="", status="running")) is False


class TestPlannerSubagentContextIsolation:
    @pytest.mark.asyncio
    async def test_planner_subagent_keeps_supervisor_context_small(self) -> None:
        """REQ-007: planning runs in a subagent; only `.output` reaches the Plan."""
        plan_json = json.dumps(
            {
                "type": "plan",
                "goal": "Ship feature X",
                "steps": [
                    {"id": "step-1", "title": "Research the topic"},
                    {"id": "step-2", "title": "Implement the feature"},
                ],
            }
        )
        secret_transcript = Message(
            role="assistant", content="SECRET_PLANNING_REASONING"
        )
        result = SubagentResult(
            agent_id="agent-planner",
            status=SubagentStatus(state="completed"),
            output=plan_json,
            messages=[secret_transcript],
        )
        orchestrator = _FakeOrchestrator(result)
        spec = SubagentSpec(name="planner", system_prompt="You are the planner.")

        plan = await plan_via_subagent(orchestrator, spec, "plan the feature")

        assert plan.goal == "Ship feature X"
        assert [s.id for s in plan.steps] == ["step-1", "step-2"]
        assert [s.description for s in plan.steps] == [
            "Research the topic",
            "Implement the feature",
        ]
        # Context-isolation proof: nothing derived from `.messages` leaks in.
        plan_repr = repr(plan)
        assert "SECRET_PLANNING_REASONING" not in plan_repr
        assert len(orchestrator.spawned) == 1
        _, task = orchestrator.spawned[0]
        assert task == "plan the feature"

    @pytest.mark.asyncio
    async def test_plan_via_subagent_maps_success_criteria_to_dod(self) -> None:
        """Regression: `schemas.PlanStep.success_criteria` must survive the
        adaptation into `orchestration.types.PlanStep.dod_criteria` — it is
        contract material for verify-before-done (Epic H2), and was
        previously dropped on the floor by `PlanStep(id=..., description=...)`
        omitting the field entirely.
        """
        plan_json = json.dumps(
            {
                "type": "plan",
                "goal": "Ship feature X",
                "steps": [
                    {
                        "id": "step-1",
                        "title": "Research the topic",
                        "success_criteria": ["notes exist", "sources cited"],
                    },
                    {
                        "id": "step-2",
                        "title": "Implement the feature",
                        "success_criteria": ["tests pass"],
                    },
                ],
            }
        )
        result = SubagentResult(
            agent_id="agent-planner",
            status=SubagentStatus(state="completed"),
            output=plan_json,
        )
        orchestrator = _FakeOrchestrator(result)
        spec = SubagentSpec(name="planner", system_prompt="You are the planner.")

        plan = await plan_via_subagent(orchestrator, spec, "plan the feature")

        assert plan.steps[0].dod_criteria == ("notes exist", "sources cited")
        assert plan.steps[1].dod_criteria == ("tests pass",)


class TestWriteSerializationReadOnlyParallel:
    @pytest.mark.asyncio
    async def test_parallel_only_for_readonly_writes_serialized(self) -> None:
        """REQ-010: writes are serialized; read-only workers overlap freely
        but their state MUTATIONS still land correctly (no lost update).

        (a) gates the raw `_write_lock` to prove two write-guarded critical
        sections never overlap. (b) drives TWO concurrent `read_only=True`
        `create_spawn_subagent_tool` calls through a gated fake orchestrator
        that only releases once BOTH have entered `spawn()` — proving the
        EXECUTION genuinely overlaps — then asserts both workers land in
        `state.workers`/`state.reports` (nothing dropped).
        """
        bb = Blackboard(plan=_make_plan())
        state = SupervisorState(blackboard=bb)

        # --- (a) write-guarded critical section: must never exceed 1. ---
        in_section = 0
        max_in_section = 0
        first_entered = asyncio.Event()
        release_first = asyncio.Event()

        async def guarded_write(is_first: bool) -> None:
            nonlocal in_section, max_in_section
            async with state._write_lock:
                in_section += 1
                max_in_section = max(max_in_section, in_section)
                if is_first:
                    first_entered.set()
                    await release_first.wait()
                in_section -= 1

        async def second_write() -> None:
            await first_entered.wait()
            # The lock must already be held by the first writer — the
            # second writer's `async with` blocks here until released.
            assert state._write_lock.locked()
            release_first.set()
            await guarded_write(is_first=False)

        await asyncio.gather(guarded_write(is_first=True), second_write())

        assert max_in_section == 1

        # --- (b) read_only spawn_subagent execution overlaps; mutations land. ---
        orchestrator = _GatedOrchestrator()
        execute = create_spawn_subagent_tool(state, orchestrator)

        await asyncio.gather(
            execute(_ro_args("scanner-a", "a", "step-1")),
            execute(_ro_args("scanner-b", "b", "step-2")),
        )

        # Execution genuinely overlapped (both entered spawn() before either
        # could exit) — proves read-only execution is NOT lock-serialized,
        # yet both workers' mutations landed — no lost update.
        assert orchestrator.max_entered == 2
        assert len(state.workers) == 2
        assert len(state.reports) == 2
        assert {r.status for r in state.reports} == {"completed"}
