"""Tests for AgentToolResult domain type."""

from __future__ import annotations

import dataclasses

import pytest


class TestAgentToolResult:
    """AgentToolResult frozen dataclass tests."""

    def test_agent_tool_result_is_frozen_cannot_mutate(self) -> None:
        from swarmline.multi_agent.types import AgentToolResult

        result = AgentToolResult(success=True, output="hello")
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.success = False  # type: ignore[misc]

    def test_agent_tool_result_default_values(self) -> None:
        from swarmline.multi_agent.types import AgentToolResult

        result = AgentToolResult(success=True, output="ok")
        assert result.error is None
        assert result.agent_id == ""
        assert result.tokens_used == 0
        assert result.cost_usd == 0.0

    def test_agent_tool_result_all_fields(self) -> None:
        from swarmline.multi_agent.types import AgentToolResult

        result = AgentToolResult(
            success=False,
            output="",
            error="timeout",
            agent_id="agent-1",
            tokens_used=150,
            cost_usd=0.003,
        )
        assert result.success is False
        assert result.output == ""
        assert result.error == "timeout"
        assert result.agent_id == "agent-1"
        assert result.tokens_used == 150
        assert result.cost_usd == pytest.approx(0.003)

    def test_agent_tool_result_is_dataclass(self) -> None:
        from swarmline.multi_agent.types import AgentToolResult

        assert dataclasses.is_dataclass(AgentToolResult)

    def test_agent_tool_result_importable_from_multi_agent(self) -> None:
        from swarmline.multi_agent import AgentToolResult

        assert AgentToolResult is not None
