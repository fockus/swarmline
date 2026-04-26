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
    from swarmline.runtime.types import (
        ModelRequestOptions,
        StructuredMode,
        ThinkingConfig,
    )
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

    # Runtime: thin (default — lightweight, multi-provider) | claude_sdk | deepagents | cli | openai_agents | pi_sdk
    runtime: str = "thin"

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
    # Extended thinking. Accepts either:
    #   - a typed dataclass: ThinkingConfigEnabled / ThinkingConfigAdaptive / ThinkingConfigDisabled
    #   - a dict (deprecated, auto-converted in __post_init__):
    #       {"type": "enabled", "budget_tokens": N}
    #       {"type": "adaptive"}
    #       {"type": "disabled"}
    thinking: dict[str, Any] | ThinkingConfig | None = None
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
    runtime_options: Any | None = None

    def __post_init__(self) -> None:
        if not self.system_prompt or not self.system_prompt.strip():
            raise ValueError("system_prompt must not be empty")

        # Accept both dict (deprecated) and the typed ThinkingConfig dataclass.
        # Internally we always store the dict form, which downstream consumers
        # (claude_sdk adapter, options_builder, ThinRuntime) already handle.
        from swarmline.runtime.types import ThinkingConfig as _ThinkingConfig

        if isinstance(self.thinking, _ThinkingConfig):
            object.__setattr__(
                self,
                "thinking",
                {"type": "enabled", "budget_tokens": self.thinking.budget_tokens},
            )
        elif isinstance(self.thinking, dict):
            warnings.warn(
                "AgentConfig(thinking=<dict>) is deprecated; pass the typed "
                "swarmline.runtime.types.ThinkingConfig dataclass instead. "
                "The dict form will be removed in a future release.",
                DeprecationWarning,
                stacklevel=2,
            )

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
