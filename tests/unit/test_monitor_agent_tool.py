"""Tests for monitor_agent tool + spawn_agent run_in_background — TDD.

Covers: SUBAGENT_TOOL_SPEC run_in_background param, MONITOR_AGENT_TOOL_SPEC,
create_monitor_executor, background spawn flow (immediate return),
foreground spawn flow (unchanged), monitor_agent status/output retrieval,
ThinRuntime wiring of monitor_agent tool.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from swarmline.domain_types import ToolSpec
from swarmline.orchestration.subagent_types import (
    SubagentResult,
    SubagentSpec,
    SubagentStatus,
)
from swarmline.runtime.thin.subagent_tool import (
    MONITOR_AGENT_TOOL_SPEC,
    SUBAGENT_TOOL_SPEC,
    SubagentToolConfig,
    create_monitor_executor,
    create_subagent_executor,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def orchestrator() -> AsyncMock:
    """Mock ThinSubagentOrchestrator with spawn/wait/cancel/get_status/get_output."""
    mock = AsyncMock()
    mock.spawn.return_value = "agent-bg-001"
    mock.wait.return_value = SubagentResult(
        agent_id="agent-bg-001",
        status=SubagentStatus(state="completed", result="done"),
        output="Task completed successfully",
    )
    mock.cancel = AsyncMock()
    mock.get_status = AsyncMock(
        return_value=SubagentStatus(state="completed", result="done"),
    )
    mock.get_output = lambda agent_id: "bg output"
    return mock


@pytest.fixture
def config() -> SubagentToolConfig:
    return SubagentToolConfig()


@pytest.fixture
def parent_tools() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="read_file", description="Read a file", parameters={"type": "object"}
        ),
        ToolSpec(
            name="write_file", description="Write a file", parameters={"type": "object"}
        ),
    ]


# ---------------------------------------------------------------------------
# 1. SUBAGENT_TOOL_SPEC has run_in_background parameter
# ---------------------------------------------------------------------------


class TestSubagentToolSpecRunInBackground:
    def test_spec_has_run_in_background_property(self) -> None:
        props = SUBAGENT_TOOL_SPEC.parameters.get("properties", {})
        assert "run_in_background" in props

    def test_run_in_background_is_boolean(self) -> None:
        props = SUBAGENT_TOOL_SPEC.parameters.get("properties", {})
        assert props["run_in_background"]["type"] == "boolean"

    def test_run_in_background_not_required(self) -> None:
        required = SUBAGENT_TOOL_SPEC.parameters.get("required", [])
        assert "run_in_background" not in required


# ---------------------------------------------------------------------------
# 2. MONITOR_AGENT_TOOL_SPEC validation
# ---------------------------------------------------------------------------


class TestMonitorAgentToolSpec:
    def test_spec_name_is_monitor_agent(self) -> None:
        assert MONITOR_AGENT_TOOL_SPEC.name == "monitor_agent"

    def test_spec_has_description(self) -> None:
        assert MONITOR_AGENT_TOOL_SPEC.description
        assert len(MONITOR_AGENT_TOOL_SPEC.description) > 10

    def test_spec_has_agent_id_required(self) -> None:
        props = MONITOR_AGENT_TOOL_SPEC.parameters.get("properties", {})
        assert "agent_id" in props
        required = MONITOR_AGENT_TOOL_SPEC.parameters.get("required", [])
        assert "agent_id" in required

    def test_spec_is_local_tool(self) -> None:
        assert MONITOR_AGENT_TOOL_SPEC.is_local is True


# ---------------------------------------------------------------------------
# 3. Background spawn flow — immediate return
# ---------------------------------------------------------------------------


class TestBackgroundSpawnFlow:
    async def test_background_spawn_returns_immediately(
        self,
        orchestrator: AsyncMock,
        config: SubagentToolConfig,
        parent_tools: list[ToolSpec],
    ) -> None:
        executor = create_subagent_executor(orchestrator, config, parent_tools)
        raw = await executor({"task": "long work", "run_in_background": True})

        result = json.loads(raw)
        assert result["status"] == "spawned"
        assert result["agent_id"] == "agent-bg-001"
        orchestrator.wait.assert_not_awaited()

    async def test_background_spawn_sets_run_in_background_on_spec(
        self,
        orchestrator: AsyncMock,
        config: SubagentToolConfig,
        parent_tools: list[ToolSpec],
    ) -> None:
        executor = create_subagent_executor(orchestrator, config, parent_tools)
        await executor({"task": "bg task", "run_in_background": True})

        spec_arg: SubagentSpec = orchestrator.spawn.call_args[0][0]
        assert spec_arg.run_in_background is True


# ---------------------------------------------------------------------------
# 4. Foreground spawn flow — unchanged
# ---------------------------------------------------------------------------


class TestForegroundSpawnFlowUnchanged:
    async def test_foreground_spawn_waits_for_result(
        self,
        orchestrator: AsyncMock,
        config: SubagentToolConfig,
        parent_tools: list[ToolSpec],
    ) -> None:
        executor = create_subagent_executor(orchestrator, config, parent_tools)
        raw = await executor({"task": "quick work"})

        result = json.loads(raw)
        assert result["status"] == "completed"
        orchestrator.wait.assert_awaited_once()

    async def test_foreground_with_explicit_false(
        self,
        orchestrator: AsyncMock,
        config: SubagentToolConfig,
        parent_tools: list[ToolSpec],
    ) -> None:
        executor = create_subagent_executor(orchestrator, config, parent_tools)
        raw = await executor({"task": "quick work", "run_in_background": False})

        result = json.loads(raw)
        assert result["status"] == "completed"
        orchestrator.wait.assert_awaited_once()


# ---------------------------------------------------------------------------
# 5. create_monitor_executor — status retrieval
# ---------------------------------------------------------------------------


class TestMonitorExecutor:
    async def test_monitor_returns_status_json(self, orchestrator: AsyncMock) -> None:
        executor = create_monitor_executor(orchestrator)
        raw = await executor({"agent_id": "agent-bg-001"})

        result = json.loads(raw)
        assert result["agent_id"] == "agent-bg-001"
        assert result["state"] == "completed"

    async def test_monitor_includes_output(self, orchestrator: AsyncMock) -> None:
        executor = create_monitor_executor(orchestrator)
        raw = await executor({"agent_id": "agent-bg-001"})

        result = json.loads(raw)
        assert result["output"] == "bg output"

    async def test_monitor_missing_agent_id_returns_error(
        self, orchestrator: AsyncMock
    ) -> None:
        executor = create_monitor_executor(orchestrator)
        raw = await executor({})

        result = json.loads(raw)
        assert result["status"] == "error"
        assert "agent_id" in result["error"].lower()

    async def test_monitor_includes_error_for_failed_agent(
        self, orchestrator: AsyncMock
    ) -> None:
        orchestrator.get_status = AsyncMock(
            return_value=SubagentStatus(state="failed", error="crashed"),
        )
        orchestrator.get_output = lambda agent_id: ""
        executor = create_monitor_executor(orchestrator)
        raw = await executor({"agent_id": "agent-fail"})

        result = json.loads(raw)
        assert result["state"] == "failed"
        assert result["error"] == "crashed"


# ---------------------------------------------------------------------------
# 6. ThinRuntime — _bg_events draining in run()
# ---------------------------------------------------------------------------


class TestThinRuntimeBgEventsDraining:
    """ThinRuntime yields pending _bg_events during event loop iteration."""

    async def test_bg_events_drained_during_run(self) -> None:
        """Simulate: add event to _bg_events, verify it's yielded in run()."""
        from swarmline.domain_types import RuntimeEvent
        from swarmline.runtime.thin.runtime import ThinRuntime

        runtime = ThinRuntime()
        bg_event = RuntimeEvent.background_complete(agent_id="bg-42", result="done")
        runtime._bg_events.append(bg_event)

        events: list[RuntimeEvent] = []
        from swarmline.runtime.types import Message

        async for evt in runtime.run(
            messages=[Message(role="user", content="hello")],
            system_prompt="test",
            active_tools=[],
        ):
            events.append(evt)

        bg_types = [e for e in events if e.type == "background_complete"]
        assert len(bg_types) == 1
        assert bg_types[0].data["agent_id"] == "bg-42"

    async def test_bg_events_cleared_after_drain(self) -> None:
        """After yielding, _bg_events list is empty."""
        from swarmline.domain_types import RuntimeEvent
        from swarmline.runtime.thin.runtime import ThinRuntime

        runtime = ThinRuntime()
        runtime._bg_events.append(
            RuntimeEvent.background_complete(agent_id="bg-99", result="ok")
        )

        from swarmline.runtime.types import Message

        async for _ in runtime.run(
            messages=[Message(role="user", content="hi")],
            system_prompt="test",
            active_tools=[],
        ):
            pass

        assert len(runtime._bg_events) == 0
