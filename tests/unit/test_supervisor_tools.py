"""Tests for the supervisor's spawn_subagent / read_reports / mailbox
addressing (H6 supervisor-orchestrator, Task 2 + Task 4).

Covers REQ-001 (spawn_subagent surface), REQ-002 (kernel-backed runtime,
tested in `test_supervisor_tools_wiring.py`), REQ-006 (read_reports is
result-only), and REQ-010 (single-threaded writes, parallel read-only
execution). TDD: written before the implementation exists.

Split from a single >400-line file (Task 4 fix-loop, MINOR finding):
`update_plan`/`send_message`/`finalize`/kernel-wiring coverage lives in
`test_supervisor_tools_wiring.py`. This file keeps spawn/read_reports/
mailbox-addressing coverage — all existing test names/assertions here are
unchanged from before the split.

Uses FAKES for the subagent orchestrator — no live LLM, no network.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from swarmline.orchestration.subagent_types import (
    SubagentResult,
    SubagentSpec,
    SubagentStatus,
)
from swarmline.orchestration.supervisor.blackboard import Blackboard
from swarmline.orchestration.supervisor.state import OutboxMessage, SupervisorState
from swarmline.orchestration.supervisor.tools import (
    create_read_reports_tool,
    create_send_message_tool,
    create_spawn_subagent_tool,
)
from swarmline.orchestration.supervisor.types import Report
from swarmline.orchestration.types import Plan, PlanStep
from swarmline.protocols.host_adapter import AgentHandle
from swarmline.runtime.types import Message

FIXED_UUID = uuid.UUID("11111111-1111-1111-1111-111111111111")


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


class TestSpawnSubagent:
    @pytest.mark.asyncio
    async def test_spawn_subagent_creates_scoped_worker(self) -> None:
        """Scoping must work from a caller-supplied `step_ids` alone.

        Deliberately does NOT monkeypatch `uuid4` and does NOT preload
        `Blackboard.assignments` — the old version of this test masked the
        real defect (spawn minted a fresh UUID with no way for the caller to
        assign steps to it) by pre-seeding the assignment under a fixed UUID.
        This version proves the assignment is recorded BY the spawn call
        itself, from the `step_ids` argument.
        """
        bb = Blackboard(plan=_make_plan())
        state = SupervisorState(blackboard=bb)
        result = SubagentResult(
            agent_id="agent-xyz",
            status=SubagentStatus(state="completed"),
            output="research done",
        )
        orchestrator = _FakeOrchestrator(result)
        execute = create_spawn_subagent_tool(state, orchestrator)

        output = await execute(
            {
                "role": "researcher",
                "task": "research the topic",
                "step_ids": ["step-1"],
            }
        )

        assert isinstance(output, str)
        assert len(state.workers) == 1
        worker_id, handle = next(iter(state.workers.items()))
        assert handle.role == "researcher"
        assert len(orchestrator.spawned) == 1
        spec, task = orchestrator.spawned[0]
        assert task == "research the topic"
        # Scoped slice content present (assigned by THIS spawn call, from
        # step_ids — not pre-seeded on the Blackboard)...
        assert "Ship feature X" in spec.system_prompt
        assert "step-1" in spec.system_prompt
        assert "Research" in spec.system_prompt
        # ...but NOT the whole plan / other workers' steps.
        assert "step-2" not in spec.system_prompt
        assert "step-3" not in spec.system_prompt
        assert "Implement" not in spec.system_prompt
        assert "Verify" not in spec.system_prompt
        assert state.blackboard.assignments[worker_id] == ("step-1",)
        assert len(state.reports) == 1
        assert state.reports[0] == Report(
            worker="researcher",
            worker_id=worker_id,
            summary="research done",
            status="completed",
        )

    @pytest.mark.asyncio
    async def test_spawn_subagent_rejects_unknown_step_id(self) -> None:
        """An unknown step id must surface as a clear tool error, not a silent drop."""
        bb = Blackboard(plan=_make_plan())
        state = SupervisorState(blackboard=bb)
        orchestrator = _FakeOrchestrator(
            SubagentResult(
                agent_id="agent-xyz",
                status=SubagentStatus(state="completed"),
                output="done",
            )
        )
        execute = create_spawn_subagent_tool(state, orchestrator)

        with pytest.raises(ValueError, match="no-such-step"):
            await execute(
                {
                    "role": "researcher",
                    "task": "research the topic",
                    "step_ids": ["no-such-step"],
                }
            )

        # No partial state recorded on the error path.
        assert orchestrator.spawned == []
        assert state.workers == {}
        assert state.reports == ()
        assert state.blackboard is bb


class TestSpawnSubagentLockDiscipline:
    """MAJOR-2 regression (REQ-010): `read_only=True` used to skip
    `state._write_lock` ENTIRELY, so even `assign_steps`/`register_worker`/
    `add_report` (state mutations) went unlocked. Deterministic — spies on
    `state._write_lock.locked()` at each call site instead of relying on
    timing, which is what actually discriminates the old (mutations never
    locked for read_only) behavior from the fixed (mutations always
    short-locked; only the spawn/wait EXECUTION span differs) behavior.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "read_only,expected_execution_locked",
        [
            pytest.param(True, False, id="read_only-execution-unlocked"),
            pytest.param(False, True, id="write-worker-execution-locked"),
        ],
    )
    async def test_mutations_always_locked_execution_lock_depends_on_read_only(
        self, read_only: bool, expected_execution_locked: bool
    ) -> None:
        bb = Blackboard(plan=_make_plan())
        state = SupervisorState(blackboard=bb)
        lock_log: dict[str, list[bool]] = {
            "assign": [],
            "spawn": [],
            "wait": [],
            "register": [],
            "report": [],
        }

        original_assign = state.assign_steps
        original_register = state.register_worker
        original_add_report = state.add_report

        def spy_assign(worker_id: str, step_ids: list[str]) -> None:
            lock_log["assign"].append(state._write_lock.locked())
            original_assign(worker_id, step_ids)

        def spy_register(handle: AgentHandle) -> None:
            lock_log["register"].append(state._write_lock.locked())
            original_register(handle)

        def spy_add_report(report: Report) -> None:
            lock_log["report"].append(state._write_lock.locked())
            original_add_report(report)

        # Instance-level monkeypatch of a bound method — intentional spy,
        # not a real type mismatch (the plain function's shape matches the
        # bound method's after `self` binding).
        state.assign_steps = spy_assign  # ty: ignore[invalid-assignment]
        state.register_worker = spy_register  # ty: ignore[invalid-assignment]
        state.add_report = spy_add_report  # ty: ignore[invalid-assignment]

        class _SpyOrchestrator:
            async def spawn(self, spec: SubagentSpec, task: str) -> str:
                lock_log["spawn"].append(state._write_lock.locked())
                return "agent-spy"

            async def wait(self, agent_id: str) -> SubagentResult:
                lock_log["wait"].append(state._write_lock.locked())
                return SubagentResult(
                    agent_id=agent_id,
                    status=SubagentStatus(state="completed"),
                    output="done",
                )

        execute = create_spawn_subagent_tool(state, _SpyOrchestrator())

        await execute(
            {
                "role": "worker",
                "task": "do work",
                "step_ids": ["step-1"],
                "read_only": read_only,
            }
        )

        # Mutations are ALWAYS serialized under the lock, regardless of read_only.
        assert lock_log["assign"] == [True]
        assert lock_log["register"] == [True]
        assert lock_log["report"] == [True]
        # The spawn/wait EXECUTION span is locked only for write workers.
        assert lock_log["spawn"] == [expected_execution_locked]
        assert lock_log["wait"] == [expected_execution_locked]
        assert state._write_lock.locked() is False


