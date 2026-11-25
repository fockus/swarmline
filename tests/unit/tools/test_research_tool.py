"""Tests for spawn_research tool — TDD Red phase."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from swarmline.orchestration.context_bridge import ContextBridge
from swarmline.orchestration.subagent_types import (
    SubagentResult,
    SubagentSpec,
    SubagentStatus,
)
from swarmline.tools.research import make_spawn_research_tool


def _make_mock_orchestrator(output: str = "Research findings here") -> AsyncMock:
    """Create a mock SubagentOrchestrator that returns given output."""
    orch = AsyncMock()
    orch.spawn.return_value = "agent-123"
    orch.wait.return_value = SubagentResult(
        agent_id="agent-123",
        status=SubagentStatus(state="completed", result=output),
        output=output,
    )
    return orch


@pytest.mark.asyncio
async def test_spawn_research_creates_subagent() -> None:
    """spawn_research calls orchestrator.spawn with research system prompt."""
    orch = _make_mock_orchestrator()
    spec, executor = make_spawn_research_tool(orch)

    result_json = await executor({"query": "test topic"})
    result = json.loads(result_json)

    orch.spawn.assert_called_once()
    spawned_spec: SubagentSpec = orch.spawn.call_args[0][0]
    assert "test topic" in spawned_spec.system_prompt
    assert spawned_spec.name == "research"
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_spawn_research_with_context_bridge() -> None:
    """spawn_research injects context bridge into SubagentSpec when provided."""
    bridge = ContextBridge(
        parent_goal="Build a feature",
        parent_progress="50% done",
        parent_findings=["finding-1"],
        inherited_tools=["bash"],
    )
    orch = _make_mock_orchestrator()
    spec, executor = make_spawn_research_tool(orch, context_bridge=bridge)

    await executor({"query": "how to optimize"})

    spawned_spec: SubagentSpec = orch.spawn.call_args[0][0]
    assert spawned_spec.context_bridge is bridge


@pytest.mark.asyncio
async def test_spawn_research_without_context_bridge() -> None:
    """spawn_research works without context bridge (backward compat)."""
    orch = _make_mock_orchestrator()
    spec, executor = make_spawn_research_tool(orch)

    await executor({"query": "test"})

    spawned_spec: SubagentSpec = orch.spawn.call_args[0][0]
    assert spawned_spec.context_bridge is None


@pytest.mark.asyncio
async def test_spawn_research_returns_output() -> None:
    """spawn_research returns sub-agent output text."""
    orch = _make_mock_orchestrator(output="The answer is 42")
    _, executor = make_spawn_research_tool(orch)

    result_json = await executor({"query": "what is the answer?"})
    result = json.loads(result_json)

    assert result["status"] == "ok"
    assert result["output"] == "The answer is 42"


@pytest.mark.asyncio
async def test_spawn_research_passes_task_from_query() -> None:
    """spawn_research passes query as the task to orchestrator.spawn."""
    orch = _make_mock_orchestrator()
    _, executor = make_spawn_research_tool(orch)

    await executor({"query": "specific research question"})

    task_arg = orch.spawn.call_args[0][1]
    assert task_arg == "specific research question"


@pytest.mark.asyncio
async def test_spawn_research_uses_context_in_prompt() -> None:
    """spawn_research includes context parameter in system prompt."""
    orch = _make_mock_orchestrator()
    _, executor = make_spawn_research_tool(orch)

    await executor({"query": "topic", "context": "extra context info"})

    spawned_spec: SubagentSpec = orch.spawn.call_args[0][0]
    assert "extra context info" in spawned_spec.system_prompt


@pytest.mark.asyncio
async def test_spawn_research_respects_max_turns() -> None:
    """spawn_research sets max_turns on context bridge when provided."""
    bridge = ContextBridge(
        parent_goal="goal",
        parent_progress="progress",
        max_turns=3,
    )
    orch = _make_mock_orchestrator()
    _, executor = make_spawn_research_tool(orch, context_bridge=bridge)

    await executor({"query": "topic"})

    spawned_spec: SubagentSpec = orch.spawn.call_args[0][0]
    assert spawned_spec.context_bridge is not None
    assert spawned_spec.context_bridge.max_turns == 3


@pytest.mark.asyncio
async def test_spawn_research_missing_query_returns_error() -> None:
    """spawn_research returns error when query is missing."""
    orch = _make_mock_orchestrator()
    _, executor = make_spawn_research_tool(orch)

    result_json = await executor({})
    result = json.loads(result_json)

    assert result["status"] == "error"
    orch.spawn.assert_not_called()


@pytest.mark.asyncio
async def test_make_tool_returns_toolspec() -> None:
    """make_spawn_research_tool returns a valid ToolSpec."""
    orch = _make_mock_orchestrator()
    spec, executor = make_spawn_research_tool(orch)

    assert spec.name == "spawn_research"
    assert "research" in spec.description.lower()
    assert "query" in spec.parameters.get("properties", {})
    assert callable(executor)


@pytest.mark.asyncio
async def test_spawn_research_handles_orchestrator_error() -> None:
    """spawn_research returns error when orchestrator fails."""
    orch = AsyncMock()
    orch.spawn.side_effect = RuntimeError("LLM unavailable")
    _, executor = make_spawn_research_tool(orch)

    result_json = await executor({"query": "test"})
    result = json.loads(result_json)

    assert result["status"] == "error"
    assert "LLM unavailable" in result["message"]


@pytest.mark.asyncio
async def test_spawn_research_with_context_bridge_includes_parent_goal() -> None:
    """Context bridge parent_goal is preserved in SubagentSpec passed to orchestrator."""
    bridge = ContextBridge(
        parent_goal="Analyze user churn patterns",
        parent_progress="Collected raw data",
        parent_findings=["churn is 5%"],
        inherited_tools=["web_search"],
        max_turns=7,
    )
    orch = _make_mock_orchestrator()
    _, executor = make_spawn_research_tool(orch, context_bridge=bridge)

    await executor({"query": "churn reasons"})

    spawned_spec: SubagentSpec = orch.spawn.call_args[0][0]
    assert spawned_spec.context_bridge is not None
    assert spawned_spec.context_bridge.parent_goal == "Analyze user churn patterns"
    assert spawned_spec.context_bridge.parent_findings == ["churn is 5%"]
    assert spawned_spec.context_bridge.inherited_tools == ["web_search"]


@pytest.mark.asyncio
async def test_spawn_research_empty_query_returns_error() -> None:
    """spawn_research returns error for whitespace-only query."""
    orch = _make_mock_orchestrator()
    _, executor = make_spawn_research_tool(orch)

    result_json = await executor({"query": "   "})
    result = json.loads(result_json)

    assert result["status"] == "error"
    orch.spawn.assert_not_called()


def test_toolspec_has_correct_name_and_description() -> None:
    """ToolSpec from make_spawn_research_tool has spawn_research name and informative description."""
    orch = _make_mock_orchestrator()
    spec, _ = make_spawn_research_tool(orch)

    assert spec.name == "spawn_research"
    assert (
        "sub-agent" in spec.description.lower()
        or "research" in spec.description.lower()
    )
    assert len(spec.description) > 10
    assert "query" in spec.parameters["properties"]
    assert spec.parameters["required"] == ["query"]
