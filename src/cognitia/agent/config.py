"""AgentConfig - frozen configuration for the Agent facade."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from cognitia.runtime.capabilities import (
    VALID_FEATURE_MODES,
    CapabilityRequirements,
)

if TYPE_CHECKING:
    from cognitia.agent.middleware import Middleware
    from cognitia.agent.tool import ToolDefinition
    from cognitia.hooks.registry import HookRegistry


@dataclass(frozen=True)
class AgentConfig:
    """Immutable configuration for the Agent facade.

    The only required parameter is system_prompt.
    All others have sensible defaults.
    """

    system_prompt: str

    # Model (alias or full name)
    model: str = "sonnet"

    # Runtime: claude_sdk | thin | deepagents
    runtime: str = "claude_sdk"

    # Tools (standalone @tool decorated functions)
    tools: tuple[ToolDefinition, ...] = ()

    # Middleware chain (applied in order)
    middleware: tuple[Middleware, ...] = ()

    # Remote MCP servers
    mcp_servers: dict[str, Any] = field(default_factory=dict)

    # Cognitia hooks
    hooks: HookRegistry | None = None

    # Limits
    max_turns: int | None = None
    max_budget_usd: float | None = None

    # Structured output (JSON Schema)
    output_format: dict[str, Any] | None = None

    # Working directory
    cwd: str | None = None

    # Environment variables
    env: dict[str, str] = field(default_factory=dict)

    # SDK-specific (claude_sdk runtime only)
    betas: tuple[str, ...] = ()
    sandbox: dict[str, Any] | None = None
    max_thinking_tokens: int | None = None
    fallback_model: str | None = None
    permission_mode: str = "bypassPermissions"
    setting_sources: tuple[str, ...] = ()

    # Runtime convergence / capability negotiation
    feature_mode: str = "portable"
    require_capabilities: CapabilityRequirements | None = None
    allow_native_features: bool = False
    native_config: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        from cognitia.runtime.registry import get_valid_runtime_names, resolve_runtime_capabilities

        if not self.system_prompt or not self.system_prompt.strip():
            raise ValueError("system_prompt must not be empty")
        valid_names = get_valid_runtime_names()
        if self.runtime not in valid_names:
            raise ValueError(
                f"Unknown runtime: '{self.runtime}'. "
                f"Allowed: {', '.join(sorted(valid_names))}"
            )
        if self.feature_mode not in VALID_FEATURE_MODES:
            raise ValueError(
                f"Unknown feature_mode: '{self.feature_mode}'. "
                f"Allowed: {', '.join(sorted(VALID_FEATURE_MODES))}"
            )
        if self.require_capabilities is not None:
            caps = resolve_runtime_capabilities(self.runtime)
            missing = caps.missing(self.require_capabilities)
            if missing:
                raise ValueError(
                    f"Runtime '{self.runtime}' does not support required capabilities: "
                    f"{', '.join(missing)}"
                )

    @property
    def resolved_model(self) -> str:
        """Resolve the model alias to its full name."""
        from cognitia.runtime.types import resolve_model_name

        return resolve_model_name(self.model)
