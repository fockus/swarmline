"""Shared wiring helpers for portable runtime entrypoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from swarmline.agent.config import AgentConfig
from swarmline.agent.runtime_factory_port import RuntimeFactoryPort, build_runtime_factory
from swarmline.runtime.types import RuntimeConfig, ToolSpec

_PORTABLE_MCP_RUNTIMES = frozenset({"thin", "deepagents"})


@dataclass(frozen=True)
class PortableRuntimePlan:
    """Portable runtime request assembled from AgentConfig."""

    config: RuntimeConfig
    create_kwargs: dict[str, Any]
    active_tools: list[ToolSpec]


def build_portable_runtime_plan(
    agent_config: AgentConfig,
    runtime_name: str,
    *,
    session_id: str | None = None,
    runtime_factory: RuntimeFactoryPort | None = None,
) -> PortableRuntimePlan:
    """Build RuntimeConfig/create kwargs for portable entrypoints."""
    factory = runtime_factory or build_runtime_factory()
    factory.validate_agent_config(agent_config)

    runtime_config = RuntimeConfig(
        runtime_name=runtime_name,
        model=factory.resolve_agent_model(agent_config),
        output_format=agent_config.output_format,
        output_type=agent_config.output_type,
        feature_mode=agent_config.feature_mode,
        required_capabilities=agent_config.require_capabilities,
        allow_native_features=agent_config.allow_native_features,
        native_config=dict(agent_config.native_config),
    )
    if runtime_name == "deepagents" and session_id is not None:
        runtime_config.native_config = {
            **runtime_config.native_config,
            "thread_id": session_id,
        }

    create_kwargs: dict[str, Any] = {
        "tool_executors": {
            tool_definition.name: tool_definition.handler
            for tool_definition in agent_config.tools
        }
    }
    if runtime_name in _PORTABLE_MCP_RUNTIMES and agent_config.mcp_servers:
        create_kwargs["mcp_servers"] = agent_config.mcp_servers

    active_tools = [tool_definition.to_tool_spec() for tool_definition in agent_config.tools]
    return PortableRuntimePlan(
        config=runtime_config,
        create_kwargs=create_kwargs,
        active_tools=active_tools,
    )
