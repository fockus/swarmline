"""Types for runtime pluggability - AgentRuntime v1 contract.

Domain types (Message, ToolSpec, RuntimeEvent, RuntimeErrorData, TurnMetrics)
are defined in swarmline.domain_types and re-exported here for backward compatibility.

RuntimeConfig remains here as it depends on infrastructure (CancellationToken, etc.).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from swarmline.observability.journal import EventJournal  # noqa: TC001
from swarmline.resilience.checkpoint import CheckpointWriter  # noqa: TC001

if TYPE_CHECKING:
    from swarmline.domain_types import ProviderTool
    from swarmline.protocols.external_signal import ExternalSignal
    from swarmline.protocols.verification import Verifier
    from swarmline.types import KernelContext, VerificationLedger

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


def _allow_model_fallback() -> bool:
    """True only when the operator has explicitly opted into silent model fallback.

    Default (env unset) is fail-loud: an unresolvable model raises instead of silently
    becoming the default model.
    """
    import os

    return os.getenv("SWARMLINE_ALLOW_MODEL_FALLBACK", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _known_model_providers() -> frozenset[str]:
    """Provider prefixes that ``resolve_model_name`` accepts as a pass-through.

    Derived from ``provider_resolver._OPENAI_COMPAT_PROVIDERS`` (single source of truth) plus the
    two native providers, so a provider added there can never again drift out of this allowlist —
    that drift is exactly how ``polza:`` once resolved silently to the default model.
    """
    from swarmline.runtime.provider_resolver import _OPENAI_COMPAT_PROVIDERS

    return frozenset(_OPENAI_COMPAT_PROVIDERS) | {"anthropic", "google"}


def _fallback_or_raise(raw: str, reason: str) -> str:
    """Fail loud by default; only fall back to the default model under an explicit opt-in.

    Raises ``UnknownModelError`` unless ``SWARMLINE_ALLOW_MODEL_FALLBACK`` is set, in which case it
    logs a warning and returns the registry default. Silent coercion (the old behaviour) is gone:
    that is how ``polza:gemini`` became ``claude-sonnet-4`` in production with zero signal.
    """
    from swarmline.errors import UnknownModelError

    default = _get_registry().default_model
    if _allow_model_fallback():
        import structlog

        structlog.get_logger(component="runtime.model_resolver").warning(
            "model_fallback_to_default",
            requested=raw,
            reason=reason,
            fallback=default,
        )
        return default
    raise UnknownModelError(
        f"Cannot resolve model {raw!r}: {reason}. "
        f"Known provider prefixes: {', '.join(sorted(_known_model_providers()))}. "
        f"Set SWARMLINE_ALLOW_MODEL_FALLBACK=1 to fall back to {default!r} "
        f"with a warning instead of failing."
    )


def resolve_model_name(raw: str | None) -> str:
    """Resolve a model name: alias/prefix/full -> full name.

    Multi-provider support - models and aliases are loaded from models.yaml.
    Supports Anthropic, OpenAI, Google, DeepSeek, and others.

    Fail-loud: a non-empty model that is neither a known alias/id nor a recognized
    ``provider:model`` slug raises ``UnknownModelError`` instead of silently coercing to the
    default model. Set ``SWARMLINE_ALLOW_MODEL_FALLBACK=1`` to restore the old fall-back (with a
    warning). ``None`` / empty / whitespace remains the caller's explicit "use the default" signal.

    Examples:
    - "sonnet" -> "claude-sonnet-4-20250514"
    - "gpt-4o" -> "gpt-4o"
    - "gemini" -> "gemini-2.5-pro"
    - "r1" -> "deepseek-reasoner"
    - "openrouter:anthropic/claude-3.5-haiku" -> "openrouter:anthropic/claude-3.5-haiku"
    - None -> DEFAULT_MODEL
    - "madeup:foo" -> raises UnknownModelError (unknown provider prefix)
    """
    _ensure_model_constants()
    if raw and raw.strip():
        normalized = raw.strip()
        if ":" in normalized:
            prefix, model_part = normalized.split(":", 1)
            provider = prefix.strip().lower()
            if provider == "google_genai":
                provider = "google"
            if provider in _known_model_providers():
                return f"{provider}:{model_part.strip()}"
            # Provider-prefixed but provider unknown: previously fell through to the registry and
            # silently resolved to DEFAULT_MODEL (the polza->sonnet bug class). Fail loud.
            return _fallback_or_raise(
                normalized, f"unknown provider prefix {provider!r}"
            )
        # No provider prefix: resolve via the registry of bare names/aliases, but use is_known()
        # to distinguish a genuine hit from the registry's silent default-coercion on a total miss.
        if _get_registry().is_known(normalized):
            result: str = _get_registry().resolve(normalized)
            return result
        return _fallback_or_raise(
            normalized, "not a known model id, alias, or provider-prefixed slug"
        )
    # None / empty / whitespace -> caller's explicit signal to use the default model.
    return _get_registry().resolve(raw)


@dataclass
class RuntimeConfig:
    """Configuration for runtime selection and parameters.

    Priority: runtime_override > runtime_name > env SWARMLINE_RUNTIME > default.
    """

    runtime_name: str = "thin"

    # Budgets for ThinRuntime
    max_iterations: int = 6
    max_tool_calls: int = 8
    max_model_retries: int = 2

    # Model for ThinRuntime / DeepAgents
    model: str = DEFAULT_MODEL

    # Base URL for the LLM API (OpenRouter, proxy, etc.)
    # None = provider default URL
    base_url: str | None = None

    # Per-config API key forwarded through resolve_provider to the LLM adapter.
    # None = adapter falls back to the environment variable OPENAI_API_KEY (back-compat default).
    api_key: str | None = None

    # Structured output schema for the portable/native runtime path
    output_format: dict[str, Any] | None = None

    # Pydantic model type for automatic structured output validation
    # If set and output_format=None, output_format is generated from model_json_schema()
    output_type: type | None = None

    # Structured output mode:
    # - prompt: portable prompt instruction + local validation (backward compatible)
    # - native: provider-native JSON mode/schema when supported
    # - auto: native when supported, otherwise prompt
    # In the thin react path, "native"/"auto" also drive native tool-calling
    # (use_native_tools is derived from this): a clean native tool loop + a separate
    # structured-finalization call (two-phase); native failures fall back to text-ReAct.
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

    # SGR (Structured Generation + Reasoning) mode
    sgr_enabled: bool = False

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

    # Iteration budget: opt-in VO-driven loop cap (REQ-OSS-052/053, OSS-T3).
    # Default False keeps the plain ``iterations < max_iterations`` guard so
    # the default path is byte-identical to pre-OSS-T3 behaviour.
    use_iteration_budget: bool = False

    # Web tool domain filtering (applied to HttpxWebProvider)
    web_allowed_domains: list[str] | None = None
    web_blocked_domains: list[str] | None = None

    # Conversation compaction (3-tier pipeline via InputFilter)
    compaction: CompactionConfig | None = None

    # Extended thinking / chain-of-thought configuration
    thinking: ThinkingConfig | None = None

    # Self-evolution: stuck detection + recovery cascade (opt-in)
    evolution_enabled: bool = False
    stuck_detector: Any | None = None  # StuckDetector
    recovery_cascade: Any | None = None  # RecoveryCascade

    # OSS-T4: durable checkpoint (opt-in — default None keeps loop byte-identical).
    # When checkpoint_writer is set together with run_id, the react loop:
    #   (a) on start: loads any prior checkpoint and emits a "resumed" status event;
    #   (b) after each tool call: persists a checkpoint via after_tool_call().
    checkpoint_writer: CheckpointWriter | None = None  # CheckpointWriter
    run_id: str | None = None

    # observability-events Task 2 (REQ-007/014): opt-in event journal tap.
    # Default None keeps ThinRuntime.run() byte-identical (REQ-014); when set,
    # every RuntimeEvent yielded by the run is also appended as a side-channel
    # (see runtime/thin/runtime.py -- the tap never filters or delays the stream).
    event_journal: EventJournal | None = None  # EventJournal

    # kernel-patterns H4 Task 1 (REQ-010): generic mid-run control hooks,
    # optional / default None so every kernel's loop stays byte-identical
    # until a hook is set. Reachable by any kernel through ``ctx.config.*``
    # (KernelContext already carries ``config`` — no duplicate fields there).
    # should_stop_after_turn: called after a turn; True ends the loop gracefully.
    should_stop_after_turn: Callable[[KernelContext], bool] | None = None
    # get_steering_messages: messages injected between turns (loop continues).
    get_steering_messages: Callable[[KernelContext], list] | None = None
    # get_followup_messages: follow-up messages queued once the loop would
    # otherwise end (agent_end) — declared for REQ-010 completeness; wiring
    # into a concrete continuation path is deferred to a later kernel task.
    get_followup_messages: Callable[[KernelContext], list] | None = None
    # transform_context: applied to the LM-facing message list before each
    # model call (tail injection/steering only — see contract below).
    # Contract (conformance-audit Basket 1 item 6 / plan stage 30): the
    # callable may ONLY append new entries to the TAIL of the message list —
    # every entry already present before the call must come back
    # byte-identical, in the same order. This protects build-once / KV-cache
    # prompt-prefix stability; enforced at call time by
    # ``swarmline.runtime.thin.mid_run_hooks.apply_transform_context``, which
    # raises ``TransformContextContractError`` on violation.
    transform_context: Callable[[list], list] | None = None

    external_signal: ExternalSignal | None = None  # H4 Task 6: "reflection" grounding

    # verify-before-done spec, Task 4 (REQ-004/005/008/009): opt-in finalize gate.
    # Active iff BOTH fields are set AND verification_ledger.criteria is non-empty
    # (REQ-008/009: None/empty/either-missing -> finalize unchanged, no-op by default).
    # verification_ledger = the acceptance-criteria contract fixed before execution.
    # verifier = the Verifier run at finalize time (typically a LedgerCodeVerifier, or
    # a caller-composed code+judge verifier) — always against a FRESH criteria-only
    # copy of verification_ledger, never its stored results (see
    # swarmline.verification.gate for the fresh-re-verify rationale, I-027).
    verification_ledger: VerificationLedger | None = None
    verifier: Verifier | None = None

    # Provider-executed (hosted) tools: passthrough tool specs serialized untouched
    # into the provider request and run server-side (Epic E). Empty tuple (default)
    # is a no-op -- byte-identical to pre-Epic-E behavior. Only consumed by the thin
    # runtime's native react path in this Epic; other runtimes carry it, unused.
    # MUST stay the LAST field: RuntimeConfig is not frozen and existing positional
    # constructions must keep binding to the same fields (I-major fix review finding).
    provider_tools: tuple[ProviderTool, ...] = ()

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

            caps = resolve_runtime_capabilities(self.runtime_name).resolve(self)
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
