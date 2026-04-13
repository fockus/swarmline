"""Pure domain types — zero external dependencies.

These types form the core contract used across all layers:
- Message: universal runtime message
- ToolSpec: tool metadata
- RuntimeEvent: unified streaming event
- RuntimeErrorData: typed runtime error
- TurnMetrics: analytics data

Clean Architecture: this module has NO dependencies on runtime/,
memory/, tools/, or any external library. Only stdlib.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# ContentBlock - multimodal content blocks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TextBlock:
    """Plain text content block."""

    text: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {"type": "text", "text": self.text}


@dataclass(frozen=True)
class ImageBlock:
    """Base64-encoded image content block."""

    data: str  # base64-encoded image bytes
    media_type: str  # e.g. "image/png", "image/jpeg"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {"type": "image", "data": self.data, "media_type": self.media_type}


ContentBlock = TextBlock | ImageBlock


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
    content_blocks: list[ContentBlock] | None = None

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
        if self.content_blocks is not None:
            d["content_blocks"] = [b.to_dict() for b in self.content_blocks]
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
# ThinkingConfig - extended thinking configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ThinkingConfig:
    """Configuration for LLM extended thinking / chain-of-thought.

    budget_tokens controls how many tokens the model may use for reasoning.
    """

    budget_tokens: int = 10_000


# ---------------------------------------------------------------------------
# RuntimeEvent - unified streaming event
# ---------------------------------------------------------------------------

# Allowed event types
RUNTIME_EVENT_TYPES = frozenset(
    {
        "assistant_delta",  # streamed text output
        "thinking_delta",  # streamed thinking/reasoning fragment
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
    - thinking_delta: data={"text": "..."} (extended thinking fragment)
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
    def thinking_delta(text: str) -> RuntimeEvent:
        """Streamed thinking/reasoning fragment."""
        return RuntimeEvent(type="thinking_delta", data={"text": text})

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
