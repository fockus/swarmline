"""Tests for spawn_agent tool isolation parameter (Phase 17, Task #2).

Verifies:
1. SUBAGENT_TOOL_SPEC schema includes 'isolation' parameter with correct shape
2. Executor extracts isolation from args and passes to SubagentSpec constructor
3. When isolation is omitted, it is NOT passed to SubagentSpec constructor
4. Isolation combines correctly with other parameters
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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
        output="Task completed",
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
    ]


# ---------------------------------------------------------------------------
# 1. SUBAGENT_TOOL_SPEC — isolation parameter schema
# ---------------------------------------------------------------------------


class TestSubagentToolSpecIsolation:
    """SUBAGENT_TOOL_SPEC schema includes 'isolation' with correct shape."""

    def test_spec_has_isolation_property(self) -> None:
        props = SUBAGENT_TOOL_SPEC.parameters["properties"]
        assert "isolation" in props

    def test_isolation_type_is_string(self) -> None:
        isolation_prop = SUBAGENT_TOOL_SPEC.parameters["properties"]["isolation"]
        assert isolation_prop["type"] == "string"

    def test_isolation_enum_contains_only_worktree(self) -> None:
        isolation_prop = SUBAGENT_TOOL_SPEC.parameters["properties"]["isolation"]
        assert isolation_prop["enum"] == ["worktree"]

    def test_isolation_not_in_required(self) -> None:
        required = SUBAGENT_TOOL_SPEC.parameters.get("required", [])
        assert "isolation" not in required

    def test_isolation_has_meaningful_description(self) -> None:
        isolation_prop = SUBAGENT_TOOL_SPEC.parameters["properties"]["isolation"]
        assert "description" in isolation_prop
        assert len(isolation_prop["description"]) > 10
        assert "worktree" in isolation_prop["description"].lower()


# ---------------------------------------------------------------------------
# 2. Executor — isolation passthrough via patched SubagentSpec
#    Patching SubagentSpec at the import site so tests pass regardless of
#    whether dev-domain (Task #1) has added the `isolation` field yet.
# ---------------------------------------------------------------------------


class TestExecutorIsolationPassthrough:
    """Executor extracts isolation from args and passes to SubagentSpec constructor."""

    @patch("swarmline.runtime.thin.subagent_tool.SubagentSpec")
    async def test_isolation_worktree_passed_to_spec_constructor(
        self,
        mock_spec_cls: MagicMock,
        orchestrator: AsyncMock,
        config: SubagentToolConfig,
        parent_tools: list[ToolSpec],
    ) -> None:
        mock_spec_cls.return_value = MagicMock()
        executor = create_subagent_executor(orchestrator, config, parent_tools)
        raw = await executor({"task": "isolated work", "isolation": "worktree"})

        result = json.loads(raw)
        assert result["status"] == "completed"

        call_kwargs = mock_spec_cls.call_args
        assert call_kwargs.kwargs["isolation"] == "worktree"

    @patch("swarmline.runtime.thin.subagent_tool.SubagentSpec")
    async def test_isolation_not_passed_when_omitted(
        self,
        mock_spec_cls: MagicMock,
        orchestrator: AsyncMock,
        config: SubagentToolConfig,
        parent_tools: list[ToolSpec],
    ) -> None:
        mock_spec_cls.return_value = MagicMock()
        executor = create_subagent_executor(orchestrator, config, parent_tools)
        await executor({"task": "normal work"})

        call_kwargs = mock_spec_cls.call_args
        assert "isolation" not in call_kwargs.kwargs

    @patch("swarmline.runtime.thin.subagent_tool.SubagentSpec")
    async def test_isolation_combined_with_tools_and_system_prompt(
        self,
        mock_spec_cls: MagicMock,
        orchestrator: AsyncMock,
        config: SubagentToolConfig,
        parent_tools: list[ToolSpec],
    ) -> None:
        mock_spec_cls.return_value = MagicMock()
        executor = create_subagent_executor(orchestrator, config, parent_tools)
        await executor({
            "task": "complex work",
            "system_prompt": "Be careful",
            "tools": ["read_file"],
            "isolation": "worktree",
        })

        call_kwargs: dict[str, Any] = mock_spec_cls.call_args.kwargs
        assert call_kwargs["isolation"] == "worktree"
        assert call_kwargs["system_prompt"] == "Be careful"
        assert len(call_kwargs["tools"]) == 1
        assert call_kwargs["tools"][0].name == "read_file"
