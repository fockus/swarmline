"""Tests for update_plan / send_message / finalize + supervisor kernel wiring.

H6 supervisor-orchestrator, Task 2 (REQ-001, REQ-002). Split out of
`test_supervisor_tools.py` (Task 4 fix-loop, MINOR finding — that file was
>400 lines): spawn_subagent/read_reports/mailbox-addressing coverage stays
there; this file keeps update_plan/send_message/finalize/kernel-wiring.
All test names/assertions below are unchanged from before the split.

Uses FAKES for the subagent orchestrator — no live LLM, no network.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from swarmline.orchestration.subagent_types import (
    SubagentResult,
    SubagentSpec,
    SubagentStatus,
)
from swarmline.orchestration.supervisor.blackboard import Blackboard, PlanPatch
from swarmline.orchestration.supervisor.finalize import (
    FINALIZE_TOOL_SPEC,
    create_finalize_tool,
)
from swarmline.orchestration.supervisor.kernel import SupervisorKernel, build_supervisor
from swarmline.orchestration.supervisor.state import OutboxMessage, SupervisorState
from swarmline.orchestration.supervisor.tools import (
    READ_REPORTS_TOOL_SPEC,
    SEND_MESSAGE_TOOL_SPEC,
    SPAWN_SUBAGENT_TOOL_SPEC,
    UPDATE_PLAN_TOOL_SPEC,
    create_send_message_tool,
    create_update_plan_tool,
)
from swarmline.orchestration.supervisor.types import Report
from swarmline.orchestration.types import Plan, PlanStep


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

    def __init__(self, result: SubagentResult, agent_id: str = "agent-xyz") -> None:
        self.result = result
        self.agent_id = agent_id
        self.spawned: list[tuple[SubagentSpec, str]] = []

    async def spawn(self, spec: SubagentSpec, task: str) -> str:
        self.spawned.append((spec, task))
        return self.agent_id

    async def wait(self, agent_id: str) -> SubagentResult:
        assert agent_id == self.agent_id
        return self.result


class TestUpdatePlan:
    @pytest.mark.asyncio
    async def test_update_plan_writes_to_blackboard(self) -> None:
        bb = Blackboard(plan=_make_plan())
        state = SupervisorState(blackboard=bb)
        execute = create_update_plan_tool(state)

        output = await execute(
            {"step_id": "step-2", "status": "completed", "result": "done"}
        )

        assert isinstance(output, str)
        assert state.blackboard is not bb
        original_step = next(s for s in bb.plan.steps if s.id == "step-2")
        assert original_step.status == "pending"
        patched_step = next(s for s in state.blackboard.plan.steps if s.id == "step-2")
        assert patched_step.status == "completed"
        assert patched_step.result == "done"
        # description was not provided in args — preserved from the current step.
        assert patched_step.description == "Implement"

    @pytest.mark.asyncio
    async def test_update_plan_preserves_unspecified_step_fields(self) -> None:
        """A status-only patch must not clobber substeps/dod_criteria/etc.

        Regression for the data-loss defect: the executor used to build a
        BRAND-NEW `PlanStep(id=..., description=..., status=..., result=...)`,
        silently resetting `substeps`/`dod_criteria`/`dod_verified`/
        `verification_log` to their defaults on every call — even when only
        `status` was patched.
        """
        substeps = [PlanStep(id="step-2a", description="Implement part A")]
        rich_step = PlanStep(
            id="step-2",
            description="Implement",
            status="pending",
            substeps=substeps,
            dod_criteria=("crit-a",),
            dod_verified=True,
            verification_log="prior run",
        )
        plan = Plan(
            id="plan-1",
            goal="Ship feature X",
            steps=[
                PlanStep(id="step-1", description="Research"),
                rich_step,
                PlanStep(id="step-3", description="Verify"),
            ],
            created_at=datetime(2026, 7, 1, tzinfo=UTC),
        )
        bb = Blackboard(plan=plan)
        state = SupervisorState(blackboard=bb)
        execute = create_update_plan_tool(state)

        await execute({"step_id": "step-2", "status": "in_progress"})

        patched_step = next(s for s in state.blackboard.plan.steps if s.id == "step-2")
        assert patched_step.status == "in_progress"
        assert patched_step.substeps == substeps
        assert patched_step.dod_criteria == ("crit-a",)
        assert patched_step.dod_verified is True
        assert patched_step.verification_log == "prior run"


class TestSendMessage:
    @pytest.mark.asyncio
    async def test_send_message_appends_to_outbox(self) -> None:
        """Task-2 intent preserved on the Task-3 mailbox-backed reality.

        `send_message` now delivers into `state._mailbox` (a frozen
        `Mailbox`); `.outbox` stays observable and `drain_for` proves the
        message is addressed to the right recipient.
        """
        bb = Blackboard(plan=_make_plan())
        state = SupervisorState(blackboard=bb)
        execute = create_send_message_tool(state)

        output = await execute({"to": "coder", "content": "please retry with fix"})

        assert isinstance(output, str)
        assert state.outbox == (
            OutboxMessage(to="coder", content="please retry with fix"),
        )
        assert state.drain_for("coder") == (
            OutboxMessage(to="coder", content="please retry with fix"),
        )

    @pytest.mark.asyncio
    async def test_supervisor_corrects_worker_via_mailbox_midrun(self) -> None:
        """Scenario 2: supervisor reads a worker blocker → corrects via mailbox.

        Proves addressed, once-only delivery at the state/unit level: the
        message reaches exactly the intended worker, a different worker's
        drain is empty, and a second drain of the same worker is empty too
        (not re-delivered).
        """
        bb = Blackboard(plan=_make_plan())
        state = SupervisorState(blackboard=bb)
        execute = create_send_message_tool(state)

        output = await execute(
            {"to": "worker-blocked", "content": "unblock: use fallback endpoint"}
        )

        assert isinstance(output, str)
        assert state.drain_for("worker-blocked") == (
            OutboxMessage(
                to="worker-blocked", content="unblock: use fallback endpoint"
            ),
        )
        assert state.drain_for("worker-other") == ()
        # Once-only: draining again yields nothing — it was not re-delivered.
        assert state.drain_for("worker-blocked") == ()


class TestWriteLockDiscipline:
    """MAJOR fix-cycle-3 regression (REQ-010, GPT-5.5 r2): `update_plan`'s
    read-modify-write and `send_message`'s mutation used to run entirely
    OUTSIDE `state._write_lock` — only `spawn_subagent`'s lifecycle was
    serialized (cycle 2). Since ThinRuntime executes native tool calls
    concurrently (`asyncio.gather`), either could interleave with
    `replan_on_blocker`'s locked, `await`-spanning write flow and clobber a
    stale blackboard snapshot. Deterministic — spies on
    `state._write_lock.locked()` at the moment the underlying mutator runs
    (mirrors `TestSpawnSubagentLockDiscipline` in `test_supervisor_tools.py`),
    plus one genuine concurrency proof gated by `asyncio.Event` (no
    sleeps/timing).
    """

    @pytest.mark.asyncio
    async def test_update_plan_mutation_runs_under_write_lock(self) -> None:
        bb = Blackboard(plan=_make_plan())
        state = SupervisorState(blackboard=bb)
        lock_log: list[bool] = []
        original_update_plan = state.update_plan

        def spy_update_plan(patch: PlanPatch) -> None:
            lock_log.append(state._write_lock.locked())
            original_update_plan(patch)

        # Instance-level monkeypatch of a bound method — intentional spy,
        # not a real type mismatch (mirrors TestSpawnSubagentLockDiscipline).
        state.update_plan = spy_update_plan  # ty: ignore[invalid-assignment]
        execute = create_update_plan_tool(state)

        await execute({"step_id": "step-2", "status": "completed", "result": "done"})

        assert lock_log == [True]

    @pytest.mark.asyncio
    async def test_send_message_runs_under_write_lock(self) -> None:
        bb = Blackboard(plan=_make_plan())
        state = SupervisorState(blackboard=bb)
        lock_log: list[bool] = []
        original_send_message = state.send_message

        def spy_send_message(to: str, content: str) -> None:
            lock_log.append(state._write_lock.locked())
            original_send_message(to=to, content=content)

        state.send_message = spy_send_message  # ty: ignore[invalid-assignment]
        execute = create_send_message_tool(state)

        await execute({"to": "coder", "content": "retry"})

        assert lock_log == [True]

    @pytest.mark.asyncio
    async def test_update_plan_blocks_while_replan_holds_lock(self) -> None:
        """Concurrency proof: `replan_on_blocker` holds `_write_lock` across
        its `await decompose(...)`. A concurrent `update_plan` executor must
        not land its mutation until the lock is released, and must then
        observe the POST-replan blackboard — not a stale pre-replan snapshot
        read before the lock was ever acquired.
        """
        bb = Blackboard(plan=_make_plan())
        state = SupervisorState(blackboard=bb)
        state.assign_steps("worker-1", ["step-2"])
        report = Report(
            worker="coder", summary="stuck", status="failed", worker_id="worker-1"
        )

        entered_event = asyncio.Event()
        release_event = asyncio.Event()
        added_substep = PlanStep(id="step-2a", description="added by replan")

        class _GatedDecomposer:
            async def decompose(self, step: PlanStep) -> tuple[PlanStep, ...]:
                entered_event.set()
                await release_event.wait()
                return (added_substep,)

        execute = create_update_plan_tool(state)

        async def do_replan() -> bool:
            return await state.replan_on_blocker(report, _GatedDecomposer())

        async def do_update() -> None:
            await entered_event.wait()
            await execute(
                {"step_id": "step-2", "status": "completed", "result": "done"}
            )

        async def do_release() -> None:
            await entered_event.wait()
            # replan already holds the lock, parked inside decompose(): the
            # concurrently-launched update_plan must not have landed yet.
            assert state._write_lock.locked()
            still_pending = next(
                s for s in state.blackboard.plan.steps if s.id == "step-2"
            )
            assert still_pending.status == "pending"
            release_event.set()

        await asyncio.gather(do_replan(), do_update(), do_release())

        final_step = next(s for s in state.blackboard.plan.steps if s.id == "step-2")
        # update_plan landed AFTER replan released the lock, and preserved the
        # substep replan just added — proof it read the POST-replan snapshot,
        # not a stale pre-replan one captured before acquiring the lock.
        assert final_step.status == "completed"
        assert final_step.result == "done"
        assert final_step.substeps == [added_substep]


class TestFinalize:
    @pytest.mark.asyncio
    async def test_finalize_returns_summary_not_stub(self) -> None:
        bb = Blackboard(plan=_make_plan())
        state = SupervisorState(blackboard=bb)
        state.add_report(
            Report(worker="researcher", summary="found X", status="completed")
        )
        execute = create_finalize_tool(state)

        output = await execute({})

        assert isinstance(output, str)
        assert output.strip() != ""
        assert "researcher" in output
        assert "plan-1" in output


class TestSupervisorKernelWiring:
    def test_all_five_tools_wire_into_supervisor_kernel(self) -> None:
        bb = Blackboard(plan=_make_plan())
        state = SupervisorState(blackboard=bb)
        orchestrator = _FakeOrchestrator(
            SubagentResult(
                agent_id="a",
                status=SubagentStatus(state="completed"),
                output="",
            )
        )

        supervisor = build_supervisor(state, orchestrator)

        assert isinstance(supervisor, SupervisorKernel)
        expected_names = {
            "spawn_subagent",
            "update_plan",
            "send_message",
            "read_reports",
            "finalize",
        }
        assert {spec.name for spec in supervisor.active_tools} == expected_names
        assert set(supervisor.local_tools.keys()) == expected_names
        assert supervisor.runtime is not None

    def test_tool_specs_have_expected_names(self) -> None:
        specs = [
            SPAWN_SUBAGENT_TOOL_SPEC,
            UPDATE_PLAN_TOOL_SPEC,
            SEND_MESSAGE_TOOL_SPEC,
            READ_REPORTS_TOOL_SPEC,
            FINALIZE_TOOL_SPEC,
        ]
        assert [s.name for s in specs] == [
            "spawn_subagent",
            "update_plan",
            "send_message",
            "read_reports",
            "finalize",
        ]
        assert all(s.is_local for s in specs)
