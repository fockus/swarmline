"""Shared wiring helpers for portable runtime entrypoints."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from swarmline.agent.config import AgentConfig
from swarmline.agent.runtime_dispatch import merge_hooks
from swarmline.agent.runtime_factory_port import (
    RuntimeFactoryPort,
    build_runtime_factory,
)
from swarmline.runtime.types import RuntimeConfig, ToolSpec

_PORTABLE_MCP_RUNTIMES = frozenset({"thin", "deepagents"})
_FAIL_FAST_MCP_RUNTIMES = frozenset({"openai_agents", "pi_sdk"})


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
        max_model_retries=(
            agent_config.max_model_retries
            if agent_config.max_model_retries is not None
            else RuntimeConfig().max_model_retries
        ),
        model=factory.resolve_agent_model(agent_config),
        base_url=agent_config.base_url,
        output_format=agent_config.output_format,
        output_type=agent_config.output_type,
        structured_mode=agent_config.structured_mode,
        structured_schema_name=agent_config.structured_schema_name,
        structured_strict=agent_config.structured_strict,
        request_options=agent_config.request_options,
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
    elif runtime_name in _FAIL_FAST_MCP_RUNTIMES and agent_config.mcp_servers:
        create_kwargs["mcp_servers"] = agent_config.mcp_servers

    if agent_config.runtime_options is not None:
        _apply_runtime_options(
            runtime_name, agent_config.runtime_options, create_kwargs
        )

    # Merge hooks from config + middleware for portable runtimes
    merged_hooks = merge_hooks(agent_config.hooks, agent_config.middleware)
    if merged_hooks is not None:
        create_kwargs["hook_registry"] = merged_hooks

    # Tool policy enforcement
    if agent_config.tool_policy is not None:
        create_kwargs["tool_policy"] = agent_config.tool_policy

    # Subagent configuration
    if runtime_name == "thin" and agent_config.subagent_config is not None:
        subagent_config = agent_config.subagent_config
        if subagent_config.base_path is None:
            if agent_config.cwd is None:
                raise ValueError(
                    "AgentConfig.cwd is required when subagent_config is enabled. "
                    "Set cwd to a git repository path so worktree isolation can be initialized."
                )
            subagent_config = replace(subagent_config, base_path=agent_config.cwd)
        create_kwargs["subagent_config"] = subagent_config

    # Command registry
    if agent_config.command_registry is not None:
        create_kwargs["command_registry"] = agent_config.command_registry

    active_tools = [
        tool_definition.to_tool_spec() for tool_definition in agent_config.tools
    ]

    # Coding profile: inject coding tool pack + policy scope (after active_tools built)
    if (
        runtime_name == "thin"
        and agent_config.coding_profile is not None
        and agent_config.coding_profile.enabled
    ):
        from swarmline.context.coding_input_filter import CodingContextInputFilter
        from swarmline.policy.tool_policy import DefaultToolPolicy
        from swarmline.runtime.thin.coding_toolpack import (
            CODING_TOOL_NAMES,
            build_coding_toolpack,
        )
        from swarmline.tools.sandbox_local import LocalSandboxProvider
        from swarmline.tools.types import SandboxConfig

        create_kwargs["coding_profile"] = agent_config.coding_profile

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
            coding_allowed = coding_allowed | set(
                agent_config.tool_policy.allowed_system_tools
            )
        create_kwargs["tool_policy"] = DefaultToolPolicy(
            allowed_system_tools=coding_allowed,
        )

        board_context = agent_config.native_config.get("coding_board_context")
        search_context = agent_config.native_config.get("coding_search_context")
        skill_profile_text = agent_config.native_config.get("coding_skill_profile")
        session_store = agent_config.native_config.get("task_session_store")
        session_agent_id = agent_config.native_config.get(
            "task_session_agent_id", "coding"
        )
        budget_tokens_raw = agent_config.native_config.get(
            "coding_context_budget_tokens", 2000
        )
        if skill_profile_text is None:
            skill_profile_text = (
                "Coding profile enabled. "
                f"allow_host_execution={agent_config.coding_profile.allow_host_execution}"
            )
        runtime_config = replace(
            runtime_config,
            input_filters=[
                *runtime_config.input_filters,
                CodingContextInputFilter(
                    workspace_cwd=cwd,
                    board_text=board_context if isinstance(board_context, str) else "",
                    search_text=search_context if isinstance(search_context, str) else "",
                    skill_profile_text=str(skill_profile_text),
                    task_session_store=session_store,
                    task_session_agent_id=(
                        str(session_agent_id)
                        if isinstance(session_agent_id, str)
                        else "coding"
                    ),
                    task_session_task_id=session_id,
                    budget_tokens=(
                        int(budget_tokens_raw)
                        if isinstance(budget_tokens_raw, (int, float))
                        else 2000
                    ),
                ),
            ],
        )

        # LLM-initiated child agents need the same sandbox template so the
        # worker runtime can rebind coding tools to a per-worktree sandbox.
        runtime_subagent_cfg = create_kwargs.get("subagent_config")
        if (
            runtime_subagent_cfg is not None
            and getattr(runtime_subagent_cfg, "sandbox_config", None) is None
        ):
            create_kwargs["subagent_config"] = replace(
                runtime_subagent_cfg,
                sandbox_config=sandbox_config,
            )

    return PortableRuntimePlan(
        config=runtime_config,
        create_kwargs=create_kwargs,
        active_tools=active_tools,
    )


def _apply_runtime_options(
    runtime_name: str,
    runtime_options: Any,
    create_kwargs: dict[str, Any],
) -> None:
    """Map typed runtime options into factory kwargs."""
    if runtime_name == "pi_sdk":
        from swarmline.runtime.pi_sdk.types import PiSdkOptions

        if not isinstance(runtime_options, PiSdkOptions):
            raise ValueError(
                "runtime='pi_sdk' expects runtime_options=PiSdkOptions(...)"
            )
        create_kwargs["pi_options"] = runtime_options
        return

    if runtime_name == "cli":
        from swarmline.runtime.cli.types import CliConfig

        if not isinstance(runtime_options, CliConfig):
            raise ValueError("runtime='cli' expects runtime_options=CliConfig(...)")
        create_kwargs["cli_config"] = runtime_options
        return

    if runtime_name == "openai_agents":
        from swarmline.runtime.openai_agents.types import OpenAIAgentsConfig

        if not isinstance(runtime_options, OpenAIAgentsConfig):
            raise ValueError(
                "runtime='openai_agents' expects runtime_options=OpenAIAgentsConfig(...)"
            )
        create_kwargs["agents_config"] = runtime_options
        return

    raise ValueError(f"runtime_options are not supported for runtime='{runtime_name}'")
