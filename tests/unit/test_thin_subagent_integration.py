"""Unit tests for subagent tool wiring into ThinRuntime."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from swarmline.runtime.thin.subagent_tool import SubagentToolConfig
from swarmline.runtime.types import RuntimeConfig


@pytest.fixture
def thin_config() -> RuntimeConfig:
    return RuntimeConfig(runtime_name="thin")


class TestThinRuntimeSubagentWiring:
    """ThinRuntime __init__ registers spawn_agent when subagent_config is provided."""

    def test_without_subagent_config_no_spawn_tool(self, thin_config: RuntimeConfig) -> None:
        """No subagent_config → spawn_agent not in executor local tools."""
        from swarmline.runtime.thin.runtime import ThinRuntime

        async def _noop_llm(**kw: object) -> dict:
            return {"content": "ok", "tool_calls": []}

        rt = ThinRuntime(config=thin_config, llm_call=_noop_llm)
        assert "spawn_agent" not in rt._executor._local_tools

    def test_with_subagent_config_has_spawn_tool(self, thin_config: RuntimeConfig) -> None:
        """subagent_config provided → spawn_agent registered in executor local tools."""
        from swarmline.runtime.thin.runtime import ThinRuntime

        async def _noop_llm(**kw: object) -> dict:
            return {"content": "ok", "tool_calls": []}

        cfg = SubagentToolConfig(max_concurrent=2, max_depth=2)
        rt = ThinRuntime(config=thin_config, llm_call=_noop_llm, subagent_config=cfg)
        assert "spawn_agent" in rt._executor._local_tools
        assert callable(rt._executor._local_tools["spawn_agent"])

    def test_subagent_tool_spec_in_builtin_specs(self, thin_config: RuntimeConfig) -> None:
        """subagent_config provided → SUBAGENT_TOOL_SPEC stored for run() to append."""
        from swarmline.runtime.thin.runtime import ThinRuntime

        async def _noop_llm(**kw: object) -> dict:
            return {"content": "ok", "tool_calls": []}

        cfg = SubagentToolConfig()
        rt = ThinRuntime(config=thin_config, llm_call=_noop_llm, subagent_config=cfg)
        assert rt._subagent_tool_spec is not None
        assert rt._subagent_tool_spec.name == "spawn_agent"

    def test_no_subagent_config_no_spec_stored(self, thin_config: RuntimeConfig) -> None:
        """No subagent_config → _subagent_tool_spec is None."""
        from swarmline.runtime.thin.runtime import ThinRuntime

        async def _noop_llm(**kw: object) -> dict:
            return {"content": "ok", "tool_calls": []}

        rt = ThinRuntime(config=thin_config, llm_call=_noop_llm)
        assert rt._subagent_tool_spec is None
