"""Types for runtime pluggability - AgentRuntime v1 contract.

Contains:
- Message: universal runtime message (extends MemoryMessage)
- ToolSpec: tool description (name, description, parameters)
- RuntimeEvent: unified streaming event
- RuntimeErrorData: typed runtime error
- RuntimeConfig: runtime selection and parameter configuration
- TurnMetrics: metrics for a turn
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from cognitia.runtime.cancellation import CancellationToken  # noqa: TC001
from cognitia.runtime.capabilities import (
    VALID_FEATURE_MODES,
    VALID_RUNTIME_NAMES,
    CapabilityRequirements,
)
from cognitia.runtime.cost import CostBudget  # noqa: TC001

# ---------------------------------------------------------------------------
# Message - canonical runtime message
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Message:
    """Universal message for AgentRuntime.

  Extends MemoryMessage: adds name (for tool results) and metadata.
  Compatible with MemoryMessage via from_memory_message().
  """

    role: str  # "user" | "assistant" | "tool" | "system"
    content: str
    name: str | None = None  # tool name (for role="tool")
    tool_calls: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None

    @classmethod
    def from_memory_message(cls, mm: Any) -> Message:
        """Create a Message from MemoryMessage (backward compat)."""
        return cls(
            role=mm.role,
            content=mm.content,
            tool_calls=getattr(mm, "tool_calls", None),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict (for passing to the LLM API)."""
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name is not None:
            d["name"] = self.name
        if self.tool_calls is not None:
            d["tool_calls"] = self.tool_calls
        if self.metadata is not None:
            d["metadata"] = self.metadata
        return d


# ---------------------------------------------------------------------------
# ToolSpec - tool description
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    """Tool description for passing into the runtime.

  The runtime uses this information to build the tool list
  in the request to the LLM (each runtime converts it to its own format).
  """

    name: str  # "mcp__server__tool_name" or "local_tool_name"
    description: str
    parameters: dict[str, Any]  # JSON Schema
    is_local: bool = False  # True for local tools (called directly)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "is_local": self.is_local,
        }


# ---------------------------------------------------------------------------
# RuntimeErrorData - typed error
# ---------------------------------------------------------------------------

# Allowed error kinds
RUNTIME_ERROR_KINDS = frozenset(
    {
        "runtime_crash",  # fatal runtime error
        "bad_model_output",  # LLM returned invalid JSON
        "loop_limit",  # max_iterations exceeded
        "budget_exceeded",  # max_tool_calls exceeded
        "mcp_timeout",  # MCP call timeout
        "tool_error",  # tool execution error
        "dependency_missing",  # optional dependency missing
        "capability_unsupported",  # runtime does not support the required features
        "cancelled",  # operation cancelled via CancellationToken
        "guardrail_tripwire",  # guardrail check failed (input or output)
        "retry",  # retrying LLM call after a transient failure
    }
)


@dataclass(frozen=True)
class RuntimeErrorData:
    """Typed runtime error.

  Used inside RuntimeEvent(type="error").
  """

    kind: str  # one of RUNTIME_ERROR_KINDS
    message: str
    recoverable: bool = False
    details: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.kind not in RUNTIME_ERROR_KINDS:
            object.__setattr__(
                self,
                "kind",
                "runtime_crash",
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        d: dict[str, Any] = {
            "kind": self.kind,
            "message": self.message,
            "recoverable": self.recoverable,
        }
        if self.details is not None:
            d["details"] = self.details
        return d


# ---------------------------------------------------------------------------
# TurnMetrics - turn metrics
# ---------------------------------------------------------------------------


@dataclass
class TurnMetrics:
    """Metrics for a single turn."""

    latency_ms: int = 0
    iterations: int = 0
    tool_calls_count: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "latency_ms": self.latency_ms,
            "iterations": self.iterations,
            "tool_calls_count": self.tool_calls_count,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "model": self.model,
        }


# ---------------------------------------------------------------------------
# RuntimeEvent - unified streaming event
# ---------------------------------------------------------------------------

# Allowed event types
RUNTIME_EVENT_TYPES = frozenset(
    {
        "assistant_delta",  # streamed text output
        "status",  # status message ("Executing step...")
        "tool_call_started",  # tool call started
        "tool_call_finished",  # tool call finished
        "approval_required",  # human approval / tool review
        "user_input_requested",  # runtime requests human input
        "native_notice",  # important native-specific semantics notice
        "final",  # final response (full text + new_messages)
        "error",  # error
    }
)


