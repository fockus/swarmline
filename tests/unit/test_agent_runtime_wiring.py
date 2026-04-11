"""Unit tests for shared portable runtime wiring helpers."""

from __future__ import annotations

from typing import Any

from swarmline.agent.config import AgentConfig
from swarmline.agent.tool import tool
from swarmline.skills.types import McpServerSpec


def _make_config(**overrides: Any) -> AgentConfig:
    defaults = {"system_prompt": "test prompt"}
    defaults.update(overrides)
    return AgentConfig(**defaults)


class TestBuildPortableRuntimePlan:
    def test_maps_tool_executors_and_active_tools(self) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        @tool(name="calc", description="Calculator")
        async def calc(expr: str) -> str:
            return "42"

        config = _make_config(runtime="thin", tools=(calc.__tool_definition__,))

        plan = build_portable_runtime_plan(config, "thin")

        assert plan.config.runtime_name == "thin"
        assert plan.create_kwargs["tool_executors"]["calc"] is calc.__tool_definition__.handler
        assert [spec.name for spec in plan.active_tools] == ["calc"]

    def test_includes_mcp_servers_only_for_portable_runtimes(self) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        mcp_servers = {"iss": McpServerSpec(name="iss", url="https://iss.test")}
        portable_config = _make_config(runtime="deepagents", mcp_servers=mcp_servers)
        cli_config = _make_config(runtime="cli", mcp_servers=mcp_servers)

        portable_plan = build_portable_runtime_plan(portable_config, "deepagents")
        cli_plan = build_portable_runtime_plan(cli_config, "cli")

        assert portable_plan.create_kwargs["mcp_servers"] == mcp_servers
        assert "mcp_servers" not in cli_plan.create_kwargs

    def test_injects_thread_id_for_deepagents_sessions(self) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        config = _make_config(runtime="deepagents", native_config={"checkpointer": object()})

        plan = build_portable_runtime_plan(
            config,
            "deepagents",
            session_id="conv-thread-1",
        )

        assert plan.config.native_config["checkpointer"] is config.native_config["checkpointer"]
        assert plan.config.native_config["thread_id"] == "conv-thread-1"

    def test_preserves_dict_style_mcp_servers_for_portable_runtime(self) -> None:
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        mcp_servers = {"iss": {"type": "http", "url": "https://iss.test"}}
        config = _make_config(runtime="thin", mcp_servers=mcp_servers)

        plan = build_portable_runtime_plan(config, "thin")

        assert plan.create_kwargs["mcp_servers"] == mcp_servers


class TestResolveMcpServerUrl:
    def test_resolves_plain_dict_server_config(self) -> None:
        from swarmline.runtime.thin.mcp_client import resolve_mcp_server_url

        url = resolve_mcp_server_url(
            {"iss": {"type": "http", "url": "https://iss.test"}},
            "iss",
        )

        assert url == "https://iss.test"
