"""Tests for tool_policy wiring: AgentConfig → runtime_wiring → create_kwargs.

Uses REAL DefaultToolPolicy — no mocks.
TDD RED phase: these tests define the contract for policy propagation.
"""

from __future__ import annotations

from swarmline.agent.config import AgentConfig
from swarmline.agent.runtime_wiring import build_portable_runtime_plan
from swarmline.policy.tool_policy import DefaultToolPolicy


class TestPolicyWiring:
    """Policy propagation from AgentConfig to create_kwargs."""

    def test_agent_with_policy_creates_kwargs(self) -> None:
        """tool_policy in AgentConfig → appears in create_kwargs."""
        policy = DefaultToolPolicy()
        config = AgentConfig(
            system_prompt="test",
            runtime="thin",
            tool_policy=policy,
        )
        plan = build_portable_runtime_plan(config, "thin")
        assert plan.create_kwargs.get("tool_policy") is policy

    def test_agent_without_policy_no_policy_in_kwargs(self) -> None:
        """No tool_policy in AgentConfig → no 'tool_policy' key in create_kwargs."""
        config = AgentConfig(
            system_prompt="test",
            runtime="thin",
        )
        plan = build_portable_runtime_plan(config, "thin")
        assert "tool_policy" not in plan.create_kwargs
