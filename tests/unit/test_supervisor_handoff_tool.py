"""Unit: opt-in `handoff` tool on `build_supervisor` (I-046, kernel-wiring Task 3).

Covers REQ-009/010/011/012/013. `handoff_tool.py` mirrors `finalize.py`'s
shape: a `ToolSpec` constant + `create_<name>_tool(...) -> executor` factory,
binding the EXISTING `handoff()` primitive (H6, handoff.py:52) as a 6th,
opt-in supervisor tool. Uses a FAKE `GraphHandoffRunner` — no live LLM, no
network, no real graph orchestrator.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from swarmline.orchestration.subagent_types import SubagentResult, SubagentSpec
from swarmline.orchestration.supervisor.blackboard import Blackboard
from swarmline.orchestration.supervisor.handoff_tool import (
    HANDOFF_TOOL_SPEC,
    create_handoff_tool,
)
from swarmline.orchestration.supervisor.kernel import SupervisorKernel, build_supervisor
from swarmline.orchestration.supervisor.state import SupervisorState
from swarmline.orchestration.types import Plan, PlanStep


def _make_plan() -> Plan:
    return Plan(
        id="plan-1",
        goal="Ship feature X",
        steps=[
            PlanStep(id="step-1", description="Research"),
            PlanStep(id="step-2", description="Implement"),
        ],
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
    )


class _FakeSubagentOrchestrator:
    """Minimal SubagentSpawner fake — unused by these tests but required to
    construct `build_supervisor` (mirrors test_supervisor_tools_wiring.py's
    `_FakeOrchestrator` construction pattern)."""

    async def spawn(self, spec: SubagentSpec, task: str) -> str:  # pragma: no cover
        return "agent-xyz"

    async def wait(self, agent_id: str) -> SubagentResult:  # pragma: no cover
        raise NotImplementedError


class _FakeGraphHandoffRunner:
    """Fake `GraphHandoffRunner`: records `delegate`/`wait_for_task` calls,
    returns a canned sentinel result."""

    def __init__(self, result: str | None = "handoff-sentinel-result") -> None:
        self.result = result
        self.delegated: list[Any] = []
        self.waited: list[tuple[str, float | None]] = []

    async def delegate(self, request: Any) -> None:
        self.delegated.append(request)

    async def wait_for_task(
        self, task_id: str, timeout: float | None = None
    ) -> str | None:
        self.waited.append((task_id, timeout))
        return self.result


def _make_state() -> SupervisorState:
    return SupervisorState(blackboard=Blackboard(plan=_make_plan()))


class TestBuildSupervisorHandoffOptIn:
    @pytest.mark.asyncio
    async def test_build_supervisor_handoff_kwarg_adds_sixth_tool(self) -> None:
        """REQ-009: `handoff_runner` set -> 6th `handoff` tool, wired end-to-end
        to the injected fake runner's `delegate` + `wait_for_task`."""
        state = _make_state()
        orchestrator = _FakeSubagentOrchestrator()
        runner = _FakeGraphHandoffRunner(result="delegated-ok")

        supervisor = build_supervisor(state, orchestrator, handoff_runner=runner)

        assert isinstance(supervisor, SupervisorKernel)
        expected_names = {
            "spawn_subagent",
            "update_plan",
            "send_message",
            "read_reports",
            "finalize",
            "handoff",
        }
        assert {spec.name for spec in supervisor.active_tools} == expected_names
        assert set(supervisor.local_tools.keys()) == expected_names

        output = await supervisor.local_tools["handoff"](
            {"agent_id": "worker-1", "goal": "do the subtask"}
        )

        assert output == "delegated-ok"
        assert len(runner.delegated) == 1
        assert runner.delegated[0].agent_id == "worker-1"
        assert runner.delegated[0].goal == "do the subtask"
        assert len(runner.waited) == 1

    def test_default_supervisor_keeps_exact_five_tools(self) -> None:
        """REQ-010: no `handoff_runner` -> exactly the 5 pre-existing tool
        names, no `handoff` — the default path stays byte-identical."""
        state = _make_state()
        orchestrator = _FakeSubagentOrchestrator()

        supervisor = build_supervisor(state, orchestrator)

        expected_names = {
            "spawn_subagent",
            "update_plan",
            "send_message",
            "read_reports",
            "finalize",
        }
        assert {spec.name for spec in supervisor.active_tools} == expected_names
        assert set(supervisor.local_tools.keys()) == expected_names
        assert "handoff" not in supervisor.local_tools
        assert "handoff" not in {spec.name for spec in supervisor.active_tools}