@dataclass
class RuntimeEvent:
    """Unified event stream from the runtime.

  Types:
  - assistant_delta: data={"text": "..."}
  - status: data={"text": "..."}
  - tool_call_started: data={"name": "...", "correlation_id": "...", "args": {...}}
  - tool_call_finished: data={"name": "...", "correlation_id": "...", "ok": bool, "result_summary": "..."}
  - approval_required: data={"action_name": "...", "args": {...}, "allowed_decisions": [...], "interrupt_id": "..."}
  - user_input_requested: data={"prompt": "...", "interrupt_id": "..."}
  - native_notice: data={"text": "...", "metadata": {...}}
  - final: data={"text": "...", "new_messages": [...], "metrics": {...}, ...metadata}
  - error: data=RuntimeErrorData.to_dict()
  """

    type: str
    data: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def assistant_delta(text: str) -> RuntimeEvent:
        """Streamed text fragment."""
        return RuntimeEvent(type="assistant_delta", data={"text": text})

    @staticmethod
    def status(text: str) -> RuntimeEvent:
        """Status message."""
        return RuntimeEvent(type="status", data={"text": text})

    @staticmethod
    def approval_required(
        action_name: str,
        args: dict[str, Any] | None = None,
        allowed_decisions: list[str] | None = None,
        interrupt_id: str | None = None,
        description: str = "",
    ) -> RuntimeEvent:
        """Request human approval / tool review."""
        return RuntimeEvent(
            type="approval_required",
            data={
                "action_name": action_name,
                "args": args or {},
                "allowed_decisions": list(allowed_decisions or []),
                "interrupt_id": interrupt_id,
                "description": description,
            },
        )

    @staticmethod
    def user_input_requested(
        prompt: str,
        interrupt_id: str | None = None,
    ) -> RuntimeEvent:
        """The runtime expects user/human input."""
        return RuntimeEvent(
            type="user_input_requested",
            data={"prompt": prompt, "interrupt_id": interrupt_id},
        )

    @staticmethod
    def native_notice(
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> RuntimeEvent:
        """Explicit notice about native-specific semantics."""
        data: dict[str, Any] = {"text": text}
        if metadata is not None:
            data["metadata"] = metadata
        return RuntimeEvent(type="native_notice", data=data)

    @staticmethod
    def tool_call_started(
        name: str,
        args: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> RuntimeEvent:
        """Start of a tool call."""
        cid = correlation_id or uuid.uuid4().hex[:8]
        return RuntimeEvent(
            type="tool_call_started",
            data={"name": name, "correlation_id": cid, "args": args or {}},
        )

    @staticmethod
    def tool_call_finished(
        name: str,
        correlation_id: str,
        ok: bool = True,
        result_summary: str = "",
    ) -> RuntimeEvent:
        """End of a tool call."""
        return RuntimeEvent(
            type="tool_call_finished",
            data={
                "name": name,
                "correlation_id": correlation_id,
                "ok": ok,
                "result_summary": result_summary[:200],
            },
        )

    @staticmethod
    def final(
        text: str,
        new_messages: list[Message] | None = None,
        metrics: TurnMetrics | None = None,
        session_id: str | None = None,
        total_cost_usd: float | None = None,
        usage: dict[str, Any] | None = None,
        structured_output: Any = None,
        native_metadata: dict[str, Any] | None = None,
    ) -> RuntimeEvent:
        """Final response."""
        data: dict[str, Any] = {
            "text": text,
            "new_messages": [m.to_dict() for m in (new_messages or [])],
            "metrics": metrics.to_dict() if metrics else {},
        }
        if session_id is not None:
            data["session_id"] = session_id
        if total_cost_usd is not None:
            data["total_cost_usd"] = total_cost_usd
        if usage is not None:
            data["usage"] = usage
        if structured_output is not None:
            data["structured_output"] = structured_output
        if native_metadata is not None:
            data["native_metadata"] = native_metadata
        return RuntimeEvent(type="final", data=data)

    @staticmethod
    def error(error: RuntimeErrorData) -> RuntimeEvent:
        """Runtime error."""
        return RuntimeEvent(type="error", data=error.to_dict())

    @property
    def text(self) -> str:
        """Text content for assistant_delta, status, and final events."""
        return self.data.get("text", "")

    @property
    def tool_name(self) -> str:
        """Tool name for tool_call_started/finished events."""
        return self.data.get("name", "")

    @property
    def is_final(self) -> bool:
        """True if this is a final event."""
        return self.type == "final"

    @property
    def is_error(self) -> bool:
        """True if this is an error event."""
        return self.type == "error"

    @property
    def is_text(self) -> bool:
        """True if this is an assistant_delta (text streaming) event."""
        return self.type == "assistant_delta"

    @property
    def structured_output(self) -> Any:
        """Structured output from final event, or None."""
        return self.data.get("structured_output")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {"type": self.type, "data": self.data}


# ---------------------------------------------------------------------------
# RuntimeConfig - runtime configuration
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Models - delegated to ModelRegistry (models.yaml)
# ---------------------------------------------------------------------------


def _get_registry():
    """Lazy ModelRegistry loading (avoid circular imports)."""
    from cognitia.runtime.model_registry import get_registry

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

  Priority: runtime_override > runtime_name > env COGNITIA_RUNTIME > default.
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

    @staticmethod
    def _get_valid_names() -> frozenset[str]:
        """Get valid runtime names: static builtins + dynamic registry."""
        try:
            from cognitia.runtime.registry import get_valid_runtime_names

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
        if self.required_capabilities is not None:
            from cognitia.runtime.registry import resolve_runtime_capabilities

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