class TestReadReportsResultOnly:
    @pytest.mark.asyncio
    async def test_read_reports_returns_result_only_not_transcript(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            "swarmline.orchestration.supervisor.tools.uuid4", lambda: FIXED_UUID
        )
        bb = Blackboard(plan=_make_plan(), assignments={str(FIXED_UUID): ("step-1",)})
        state = SupervisorState(blackboard=bb)
        transcript = Message(role="assistant", content="SECRET_INTERNAL_REASONING_XYZ")
        result = SubagentResult(
            agent_id="agent-xyz",
            status=SubagentStatus(state="completed"),
            output="done",
            messages=[transcript],
        )
        orchestrator = _FakeOrchestrator(result)
        spawn_execute = create_spawn_subagent_tool(state, orchestrator)
        await spawn_execute({"role": "coder", "task": "fix the bug"})

        read_execute = create_read_reports_tool(state)
        output = await read_execute({})

        assert "done" in output
        assert "completed" in output
        assert "SECRET_INTERNAL_REASONING_XYZ" not in output


class TestMailboxAddressing:
    @pytest.mark.asyncio
    async def test_send_message_reaches_worker_by_id_from_read_reports(self) -> None:
        """MAJOR-3 regression (mailbox role/id addressing mismatch).

        `read_reports` used to surface only the worker's ROLE, but
        `drain_for` is keyed by `worker_id` — a supervisor addressing
        `send_message(to=role, ...)` would queue a message that the worker
        never drains. Proves the round-trip is now consistent: the id
        `read_reports` surfaces is exactly the id `drain_for` consumes, and
        addressing by role (the OLD, broken behavior) does NOT deliver.
        """
        bb = Blackboard(plan=_make_plan())
        state = SupervisorState(blackboard=bb)
        orchestrator = _FakeOrchestrator(
            SubagentResult(
                agent_id="agent-xyz",
                status=SubagentStatus(state="completed"),
                output="done",
            )
        )
        spawn_execute = create_spawn_subagent_tool(state, orchestrator)
        await spawn_execute(
            {"role": "coder", "task": "fix the bug", "step_ids": ["step-1"]}
        )
        worker_id = next(iter(state.workers))

        read_execute = create_read_reports_tool(state)
        reports_output = await read_execute({})

        assert worker_id in reports_output

        send_execute = create_send_message_tool(state)
        await send_execute({"to": worker_id, "content": "please retry with fix"})

        assert state.drain_for(worker_id) == (
            OutboxMessage(to=worker_id, content="please retry with fix"),
        )
        # Addressing by the ROLE (the old, broken habit) delivers nothing.
        assert state.drain_for("coder") == ()
