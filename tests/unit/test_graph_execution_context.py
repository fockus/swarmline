"""Tests for AgentExecutionContext — structured execution data for graph runner."""

from __future__ import annotations

import pytest

from swarmline.multi_agent.graph_execution_context import AgentExecutionContext


class TestDefaultConstruction:
    def test_default_construction_minimal_fields(self) -> None:
        ctx = AgentExecutionContext(
            agent_id="a1",
            task_id="t1",
            goal="Do something",
            system_prompt="You are helpful",
        )
        assert ctx.agent_id == "a1"
        assert ctx.task_id == "t1"
        assert ctx.goal == "Do something"
        assert ctx.system_prompt == "You are helpful"
        assert ctx.tools == ()
        assert ctx.skills == ()
        assert ctx.mcp_servers == ()
        assert ctx.runtime_config is None
        assert ctx.budget_limit_usd is None
        assert ctx.metadata == {}


class TestFrozen:
    def test_frozen_cannot_mutate_agent_id(self) -> None:
        ctx = AgentExecutionContext(
            agent_id="a1",
            task_id="t1",
            goal="g",
            system_prompt="s",
        )
        with pytest.raises(AttributeError):
            ctx.agent_id = "a2"  # type: ignore[misc]

    def test_frozen_cannot_mutate_tools(self) -> None:
        ctx = AgentExecutionContext(
            agent_id="a1",
            task_id="t1",
            goal="g",
            system_prompt="s",
        )
        with pytest.raises(AttributeError):
            ctx.tools = ("new_tool",)  # type: ignore[misc]


class TestFullConstruction:
    def test_full_construction_all_fields(self) -> None:
        ctx = AgentExecutionContext(
            agent_id="agent-007",
            task_id="task-42",
            goal="Complete the mission",
            system_prompt="You are a secret agent",
            tools=("web_search", "code_sandbox"),
            skills=("research", "planning"),
            mcp_servers=("github", "filesystem"),
            runtime_config={"model": "sonnet", "temperature": 0.7},
            budget_limit_usd=25.0,
            metadata={"priority": "high", "retry_count": 0},
        )
        assert ctx.agent_id == "agent-007"
        assert ctx.task_id == "task-42"
        assert ctx.goal == "Complete the mission"
        assert ctx.system_prompt == "You are a secret agent"
        assert ctx.tools == ("web_search", "code_sandbox")
        assert ctx.skills == ("research", "planning")
        assert ctx.mcp_servers == ("github", "filesystem")
        assert ctx.runtime_config == {"model": "sonnet", "temperature": 0.7}
        assert ctx.budget_limit_usd == 25.0
        assert ctx.metadata == {"priority": "high", "retry_count": 0}


class TestBackwardCompatFields:
    def test_backward_compat_core_fields_accessible(self) -> None:
        """The four core fields (agent_id, task_id, goal, system_prompt)
        must be accessible as plain attributes — matching the old tuple contract."""
        ctx = AgentExecutionContext(
            agent_id="a1",
            task_id="t1",
            goal="Summarize document",
            system_prompt="You are a summarizer",
        )
        # These four fields replace the old (agent_id, task_id, goal, system_prompt) tuple
        assert hasattr(ctx, "agent_id")
        assert hasattr(ctx, "task_id")
        assert hasattr(ctx, "goal")
        assert hasattr(ctx, "system_prompt")
        # Values match
        assert ctx.agent_id == "a1"
        assert ctx.task_id == "t1"
        assert ctx.goal == "Summarize document"
        assert ctx.system_prompt == "You are a summarizer"
