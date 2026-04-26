"""Types for runtime pluggability - AgentRuntime v1 contract.

Domain types (Message, ToolSpec, RuntimeEvent, RuntimeErrorData, TurnMetrics)
are defined in swarmline.domain_types and re-exported here for backward compatibility.

RuntimeConfig remains here as it depends on infrastructure (CancellationToken, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# Re-export domain types for backward compatibility
from swarmline.domain_types import (  # noqa: F401
    RUNTIME_ERROR_KINDS,
    RUNTIME_EVENT_TYPES,
    ContentBlock,
    ImageBlock,
    Message,
    RuntimeErrorData,
    RuntimeEvent,
    TextBlock,
    ThinkingConfig,
    ToolSpec,
    TurnMetrics,
)
from swarmline.compaction import CompactionConfig  # noqa: TC001
from swarmline.runtime.cancellation import CancellationToken  # noqa: TC001
from swarmline.runtime.capabilities import (
    VALID_FEATURE_MODES,
    VALID_RUNTIME_NAMES,
    CapabilityRequirements,
)
from swarmline.runtime.cost import CostBudget  # noqa: TC001

# ---------------------------------------------------------------------------
# RuntimeConfig - runtime configuration (infrastructure, stays here)
# ---------------------------------------------------------------------------

StructuredMode = Literal["prompt", "native", "auto"]


@dataclass(frozen=True)
class ModelRequestOptions:
    """Provider-neutral request options for LLM calls.

    Common fields are forwarded by adapters when supported. Provider-specific
    data stays in provider_options/plugins/extra so the public API remains
    provider-neutral.
    """

    max_tokens: int | None = None
    temperature: float | None = None
    timeout_sec: float | None = None
    response_format: dict[str, Any] | None = None
    reasoning: dict[str, Any] | None = None
    provider_options: dict[str, Any] = field(default_factory=dict)
    plugins: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Models - delegated to ModelRegistry (models.yaml)
# ---------------------------------------------------------------------------


def _get_registry():
    """Lazy ModelRegistry loading (avoid circular imports)."""
    from swarmline.runtime.model_registry import get_registry

    return get_registry()


def _valid_model_names() -> frozenset[str]:
    """Allowed full model names (from YAML config)."""
    result: frozenset[str] = _get_registry().valid_models
    return result


def _default_model() -> str:
    """Default model (from YAML config)."""
    result: str = _get_registry().default_model
    return result


# Backward-compatible constants (lazy properties do not work for frozenset,
# so we export functions plus static aliases for imports)
VALID_MODEL_NAMES: frozenset[str] = frozenset()  # Populated on first use
DEFAULT_MODEL: str = "claude-sonnet-4-20250514"  # Static fallback


def _ensure_model_constants() -> None:
    """Initialize model constants from the registry (once)."""
    global VALID_MODEL_NAMES, DEFAULT_MODEL
    if not VALID_MODEL_NAMES:
        try:
            reg = _get_registry()
            VALID_MODEL_NAMES = reg.valid_models
            DEFAULT_MODEL = reg.default_model
        except Exception:
            # Fallback if YAML is unavailable
            VALID_MODEL_NAMES = frozenset({"claude-sonnet-4-20250514"})
            DEFAULT_MODEL = "claude-sonnet-4-20250514"


def resolve_model_name(raw: str | None) -> str:
    """Resolve a model name: alias/prefix/full -> full name.

    Multi-provider support - models and aliases are loaded from models.yaml.
    Supports Anthropic, OpenAI, Google, DeepSeek, and others.

    Examples:
    - "sonnet" -> "claude-sonnet-4-20250514"
    - "gpt-4o" -> "gpt-4o"
    - "gemini" -> "gemini-2.5-pro"
    - "r1" -> "deepseek-reasoner"
    - "openrouter:anthropic/claude-3.5-haiku" -> "openrouter:anthropic/claude-3.5-haiku"
    - None -> DEFAULT_MODEL
    """
    _ensure_model_constants()
    if raw:
        normalized = raw.strip()
        if ":" in normalized:
            prefix, model_part = normalized.split(":", 1)
            provider = prefix.strip().lower()
            if provider == "google_genai":
                provider = "google"
            if provider in {
                "anthropic",
                "google",
                "openai",
                "openrouter",
                "ollama",
                "local",
                "together",
                "groq",
                "fireworks",
                "deepseek",
            }:
                return f"{provider}:{model_part.strip()}"
    result: str = _get_registry().resolve(raw)
    return result


@dataclass
class RuntimeConfig:
    """Configuration for runtime selection and parameters.

    Priority: runtime_override > runtime_name > env SWARMLINE_RUNTIME > default.
    """

    runtime_name: str = "claude_sdk"

    # Budgets for ThinRuntime
    max_iterations: int = 6
    max_tool_calls: int = 8
    max_model_retries: int = 2

    # Model for ThinRuntime / DeepAgents
    model: str = DEFAULT_MODEL

    # Base URL for the LLM API (OpenRouter, proxy, etc.)
    # None = provider default URL
    base_url: str | None = None

    # Structured output schema for the portable/native runtime path
    output_format: dict[str, Any] | None = None

    # Pydantic model type for automatic structured output validation
    # If set and output_format=None, output_format is generated from model_json_schema()
    output_type: type | None = None

    # Structured output mode:
    # - prompt: portable prompt instruction + local validation (backward compatible)
    # - native: provider-native JSON mode/schema when supported
    # - auto: native when supported, otherwise prompt
    structured_mode: StructuredMode = "prompt"
    structured_schema_name: str | None = None
    structured_strict: bool = True

    # Provider-neutral inference/request options
    request_options: ModelRequestOptions | None = None

    # Additional parameters (extensible)
    extra: dict[str, Any] = field(default_factory=dict)

    # Runtime convergence / capability negotiation
    feature_mode: str = "portable"
    required_capabilities: CapabilityRequirements | None = None
    allow_native_features: bool = False
    native_config: dict[str, Any] = field(default_factory=dict)

    # Cooperative cancellation token
    cancellation_token: CancellationToken | None = None

    # Cost budget tracking
    cost_budget: CostBudget | None = None

    # Guardrails - checked before/after LLM calls
    input_guardrails: list[Any] = field(default_factory=list)  # list[InputGuardrail]
    output_guardrails: list[Any] = field(default_factory=list)  # list[OutputGuardrail]

    # Pre-LLM input filters - applied to messages/system_prompt before the turn
    input_filters: list[Any] = field(default_factory=list)  # list[InputFilter]

    # Retry policy for LLM call failures (e.g. ExponentialBackoff)
    retry_policy: Any | None = None  # RetryPolicy

    # Observability: EventBus for pub-sub runtime events
    event_bus: Any | None = None  # EventBus

    # Observability: Tracer for span-based tracing
    tracer: Any | None = None  # Tracer

    # RAG: Retriever for automatic context injection
    retriever: Any | None = None  # Retriever

    # Native tool calling: opt-in for provider-native tool APIs (Strangler Fig)
    use_native_tools: bool = False

    # Web tool domain filtering (applied to HttpxWebProvider)
    web_allowed_domains: list[str] | None = None
    web_blocked_domains: list[str] | None = None

    # Conversation compaction (3-tier pipeline via InputFilter)
    compaction: CompactionConfig | None = None

    # Extended thinking / chain-of-thought configuration
    thinking: ThinkingConfig | None = None

    @staticmethod
    def _get_valid_names() -> frozenset[str]:
        """Get valid runtime names: static builtins + dynamic registry."""
        try:
            from swarmline.runtime.registry import get_valid_runtime_names

            return get_valid_runtime_names()
        except Exception:
            return VALID_RUNTIME_NAMES

    def __post_init__(self) -> None:
        # Auto-generate output_format from output_type if not explicitly provided
        if self.output_type is not None and self.output_format is None:
            schema_builder = getattr(self.output_type, "model_json_schema", None)
            if not callable(schema_builder):
                raise TypeError("output_type must define model_json_schema()")
            self.output_format = schema_builder()

        valid_names = self._get_valid_names()
        if self.runtime_name not in valid_names:
            raise ValueError(
                f"Unknown runtime: '{self.runtime_name}'. "
                f"Allowed: {', '.join(sorted(valid_names))}"
            )
        if self.feature_mode not in VALID_FEATURE_MODES:
            raise ValueError(
                f"Unknown feature_mode: '{self.feature_mode}'. "
                f"Allowed: {', '.join(sorted(VALID_FEATURE_MODES))}"
            )
        if self.structured_mode not in {"prompt", "native", "auto"}:
            raise ValueError(
                "Unknown structured_mode: "
                f"'{self.structured_mode}'. Allowed: auto, native, prompt"
            )
        if self.required_capabilities is not None:
            from swarmline.runtime.registry import resolve_runtime_capabilities

            caps = resolve_runtime_capabilities(self.runtime_name)
            missing = caps.missing(self.required_capabilities)
            if missing:
                raise ValueError(
                    "Runtime "
                    f"'{self.runtime_name}' does not support required capabilities: "
                    f"{', '.join(missing)}"
                )

    @property
    def is_native_mode(self) -> bool:
        """True if the native upstream path is used."""
        return self.allow_native_features or self.feature_mode in {
            "hybrid",
            "native_first",
        }
