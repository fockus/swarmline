"""AgentConfig - frozen configuration for the Agent facade."""

from __future__ import annotations

from dataclasses import dataclass, field
import warnings
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from swarmline.agent.middleware import Middleware
    from swarmline.agent.tool import ToolDefinition
    from swarmline.commands.registry import CommandRegistry
    from swarmline.domain_types import ProviderTool
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

    # Per-config API key forwarded to the LLM adapter. None = adapter falls back to the
    # environment variable OPENAI_API_KEY (back-compat default).
    api_key: str | None = None

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
    #: Single public control for native-vs-portable tool-calling + structured output:
    #: - "prompt" (default): text-ReAct + prompt-based structured output (backward compatible).
    #: - "native": provider-native tool-calling + provider-native structured output
    #:   (``response_format``) when supported; errors if the provider cannot.
    #: - "auto": native when the adapter/provider supports it, else fall back to "prompt"
    #:   (recommended). In the thin react path "native"/"auto" run a CLEAN native tool loop
    #:   followed by a separate structured-finalization call (two-phase); native failures fall
    #:   back to text-ReAct automatically. ``use_native_tools`` overrides the native-tools
    #:   decision independently of structured output.
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

    #: Permission callback (claude_sdk + thin runtimes). Async callable with
    #: the claude-agent-sdk ``CanUseTool`` signature:
    #:   ``async (tool_name: str, input: dict, context) -> PermissionResult``
    #: claude_sdk: requires ``permission_mode`` != "bypassPermissions" (the SDK
    #: never consults the callback when permissions are bypassed).
    #: thin: ALWAYS enforced when set (I-098b security fix -- thin has no
    #: permission_mode concept, and gating on the claude-specific knob would
    #: silently no-op the callback under the default mode); consulted after
    #: tool_policy (policy deny wins), fail-closed on callback errors.
    can_use_tool: Any | None = None

    #: Native subagent definitions (claude_sdk runtime only): name ->
    #: claude-agent-sdk ``AgentDefinition``. Passed straight through to
    #: ``ClaudeAgentOptions.agents``.
    native_agents: dict[str, Any] | None = None

    #: Resume an existing claude_sdk session by id (conversation path). When set,
    #: the adapter passes ``resume=<id>`` and does not force continue_conversation.
    resume_session_id: str | None = None

    #: Fork the resumed session into a new session id instead of continuing it
    #: in place (claude_sdk runtime, used together with resume_session_id).
    fork_session: bool = False

    # Tool policy (default-deny enforcement)
    tool_policy: DefaultToolPolicy | None = None

    # Subagent configuration (spawn_agent tool)
    subagent_config: SubagentToolConfig | None = None

    # Command registry (slash-command routing)
    command_registry: CommandRegistry | None = None

    # Coding profile (opt-in coding-agent tool surface + policy)
    coding_profile: CodingProfileConfig | None = None

    #: Load project instruction files into the system prompt (opt-in).
    #: One switch, same effect on every runtime that supports it:
    #: claude_sdk maps it to setting_sources=["project"] (native CLAUDE.md),
    #: pi_sdk loads project resources natively, portable runtimes get
    #: AGENTS.md/RULES.md/CLAUDE.md/GEMINI.md prepended via
    #: ProjectInstructionFilter. Runtimes without support fail validation.
    project_instructions: bool = False

    # Runtime convergence / capability negotiation
    feature_mode: str = "portable"
    require_capabilities: CapabilityRequirements | None = None
    allow_native_features: bool = False
    native_config: dict[str, Any] = field(default_factory=dict)
    runtime_options: Any | None = None

    #: Capability validation mode. True (default): configuration options that
    #: the selected runtime cannot deliver raise ValueError at Agent
    #: construction. False: they emit a warning and degrade (legacy behavior).
    strict_capabilities: bool = True

    #: Native tool-calling override (advanced). None = derive from ``structured_mode``
    #: (native when "native"/"auto"); set True/False to force native tools on/off
    #: independently of structured output.
    use_native_tools: bool | None = None

    #: Retry policy for per-LLM-call failures inside the react loop (e.g.
    #: ``swarmline.retry.ExponentialBackoff``). Must satisfy the
    #: ``swarmline.retry.RetryPolicy`` Protocol. None (default) keeps the
    #: pre-passthrough behaviour: no retry on LLM call failure.
    retry_policy: Any | None = None  # RetryPolicy

    #: Provider-executed (hosted) tools: passthrough tool specs serialized untouched
    #: into the provider request and run server-side (Epic E). Empty tuple (default)
    #: is a no-op -- byte-identical to pre-Epic-E behavior. Non-empty forces the
    #: native tool-calling path (``use_native_tools``) unless explicitly overridden
    #: to False (see ``runtime_wiring.build_portable_runtime_plan``).
    provider_tools: tuple[ProviderTool, ...] = ()

    def __post_init__(self) -> None:
        if not self.system_prompt or not self.system_prompt.strip():
            raise ValueError("system_prompt must not be empty")

        if self.resume_session_id is not None and (
            not isinstance(self.resume_session_id, str)
            or not self.resume_session_id.strip()
        ):
            raise ValueError("resume_session_id must be a non-empty string")

        if self.can_use_tool is not None and not callable(self.can_use_tool):
            raise ValueError("can_use_tool must be an async callable")

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
