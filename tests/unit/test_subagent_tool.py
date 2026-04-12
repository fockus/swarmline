"""Tests for SubagentTool spec, config, and executor (Phase 3)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from swarmline.domain_types import ToolSpec
from swarmline.orchestration.subagent_types import SubagentResult, SubagentStatus
from swarmline.runtime.thin.subagent_tool import (
    SUBAGENT_TOOL_SPEC,
    SubagentToolConfig,
    create_subagent_executor,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def orchestrator() -> AsyncMock:
    """Mock ThinSubagentOrchestrator with spawn/wait/cancel."""
    mock = AsyncMock()
    mock.spawn.return_value = "agent-001"
    mock.wait.return_value = SubagentResult(
        agent_id="agent-001",
        status=SubagentStatus(state="completed", result="done"),
        output="Task completed successfully",
    )
    mock.cancel = AsyncMock()
    return mock


@pytest.fixture
def config() -> SubagentToolConfig:
    return SubagentToolConfig()


@pytest.fixture
def parent_tools() -> list[ToolSpec]:
    return [
        ToolSpec(name="read_file", description="Read a file", parameters={"type": "object"}),
        ToolSpec(name="write_file", description="Write a file", parameters={"type": "object"}),
        ToolSpec(name="search", description="Search", parameters={"type": "object"}),
    ]


# ---------------------------------------------------------------------------
# 1. SUBAGENT_TOOL_SPEC validation
# ---------------------------------------------------------------------------


class TestSubagentToolSpec:
    """Verify the spawn_agent ToolSpec is well-formed."""

    def test_spec_name_is_spawn_agent(self) -> None:
        assert SUBAGENT_TOOL_SPEC.name == "spawn_agent"

    def test_spec_has_description(self) -> None:
        assert SUBAGENT_TOOL_SPEC.description
        assert len(SUBAGENT_TOOL_SPEC.description) > 10

    def test_spec_parameters_schema_has_task(self) -> None:
        props = SUBAGENT_TOOL_SPEC.parameters.get("properties", {})
        assert "task" in props
        required = SUBAGENT_TOOL_SPEC.parameters.get("required", [])
        assert "task" in required

    def test_spec_parameters_schema_has_optional_fields(self) -> None:
        props = SUBAGENT_TOOL_SPEC.parameters.get("properties", {})
        assert "system_prompt" in props
        assert "tools" in props
        required = SUBAGENT_TOOL_SPEC.parameters.get("required", [])
        assert "system_prompt" not in required
        assert "tools" not in required

    def test_spec_is_local_tool(self) -> None:
        assert SUBAGENT_TOOL_SPEC.is_local is True


# ---------------------------------------------------------------------------
# 2. SubagentToolConfig defaults
# ---------------------------------------------------------------------------


class TestSubagentToolConfig:
    """Verify frozen config dataclass defaults."""

    def test_default_max_concurrent(self) -> None:
        cfg = SubagentToolConfig()
        assert cfg.max_concurrent == 4

    def test_default_max_depth(self) -> None:
        cfg = SubagentToolConfig()
        assert cfg.max_depth == 3

    def test_default_timeout(self) -> None:
        cfg = SubagentToolConfig()
        assert cfg.timeout_seconds == 300.0

    def test_config_is_frozen(self) -> None:
        cfg = SubagentToolConfig()
        with pytest.raises(AttributeError):
            cfg.max_depth = 10  # type: ignore[misc]

    def test_custom_values(self) -> None:
        cfg = SubagentToolConfig(max_concurrent=2, max_depth=5, timeout_seconds=60.0)
        assert cfg.max_concurrent == 2
        assert cfg.max_depth == 5
        assert cfg.timeout_seconds == 60.0


# ---------------------------------------------------------------------------
# 3. create_subagent_executor — happy path
# ---------------------------------------------------------------------------


class TestSubagentExecutorHappyPath:
    """spawn + wait completes successfully."""

    async def test_spawn_wait_returns_completed_json(
        self, orchestrator: AsyncMock, config: SubagentToolConfig, parent_tools: list[ToolSpec]
    ) -> None:
        executor = create_subagent_executor(orchestrator, config, parent_tools)
        raw = await executor({"task": "Summarize this document"})

        result = json.loads(raw)
        assert result["agent_id"] == "agent-001"
        assert result["status"] == "completed"
        assert result["result"] == "Task completed successfully"

    async def test_spawn_called_with_correct_spec(
        self, orchestrator: AsyncMock, config: SubagentToolConfig, parent_tools: list[ToolSpec]
    ) -> None:
        executor = create_subagent_executor(orchestrator, config, parent_tools)
        await executor({"task": "Do something", "system_prompt": "Be concise"})

        spec_arg = orchestrator.spawn.call_args[0][0]
        assert spec_arg.system_prompt == "Be concise"
        assert orchestrator.spawn.call_args[0][1] == "Do something"

    async def test_default_system_prompt(
        self, orchestrator: AsyncMock, config: SubagentToolConfig, parent_tools: list[ToolSpec]
    ) -> None:
        executor = create_subagent_executor(orchestrator, config, parent_tools)
        await executor({"task": "Hello"})

        spec_arg = orchestrator.spawn.call_args[0][0]
        assert spec_arg.system_prompt == "You are a helpful assistant"


# ---------------------------------------------------------------------------
# 4. Tool inheritance / filtering
# ---------------------------------------------------------------------------


class TestToolInheritance:
    """LLM requests specific tools — executor filters parent_tools."""

    async def test_all_tools_when_not_specified(
        self, orchestrator: AsyncMock, config: SubagentToolConfig, parent_tools: list[ToolSpec]
    ) -> None:
        executor = create_subagent_executor(orchestrator, config, parent_tools)
        await executor({"task": "work"})

        spec_arg = orchestrator.spawn.call_args[0][0]
        tool_names = [t.name for t in spec_arg.tools]
        assert tool_names == ["read_file", "write_file", "search"]

    async def test_filtered_tools_when_specified(
        self, orchestrator: AsyncMock, config: SubagentToolConfig, parent_tools: list[ToolSpec]
    ) -> None:
        executor = create_subagent_executor(orchestrator, config, parent_tools)
        await executor({"task": "work", "tools": ["read_file", "search"]})

        spec_arg = orchestrator.spawn.call_args[0][0]
        tool_names = [t.name for t in spec_arg.tools]
        assert tool_names == ["read_file", "search"]

    async def test_unknown_tool_names_ignored(
        self, orchestrator: AsyncMock, config: SubagentToolConfig, parent_tools: list[ToolSpec]
    ) -> None:
        executor = create_subagent_executor(orchestrator, config, parent_tools)
        await executor({"task": "work", "tools": ["read_file", "nonexistent"]})

        spec_arg = orchestrator.spawn.call_args[0][0]
        tool_names = [t.name for t in spec_arg.tools]
        assert tool_names == ["read_file"]


# ---------------------------------------------------------------------------
# 5. Max depth guard
# ---------------------------------------------------------------------------


class TestMaxDepthGuard:
    """Prevent infinite recursion via max_depth."""

    async def test_depth_exceeded_returns_error_json(
        self, orchestrator: AsyncMock, parent_tools: list[ToolSpec]
    ) -> None:
        cfg = SubagentToolConfig(max_depth=3)
        executor = create_subagent_executor(orchestrator, cfg, parent_tools, current_depth=3)
        raw = await executor({"task": "recurse"})

        result = json.loads(raw)
        assert result["status"] == "error"
        assert "depth" in result["error"].lower()
        orchestrator.spawn.assert_not_awaited()

    async def test_depth_within_limit_succeeds(
        self, orchestrator: AsyncMock, config: SubagentToolConfig, parent_tools: list[ToolSpec]
    ) -> None:
        executor = create_subagent_executor(orchestrator, config, parent_tools, current_depth=2)
        raw = await executor({"task": "work"})

        result = json.loads(raw)
        assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# 6. Timeout handling
# ---------------------------------------------------------------------------


class TestTimeout:
    """Timeout triggers cancel + error JSON."""

    async def test_timeout_cancels_and_returns_error(
        self, orchestrator: AsyncMock, parent_tools: list[ToolSpec]
    ) -> None:
        cfg = SubagentToolConfig(timeout_seconds=0.01)

        async def _slow_wait(_agent_id: str) -> SubagentResult:
            await asyncio.sleep(10)
            return orchestrator.wait.return_value  # never reached

        orchestrator.wait = AsyncMock(side_effect=_slow_wait)
        executor = create_subagent_executor(orchestrator, cfg, parent_tools)
        raw = await executor({"task": "slow task"})

        result = json.loads(raw)
        assert result["status"] == "error"
        assert "timeout" in result["error"].lower()
        orchestrator.cancel.assert_awaited_once_with("agent-001")


# ---------------------------------------------------------------------------
# 7. Max concurrent (ValueError from orchestrator)
# ---------------------------------------------------------------------------


class TestMaxConcurrent:
    """Orchestrator raises ValueError when at capacity."""

    async def test_max_concurrent_returns_error_json(
        self, orchestrator: AsyncMock, config: SubagentToolConfig, parent_tools: list[ToolSpec]
    ) -> None:
        orchestrator.spawn.side_effect = ValueError("max_concurrent reached")
        executor = create_subagent_executor(orchestrator, config, parent_tools)
        raw = await executor({"task": "one more"})

        result = json.loads(raw)
        assert result["status"] == "error"
        assert "max_concurrent" in result["error"].lower()


# ---------------------------------------------------------------------------
# 8. Missing task argument
# ---------------------------------------------------------------------------


class TestMissingTask:
    """task is required — missing returns error JSON."""

    async def test_missing_task_returns_error_json(
        self, orchestrator: AsyncMock, config: SubagentToolConfig, parent_tools: list[ToolSpec]
    ) -> None:
        executor = create_subagent_executor(orchestrator, config, parent_tools)
        raw = await executor({"system_prompt": "hello"})

        result = json.loads(raw)
        assert result["status"] == "error"
        assert "task" in result["error"].lower()
        orchestrator.spawn.assert_not_awaited()

    async def test_empty_task_returns_error_json(
        self, orchestrator: AsyncMock, config: SubagentToolConfig, parent_tools: list[ToolSpec]
    ) -> None:
        executor = create_subagent_executor(orchestrator, config, parent_tools)
        raw = await executor({"task": ""})

        result = json.loads(raw)
        assert result["status"] == "error"
        assert "task" in result["error"].lower()


# ---------------------------------------------------------------------------
# 9. Generic exception handling — never raise
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """All exceptions → JSON, never crash parent."""

    async def test_unexpected_exception_returns_error_json(
        self, orchestrator: AsyncMock, config: SubagentToolConfig, parent_tools: list[ToolSpec]
    ) -> None:
        orchestrator.spawn.side_effect = RuntimeError("internal boom")
        executor = create_subagent_executor(orchestrator, config, parent_tools)
        raw = await executor({"task": "work"})

        result = json.loads(raw)
        assert result["status"] == "error"
        assert "internal boom" in result["error"]

    async def test_wait_exception_returns_error_json(
        self, orchestrator: AsyncMock, config: SubagentToolConfig, parent_tools: list[ToolSpec]
    ) -> None:
        orchestrator.wait.side_effect = RuntimeError("wait failed")
        executor = create_subagent_executor(orchestrator, config, parent_tools)
        raw = await executor({"task": "work"})

        result = json.loads(raw)
        assert result["status"] == "error"
        assert "wait failed" in result["error"]


# ---------------------------------------------------------------------------
# 10. Failed subagent status
# ---------------------------------------------------------------------------


class TestFailedSubagent:
    """Subagent completes with failed status."""

    async def test_failed_subagent_returns_failed_json(
        self, orchestrator: AsyncMock, config: SubagentToolConfig, parent_tools: list[ToolSpec]
    ) -> None:
        orchestrator.wait.return_value = SubagentResult(
            agent_id="agent-001",
            status=SubagentStatus(state="failed", error="LLM returned garbage"),
            output="",
        )
        executor = create_subagent_executor(orchestrator, config, parent_tools)
        raw = await executor({"task": "broken task"})

        result = json.loads(raw)
        assert result["agent_id"] == "agent-001"
        assert result["status"] == "failed"
        assert "LLM returned garbage" in result["error"]
