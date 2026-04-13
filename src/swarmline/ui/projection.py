"""UI Event Projection — transforms RuntimeEvent streams into UI state.

Provides a structured way to project a stream of RuntimeEvent into
a renderable UIState suitable for chat UIs, dashboards, or logs.

Architecture:
- UIBlock union: TextBlock | ToolCallBlock | ToolResultBlock | ErrorBlock
- UIMessage: role + ordered list of UIBlocks + optional timestamp
- UIState: full conversation state (messages + status + metadata)
- EventProjection protocol: apply(event) -> UIState
- ChatProjection: built-in implementation for chat-style UIs
- project_stream: async helper that yields UIState per event
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from swarmline.runtime.types import RuntimeEvent


# ---------------------------------------------------------------------------
# UIBlock — union of block types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TextBlock:
    """Accumulated text content from assistant."""

    text: str


@dataclass(frozen=True)
class ToolCallBlock:
    """A tool call initiation."""

    name: str
    args: dict[str, Any]
    correlation_id: str


@dataclass(frozen=True)
class ToolResultBlock:
    """A tool call result."""

    name: str
    ok: bool
    summary: str
    correlation_id: str


@dataclass(frozen=True)
class ErrorBlock:
    """An error that occurred during processing."""

    kind: str
    message: str


UIBlock = TextBlock | ToolCallBlock | ToolResultBlock | ErrorBlock


# ---------------------------------------------------------------------------
# UIMessage & UIState
# ---------------------------------------------------------------------------

_BLOCK_TYPE_MAP = {
    "text": TextBlock,
    "tool_call": ToolCallBlock,
    "tool_result": ToolResultBlock,
    "error": ErrorBlock,
}


def _block_to_dict(block: UIBlock) -> dict[str, Any]:
    """Serialize a UIBlock to a dict with a 'type' discriminator."""
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ToolCallBlock):
        return {
            "type": "tool_call",
            "name": block.name,
            "args": block.args,
            "correlation_id": block.correlation_id,
        }
    if isinstance(block, ToolResultBlock):
        return {
            "type": "tool_result",
            "name": block.name,
            "ok": block.ok,
            "summary": block.summary,
            "correlation_id": block.correlation_id,
        }
    if isinstance(block, ErrorBlock):
        return {"type": "error", "kind": block.kind, "message": block.message}
    raise ValueError(f"Unknown block type: {type(block)}")  # pragma: no cover


def _block_from_dict(d: dict[str, Any]) -> UIBlock:
    """Deserialize a UIBlock from a dict with 'type' discriminator."""
    block_type = d["type"]
    if block_type == "text":
        return TextBlock(text=d["text"])
    if block_type == "tool_call":
        return ToolCallBlock(
            name=d["name"], args=d["args"], correlation_id=d["correlation_id"]
        )
    if block_type == "tool_result":
        return ToolResultBlock(
            name=d["name"],
            ok=d["ok"],
            summary=d["summary"],
            correlation_id=d["correlation_id"],
        )
    if block_type == "error":
        return ErrorBlock(kind=d["kind"], message=d["message"])
    raise ValueError(f"Unknown block type: {block_type}")  # pragma: no cover


@dataclass
class UIMessage:
    """A single message in the UI conversation."""

    role: str
    blocks: list[UIBlock]
    timestamp: float | None = None


@dataclass
class UIState:
    """Full UI conversation state — serializable snapshot."""

    messages: list[UIMessage]
    status: str = "idle"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "messages": [
                {
                    "role": msg.role,
                    "blocks": [_block_to_dict(b) for b in msg.blocks],
                    "timestamp": msg.timestamp,
                }
                for msg in self.messages
            ],
            "status": self.status,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> UIState:
        """Deserialize from a dict produced by to_dict()."""
        messages = [
            UIMessage(
                role=m["role"],
                blocks=[_block_from_dict(b) for b in m["blocks"]],
                timestamp=m.get("timestamp"),
            )
            for m in d["messages"]
        ]
        return cls(
            messages=messages,
            status=d.get("status", "idle"),
            metadata=d.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# EventProjection Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class EventProjection(Protocol):
    """Protocol for projecting RuntimeEvent streams into UIState."""

    def apply(self, event: RuntimeEvent) -> UIState:
        """Apply a single event and return the updated UIState."""
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# ChatProjection — built-in implementation
# ---------------------------------------------------------------------------


class ChatProjection:
    """Built-in EventProjection for chat-style UIs.

    Maintains internal mutable UIState and updates it on each apply() call.
    All assistant content (text deltas, tool calls/results, errors) is
    accumulated into assistant-role UIMessages.
    """

    def __init__(self) -> None:
        self._state = UIState(messages=[])

    @property
    def state(self) -> UIState:
        """Current UI state snapshot."""
        return self._state

    def apply(self, event: RuntimeEvent) -> UIState:
        """Apply a RuntimeEvent and return updated UIState."""
        handler = _EVENT_HANDLERS.get(event.type)
        if handler is not None:
            handler(self, event)
        return self._state

    def _ensure_assistant_message(self) -> UIMessage:
        """Get or create the current assistant message."""
        if not self._state.messages or self._state.messages[-1].role != "assistant":
            msg = UIMessage(role="assistant", blocks=[], timestamp=time.time())
            self._state.messages.append(msg)
        return self._state.messages[-1]

    def _handle_assistant_delta(self, event: RuntimeEvent) -> None:
        msg = self._ensure_assistant_message()
        text = event.data.get("text", "")
        if msg.blocks and isinstance(msg.blocks[-1], TextBlock):
            # Accumulate into existing TextBlock (frozen, so replace)
            old = msg.blocks[-1]
            msg.blocks[-1] = TextBlock(text=old.text + text)
        else:
            msg.blocks.append(TextBlock(text=text))

    def _handle_tool_call_started(self, event: RuntimeEvent) -> None:
        msg = self._ensure_assistant_message()
        msg.blocks.append(
            ToolCallBlock(
                name=event.data.get("name", ""),
                args=event.data.get("args", {}),
                correlation_id=event.data.get("correlation_id", ""),
            )
        )

    def _handle_tool_call_finished(self, event: RuntimeEvent) -> None:
        msg = self._ensure_assistant_message()
        msg.blocks.append(
            ToolResultBlock(
                name=event.data.get("name", ""),
                ok=event.data.get("ok", False),
                summary=event.data.get("result_summary", ""),
                correlation_id=event.data.get("correlation_id", ""),
            )
        )

    def _handle_error(self, event: RuntimeEvent) -> None:
        msg = self._ensure_assistant_message()
        msg.blocks.append(
            ErrorBlock(
                kind=event.data.get("kind", "runtime_crash"),
                message=event.data.get("message", "Unknown error"),
            )
        )

    def _handle_status(self, event: RuntimeEvent) -> None:
        self._state.status = event.data.get("text", "")

    def _handle_final(self, event: RuntimeEvent) -> None:
        self._state.status = "done"
        # Propagate useful metadata from final event
        for key in ("session_id", "total_cost_usd", "metrics", "usage"):
            if key in event.data:
                self._state.metadata[key] = event.data[key]


# Handler dispatch table (avoids if/elif chain, OCP-friendly)
_EVENT_HANDLERS: dict[str, Any] = {
    "assistant_delta": ChatProjection._handle_assistant_delta,
    "tool_call_started": ChatProjection._handle_tool_call_started,
    "tool_call_finished": ChatProjection._handle_tool_call_finished,
    "error": ChatProjection._handle_error,
    "status": ChatProjection._handle_status,
    "final": ChatProjection._handle_final,
}


# ---------------------------------------------------------------------------
# project_stream — async helper
# ---------------------------------------------------------------------------


async def project_stream(
    events: AsyncIterator[RuntimeEvent],
    projection: EventProjection,
) -> AsyncIterator[UIState]:
    """Project an async stream of RuntimeEvent into UIState snapshots.

    Yields a UIState after each event is applied.
    """
    async for event in events:
        yield projection.apply(event)
