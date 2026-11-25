"""Runtime package."""

from __future__ import annotations

from importlib import import_module
from typing import Any

# --- AgentRuntime v1 contract ---
from swarmline.runtime.base import AgentRuntime
from swarmline.runtime.capabilities import (
    RUNTIME_CAPABILITY_FLAGS,
    RUNTIME_TIERS,
    VALID_FEATURE_MODES,
    CapabilityRequirements,
    FeatureMode,
    RuntimeCapabilities,
    RuntimeTier,
    get_runtime_capabilities,
)
from swarmline.runtime.factory import RuntimeFactory
from swarmline.runtime.model_policy import ModelPolicy
from swarmline.runtime.registry import (
    RuntimeRegistry,
    get_default_registry,
    get_valid_runtime_names,
    reset_default_registry,
)
from swarmline.runtime.model_registry import ModelRegistry, get_registry, reset_registry
from swarmline.runtime.model_profile import (
    UNKNOWN_MODEL_PROFILE,
    ModelProfile,
    PromptCacheMode,
    resolve_model_profile,
)

from swarmline.runtime.fallback import (
    ClassifiedError,
    CooldownStatePort,
    FallbackChain,
    FallbackEntry,
    FallbackResolver,
    InMemoryCooldownState,
    RemediationAction,
)

from swarmline.runtime.ports import BaseRuntimePort
from swarmline.runtime.ports.base import StreamEvent, convert_event

from swarmline.runtime.types import (
    DEFAULT_MODEL,
    RUNTIME_ERROR_KINDS,
    RUNTIME_EVENT_TYPES,
    VALID_MODEL_NAMES,
    VALID_RUNTIME_NAMES,
    Message,
    ModelRequestOptions,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
    ToolSpec,
    TurnMetrics,
    StructuredMode,
    resolve_model_name,
)

__all__ = [
    "DEFAULT_MODEL",
    "ThinRuntime",
    # Fallback chain / provider cascade (OSS-T5)
    "ClassifiedError",
    "CooldownStatePort",
    "FallbackChain",
    "FallbackEntry",
    "FallbackResolver",
    "InMemoryCooldownState",
    "RemediationAction",
    "RUNTIME_CAPABILITY_FLAGS",
    "RUNTIME_ERROR_KINDS",
    "RUNTIME_EVENT_TYPES",
    "RUNTIME_TIERS",
    "UNKNOWN_MODEL_PROFILE",
    "VALID_FEATURE_MODES",
    "VALID_MODEL_NAMES",
    "VALID_RUNTIME_NAMES",
    "AgentRuntime",
    "BaseRuntimePort",
    "CapabilityRequirements",
    "FeatureMode",
    "Message",
    "ModelRequestOptions",
    "ModelPolicy",
    "ModelProfile",
    "ModelRegistry",
    "PiSdkOptions",
    "PiSdkRuntime",
    "PromptCacheMode",
    "RuntimeCapabilities",
    "RuntimeConfig",
    "RuntimeErrorData",
    "RuntimeEvent",
    "RuntimeFactory",
    "RuntimeRegistry",
    "RuntimeTier",
    "StreamEvent",
    "ToolSpec",
    "TurnMetrics",
    "StructuredMode",
    "convert_event",
    "get_default_registry",
    "get_registry",
    "get_runtime_capabilities",
    "get_valid_runtime_names",
    "reset_default_registry",
    "reset_registry",
    "resolve_model_name",
    "resolve_model_profile",
]

_OPTIONAL_EXPORTS: dict[str, tuple[str, str, str]] = {
    "ThinRuntime": (
        "swarmline.runtime.thin.runtime",
        "ThinRuntime",
        "Install optional thin runtime dependencies to use ThinRuntime.",
    ),
    "DeepAgentsRuntimePort": (
        "swarmline.runtime.ports",
        "DeepAgentsRuntimePort",
        "Install optional deepagents dependencies to use DeepAgentsRuntimePort.",
    ),
    "ThinRuntimePort": (
        "swarmline.runtime.ports",
        "ThinRuntimePort",
        "Install optional thin runtime dependencies to use ThinRuntimePort.",
    ),
    "ClaudeOptionsBuilder": (
        "swarmline.runtime.options_builder",
        "ClaudeOptionsBuilder",
        "Install claude-agent-sdk to use ClaudeOptionsBuilder.",
    ),
    "RuntimeAdapter": (
        "swarmline.runtime.adapter",
        "RuntimeAdapter",
        "Install claude-agent-sdk to use RuntimeAdapter.",
    ),
    "PiSdkOptions": (
        "swarmline.runtime.pi_sdk",
        "PiSdkOptions",
        "Install Node.js and @mariozechner/pi-coding-agent to execute PiSdkRuntime.",
    ),
    "PiSdkRuntime": (
        "swarmline.runtime.pi_sdk",
        "PiSdkRuntime",
        "Install Node.js and @mariozechner/pi-coding-agent to execute PiSdkRuntime.",
    ),
    "QueryResult": (
        "swarmline.runtime.sdk_query",
        "QueryResult",
        "Install claude-agent-sdk to use QueryResult.",
    ),
    "one_shot_query": (
        "swarmline.runtime.sdk_query",
        "one_shot_query",
        "Install claude-agent-sdk to use one_shot_query.",
    ),
    "stream_one_shot_query": (
        "swarmline.runtime.sdk_query",
        "stream_one_shot_query",
        "Install claude-agent-sdk to use stream_one_shot_query.",
    ),
    "create_mcp_server": (
        "swarmline.runtime.sdk_tools",
        "create_mcp_server",
        "Install claude-agent-sdk to use create_mcp_server.",
    ),
    "mcp_tool": (
        "swarmline.runtime.sdk_tools",
        "mcp_tool",
        "Install claude-agent-sdk to use mcp_tool.",
    ),
    "ClaudeCodeRuntimeAdapter": (
        "swarmline.runtime.code_runtime.claude",
        "ClaudeCodeRuntimeAdapter",
        "ClaudeCodeRuntimeAdapter — CodeRuntimePort for Claude Code.",
    ),
    "CodexCodeRuntimeAdapter": (
        "swarmline.runtime.code_runtime.codex",
        "CodexCodeRuntimeAdapter",
        "CodexCodeRuntimeAdapter — CodeRuntimePort for Codex/OpenAI.",
    ),
}


def __getattr__(name: str) -> Any:
    """Lazy-load optional runtime exports and fail fast when extras are absent."""
    optional = _OPTIONAL_EXPORTS.get(name)
    if optional is None:
        try:
            module = import_module(f"{__name__}.{name}")
        except ImportError as exc:
            raise AttributeError(
                f"module {__name__!r} has no attribute {name!r}"
            ) from exc

        globals()[name] = module
        return module

    module_name, attr_name, hint = optional
    try:
        module = import_module(module_name)
        value = getattr(module, attr_name)
    except (ImportError, AttributeError) as exc:
        raise ImportError(f"{attr_name} is unavailable. {hint}") from exc

    globals()[name] = value
    return value
