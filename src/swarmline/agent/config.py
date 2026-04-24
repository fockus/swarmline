"""AgentConfig - frozen configuration for the Agent facade."""

from __future__ import annotations

from dataclasses import dataclass, field
import warnings
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from swarmline.agent.middleware import Middleware
    from swarmline.agent.tool import ToolDefinition
    from swarmline.commands.registry import CommandRegistry
    from swarmline.hooks.registry import HookRegistry
    from swarmline.policy.tool_policy import DefaultToolPolicy
    from swarmline.runtime.capabilities import CapabilityRequirements
    from swarmline.runtime.types import ModelRequestOptions, StructuredMode
    from swarmline.runtime.thin.coding_profile import CodingProfileConfig
    from swarmline.runtime.thin.subagent_tool import SubagentToolConfig


@dataclass(frozen=True)
class AgentConfig:
    """Immutable configuration for the Agent facade.

    The only required parameter is system_prompt.
    All others have sensible defaults.
    """

    system_prompt: str

    # Model (alias or full name)
    model: str = "sonnet"

    # Runtime: claude_sdk | thin | deepagents | openai_agents | cli
    runtime: str = "claude_sdk"

    # Base URL for LLM API (OpenRouter, proxy, etc.). None = provider default.
    base_url: str | None = None

    # Tools (standalone @tool decorated functions)
    tools: tuple[ToolDefinition, ...] = ()

    # Middleware chain (applied in order)
    middleware: tuple[Middleware, ...] = ()

    # Remote MCP servers
    mcp_servers: dict[str, Any] = field(default_factory=dict)

    # Swarmline hooks
    hooks: HookRegistry | None = None

    # Limits
    max_turns: int | None = None
    max_budget_usd: float | None = None

    # Structured output (JSON Schema)
    output_format: dict[str, Any] | None = None

    # Pydantic model type for automatic structured output validation.
    # If set and output_format is None, output_format is auto-generated
    # from model_json_schema(). Runtime validates and retries on error.
    output_type: type | None = None
    structured_mode: StructuredMode = "prompt"
    structured_schema_name: str | None = None
    structured_strict: bool = True
    max_model_retries: int | None = None
    request_options: ModelRequestOptions | None = None

    # Working directory
    cwd: str | None = None

    # Environment variables
    env: dict[str, str] = field(default_factory=dict)

    # SDK-specific (claude_sdk runtime only)
    betas: tuple[str, ...] = ()
    sandbox: dict[str, Any] | None = None
    thinking: dict[str, Any] | None = None  # {"type": "enabled", "budget_tokens": N} | {"type": "adaptive"} | {"type": "disabled"}
    max_thinking_tokens: int | None = None  # Deprecated: use thinking instead
    fallback_model: str | None = None
    permission_mode: str = "bypassPermissions"
    setting_sources: tuple[str, ...] = ()

    # Tool policy (default-deny enforcement)
    tool_policy: DefaultToolPolicy | None = None

    # Subagent configuration (spawn_agent tool)
    subagent_config: SubagentToolConfig | None = None

    # Command registry (slash-command routing)
    command_registry: CommandRegistry | None = None

    # Coding profile (opt-in coding-agent tool surface + policy)
    coding_profile: CodingProfileConfig | None = None

    # Runtime convergence / capability negotiation
    feature_mode: str = "portable"
    require_capabilities: CapabilityRequirements | None = None
    allow_native_features: bool = False
    native_config: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.system_prompt or not self.system_prompt.strip():
            raise ValueError("system_prompt must not be empty")

    @property
    def resolved_model(self) -> str:
        """Deprecated compatibility wrapper for model alias resolution."""
        from swarmline.runtime.types import resolve_model_name

        warnings.warn(
            "AgentConfig.resolved_model is deprecated; use swarmline.runtime.types.resolve_model_name() "
            "or inject a RuntimeFactoryPort instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return resolve_model_name(self.model)
