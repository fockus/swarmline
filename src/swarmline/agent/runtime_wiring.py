"""Shared wiring helpers for portable runtime entrypoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from swarmline.agent.config import AgentConfig
from swarmline.agent.runtime_dispatch import merge_hooks
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

    # Merge hooks from config + middleware for portable runtimes
    merged_hooks = merge_hooks(agent_config.hooks, agent_config.middleware)
    if merged_hooks is not None:
        create_kwargs["hook_registry"] = merged_hooks

    # Tool policy enforcement
    if agent_config.tool_policy is not None:
        create_kwargs["tool_policy"] = agent_config.tool_policy

    # Subagent configuration
    if agent_config.subagent_config is not None:
        create_kwargs["subagent_config"] = agent_config.subagent_config

    # Command registry
    if agent_config.command_registry is not None:
        create_kwargs["command_registry"] = agent_config.command_registry

    active_tools = [tool_definition.to_tool_spec() for tool_definition in agent_config.tools]

    # Coding profile: inject coding tool pack + policy scope (after active_tools built)
    if (
        agent_config.coding_profile is not None
        and agent_config.coding_profile.enabled
    ):
        from swarmline.policy.tool_policy import DefaultToolPolicy
        from swarmline.runtime.thin.coding_toolpack import CODING_TOOL_NAMES, build_coding_toolpack
        from swarmline.tools.sandbox_local import LocalSandboxProvider
        from swarmline.tools.types import SandboxConfig

        # Build coding tool pack from a default sandbox
        cwd = agent_config.cwd
        if cwd is None:
            raise ValueError(
                "AgentConfig.cwd is required when coding_profile is enabled. "
                "Set cwd to the working directory for the coding agent."
            )
        sandbox_config = SandboxConfig(
            root_path=cwd,
            user_id="coding",
            topic_id="agent",
            allow_host_execution=agent_config.coding_profile.allow_host_execution,
        )
        sandbox = LocalSandboxProvider(sandbox_config)
        coding_pack = build_coding_toolpack(sandbox)

        # Add coding tool specs to active tools
        for spec in coding_pack.specs.values():
            active_tools.append(spec)

        # Add coding tool executors to create_kwargs
        existing_executors = create_kwargs.get("tool_executors", {})
        existing_executors.update(coding_pack.executors)
        create_kwargs["tool_executors"] = existing_executors

        # Build/merge policy: coding tools allowed + any existing policy
        coding_allowed = set(CODING_TOOL_NAMES)
        if isinstance(agent_config.tool_policy, DefaultToolPolicy):
            coding_allowed = coding_allowed | set(agent_config.tool_policy.allowed_system_tools)
        create_kwargs["tool_policy"] = DefaultToolPolicy(
            allowed_system_tools=coding_allowed,
        )

    return PortableRuntimePlan(
        config=runtime_config,
        create_kwargs=create_kwargs,
        active_tools=active_tools,
    )