class TestHandoffToolExecutor:
    @pytest.mark.asyncio
    async def test_handoff_tool_executor_invokes_handoff_primitive(self) -> None:
        """REQ-011: the executor maps tool args onto the existing `handoff()`
        primitive (agent_id/goal required, stage/parent_task_id/task_id/timeout
        optional) and returns its result."""
        runner = _FakeGraphHandoffRunner(result="worker-said-done")
        execute = create_handoff_tool(runner)

        output = await execute(
            {
                "agent_id": "worker-2",
                "goal": "review the PR",
                "stage": "review",
                "parent_task_id": "parent-1",
                "task_id": "handoff-42",
                "timeout": 5.0,
            }
        )

        assert output == "worker-said-done"
        assert len(runner.delegated) == 1
        request = runner.delegated[0]
        assert request.agent_id == "worker-2"
        assert request.goal == "review the PR"
        assert request.stage == "review"
        assert request.parent_task_id == "parent-1"
        assert request.task_id == "handoff-42"
        assert runner.waited == [("handoff-42", 5.0)]

    @pytest.mark.asyncio
    async def test_handoff_tool_executor_defaults_optional_args(self) -> None:
        """Optional args (`stage`/`parent_task_id`/`task_id`/`timeout`) default
        the same way the bare `handoff()` primitive does when omitted."""
        runner = _FakeGraphHandoffRunner(result="ok")
        execute = create_handoff_tool(runner)

        await execute({"agent_id": "worker-3", "goal": "minimal call"})

        request = runner.delegated[0]
        assert request.agent_id == "worker-3"
        assert request.goal == "minimal call"
        assert request.stage == ""
        assert request.parent_task_id is None
        # task_id is auto-generated (uuid4) when omitted — just not empty.
        assert request.task_id
        assert runner.waited[0][1] is None

    @pytest.mark.asyncio
    async def test_handoff_tool_executor_returns_placeholder_when_no_result(
        self,
    ) -> None:
        """When `handoff()` returns `None` (timeout / task never registered),
        the executor still returns a clear, non-empty string — never `None`."""
        runner = _FakeGraphHandoffRunner(result=None)
        execute = create_handoff_tool(runner)

        output = await execute({"agent_id": "worker-4", "goal": "never finishes"})

        assert isinstance(output, str)
        assert output.strip() != ""


class TestHandoffToolSpec:
    def test_handoff_tool_spec_declares_required_and_optional_args(self) -> None:
        """`HANDOFF_TOOL_SPEC` names required (`agent_id`, `goal`) vs. optional
        (`stage`, `parent_task_id`, `task_id`, `timeout`) parameters."""
        assert HANDOFF_TOOL_SPEC.name == "handoff"
        assert HANDOFF_TOOL_SPEC.is_local is True
        assert set(HANDOFF_TOOL_SPEC.parameters["required"]) == {"agent_id", "goal"}
        properties = HANDOFF_TOOL_SPEC.parameters["properties"]
        assert {
            "agent_id",
            "goal",
            "stage",
            "parent_task_id",
            "task_id",
            "timeout",
        }.issubset(properties.keys())


class TestHandoffToolImportLight:
    def test_importing_handoff_tool_does_not_eagerly_pull_graph_orchestrator(
        self,
    ) -> None:
        """I-020: importing `handoff_tool` alone must not eagerly pull the
        `graph_orchestrator` import chain — `handoff()` lazy-imports
        `DelegationRequest` inside the function body, and `handoff_tool.py`
        must not add a module-level heavy import on top of that."""
        import subprocess
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[2]
        code = (
            "import sys\n"
            "import swarmline.orchestration.supervisor.handoff_tool\n"
            "assert 'swarmline.multi_agent.graph_orchestrator' not in sys.modules\n"
            "print('OK')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=repo_root, capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
        assert "OK" in result.stdout
