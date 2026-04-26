"""Integration tests for subagent wiring from AgentConfig → ThinRuntime."""

from __future__ import annotations


from swarmline.agent.config import AgentConfig
from swarmline.agent.runtime_wiring import build_portable_runtime_plan
from swarmline.runtime.thin.subagent_tool import SubagentToolConfig


class TestAgentConfigSubagentPropagation:
    """AgentConfig.subagent_config reaches ThinRuntime through wiring."""

    def test_agent_config_accepts_subagent_config(self) -> None:
        """AgentConfig stores subagent_config field."""
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            cwd="/tmp/swarmline",
            subagent_config=SubagentToolConfig(max_depth=2),
        )
        assert cfg.subagent_config is not None
        assert cfg.subagent_config.max_depth == 2

    def test_agent_config_default_subagent_config_is_none(self) -> None:
        """Default: subagent_config is None."""
        cfg = AgentConfig(system_prompt="test", runtime="thin")
        assert cfg.subagent_config is None

    def test_config_propagates_to_create_kwargs(self) -> None:
        """build_portable_runtime_plan passes subagent_config into create_kwargs."""
        sub_cfg = SubagentToolConfig(max_concurrent=2)
        agent_cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            cwd="/tmp/swarmline",
            subagent_config=sub_cfg,
        )
        plan = build_portable_runtime_plan(agent_cfg, "thin")
        runtime_sub_cfg = plan.create_kwargs.get("subagent_config")
        assert runtime_sub_cfg is not None
        assert runtime_sub_cfg.max_concurrent == 2
        assert runtime_sub_cfg.base_path == "/tmp/swarmline"

    def test_no_subagent_config_not_in_create_kwargs(self) -> None:
        """Without subagent_config, create_kwargs has no key."""
        agent_cfg = AgentConfig(system_prompt="test", runtime="thin")
        plan = build_portable_runtime_plan(agent_cfg, "thin")
        assert "subagent_config" not in plan.create_kwargs
