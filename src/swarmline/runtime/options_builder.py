"""ClaudeOptionsBuilder - factory for ClaudeAgentOptions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from claude_agent_sdk import (
    AgentDefinition,
    ClaudeAgentOptions,
    HookMatcher,
    McpSdkServerConfig,
    PermissionResultAllow,
    PermissionResultDeny,
    PermissionMode,
    SandboxSettings,
    SdkBeta,
    SdkPluginConfig,
    SettingSource,
    ThinkingConfigAdaptive,
    ThinkingConfigDisabled,
    ThinkingConfigEnabled,
    ToolPermissionContext,
)

from swarmline.network_safety import validate_http_endpoint_url
from swarmline.skills.types import McpServerSpec

if TYPE_CHECKING:
    from swarmline.protocols import ModelSelector


# Type callback for can_use_tool
CanUseToolFn = Callable[
    [str, dict[str, Any], ToolPermissionContext],
    Awaitable[PermissionResultAllow | PermissionResultDeny],
]


class ClaudeOptionsBuilder:
    """Claude Options Builder implementation."""

    def __init__(
        self,
        model_policy: ModelSelector | None = None,
        cwd: str | Path | None = None,
        override_model: str | None = None,
    ) -> None:
        if model_policy is None:
            from swarmline.runtime.model_policy import ModelPolicy

            model_policy = ModelPolicy()
        self._model_policy = model_policy
        self._cwd = cwd
        self._override_model = override_model

    def build(
        self,
        *,
        role_id: str,
        system_prompt: str,
        mcp_servers: dict[str, McpServerSpec] | None = None,
        sdk_mcp_servers: dict[str, McpSdkServerConfig] | None = None,
        allowed_tools: list[str] | None = None,
        disallowed_tools: list[str] | None = None,
        can_use_tool: CanUseToolFn | None = None,
        max_turns: int | None = None,
        permission_mode: PermissionMode = "bypassPermissions",
        tool_failure_count: int = 0,
        setting_sources: list[SettingSource] | None = None,
        thinking: dict[str, Any] | None = None,
        max_thinking_tokens: int | None = None,  # Deprecated: use thinking
        sandbox: SandboxSettings | None = None,
        agents: dict[str, AgentDefinition] | None = None,
        env: dict[str, str] | None = None,
        output_format: dict[str, Any] | None = None,
        continue_conversation: bool = False,
        resume: str | None = None,
        fork_session: bool = False,
        betas: list[SdkBeta] | None = None,
        plugins: list[SdkPluginConfig] | None = None,
        include_partial_messages: bool = False,
        enable_file_checkpointing: bool = False,
        max_budget_usd: float | None = None,
        fallback_model: str | None = None,
        hooks: dict[str, list[HookMatcher]] | None = None,
    ) -> ClaudeAgentOptions:
        """Build."""

        model = (
            self._override_model
            if self._override_model
            else self._model_policy.select(role_id, tool_failure_count)
        )

        all_mcp: dict[str, Any] = {}

        if mcp_servers:
            for name, spec in mcp_servers.items():
                all_mcp[name] = _spec_to_sdk_config(spec)

        if sdk_mcp_servers:
            all_mcp.update(sdk_mcp_servers)

        sources: list[SettingSource] = setting_sources if setting_sources is not None else []

        # Resolve thinking config: new `thinking` dict takes precedence,
        # fall back to deprecated `max_thinking_tokens` for backward compat.
        thinking_config = _resolve_thinking(thinking, max_thinking_tokens)

        opts = ClaudeAgentOptions(
            model=model,
            system_prompt=system_prompt,
            mcp_servers=all_mcp,
            allowed_tools=allowed_tools or [],
            disallowed_tools=disallowed_tools or [],
            can_use_tool=can_use_tool,
            max_turns=max_turns,
            permission_mode=permission_mode,
            cwd=str(self._cwd) if self._cwd else None,
            setting_sources=sources,
            thinking=thinking_config,
            sandbox=sandbox,
            agents=agents,
            env=env or {},
            output_format=output_format,
            continue_conversation=continue_conversation,
            resume=resume,
            fork_session=fork_session,
            betas=betas or [],
            plugins=plugins or [],
            include_partial_messages=include_partial_messages,
            enable_file_checkpointing=enable_file_checkpointing,
            max_budget_usd=max_budget_usd,
            fallback_model=fallback_model,
            hooks=hooks,  # type: ignore[arg-type]
        )
        return opts


# ---------------------------------------------------------------------------
# Thinking config resolution
# ---------------------------------------------------------------------------

ThinkingConfig = ThinkingConfigAdaptive | ThinkingConfigEnabled | ThinkingConfigDisabled


def _resolve_thinking(
    thinking: dict[str, Any] | None,
    max_thinking_tokens: int | None,
) -> ThinkingConfig | None:
    """Resolve thinking configuration.

    Priority: ``thinking`` dict > deprecated ``max_thinking_tokens``.
    """
    if thinking is not None:
        kind = thinking.get("type", "enabled")
        if kind == "enabled":
            return ThinkingConfigEnabled(
                type="enabled",
                budget_tokens=thinking.get("budget_tokens", 10000),
            )
        if kind == "adaptive":
            return ThinkingConfigAdaptive(type="adaptive")
        if kind == "disabled":
            return ThinkingConfigDisabled(type="disabled")
        raise ValueError(
            f"Unknown thinking type: {kind!r}. Expected: 'enabled', 'adaptive', 'disabled'"
        )

    if max_thinking_tokens is not None:
        return ThinkingConfigEnabled(
            type="enabled",
            budget_tokens=max_thinking_tokens,
        )

    return None


# ---------------------------------------------------------------------------
# MCP transport builders
# ---------------------------------------------------------------------------


def _build_url_config(spec: McpServerSpec) -> dict[str, Any]:
    """Build url config."""
    _validate_mcp_spec_url(spec)
    return {"type": "http", "url": spec.url or ""}


def _build_sse_config(spec: McpServerSpec) -> dict[str, Any]:
    """Build sse config."""
    _validate_mcp_spec_url(spec)
    return {"type": "sse", "url": spec.url or ""}


def _build_stdio_config(spec: McpServerSpec) -> dict[str, Any]:
    """Build stdio config."""
    cfg: dict[str, Any] = {
        "type": "stdio",
        "command": spec.command or "",
    }
    if spec.args:
        cfg["args"] = spec.args
    if spec.env:
        cfg["env"] = spec.env
    return cfg


_TRANSPORT_BUILDERS: dict[str, Callable[[McpServerSpec], dict[str, Any]]] = {
    "url": _build_url_config,
    "http": _build_url_config,
    "sse": _build_sse_config,
    "stdio": _build_stdio_config,
}


def _spec_to_sdk_config(spec: McpServerSpec) -> dict[str, Any]:
    """Spec to sdk config."""
    builder = _TRANSPORT_BUILDERS.get(spec.transport, _build_url_config)
    return builder(spec)


def _validate_mcp_spec_url(spec: McpServerSpec) -> None:
    url = spec.url or ""
    rejection = validate_http_endpoint_url(
        url,
        allow_private_network=spec.allow_private_network,
        allow_insecure_http=spec.allow_insecure_http,
    )
    if rejection:
        raise ValueError(f"Unsafe MCP server URL for '{spec.name}': {rejection}")
