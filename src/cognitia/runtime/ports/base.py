"""Base module."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from cognitia.runtime.ports._helpers import (
    append_to_history,
    build_system_prompt,
    maybe_summarize,
    should_compact,
    stream_runtime_reply,
)
from cognitia.runtime.types import Message, RuntimeConfig, RuntimeEvent

HISTORY_MAX = 20
"""Максимальное количество сообщений в in-memory истории runtime-адаптеров."""


@dataclass
class StreamEvent:
    """Stream Event implementation."""

    type: str  # 'text_delta' | 'tool_use_start' | 'tool_use_result' | 'done' | 'error'
    text: str = ""
    tool_name: str = ""
    tool_input: dict[str, Any] | None = None
    tool_result: str = ""
    allowed_decisions: list[str] | None = None
    interrupt_id: str | None = None
    native_metadata: dict[str, Any] | None = None
    session_id: str | None = None
    total_cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    structured_output: Any = None
    is_final: bool = False


def convert_event(event: RuntimeEvent) -> StreamEvent | None:
    """Convert event."""
    if event.type == "assistant_delta":
        return StreamEvent(type="text_delta", text=str(event.data.get("text", "")))

    if event.type == "status":
        return None

    if event.type == "tool_call_started":
        return StreamEvent(
            type="tool_use_start",
            tool_name=str(event.data.get("name", "")),
            tool_input=event.data.get("args"),
        )

    if event.type == "tool_call_finished":
        return StreamEvent(
            type="tool_use_result",
            tool_name=str(event.data.get("name", "")),
            tool_result=str(event.data.get("result_summary", "")),
        )

    if event.type == "approval_required":
        return StreamEvent(
            type="approval_required",
            text=str(event.data.get("description", "")),
            tool_name=str(event.data.get("action_name", "")),
            tool_input=event.data.get("args"),
            allowed_decisions=event.data.get("allowed_decisions"),
            interrupt_id=event.data.get("interrupt_id"),
        )

    if event.type == "user_input_requested":
        return StreamEvent(
            type="user_input_requested",
            text=str(event.data.get("prompt", "")),
            interrupt_id=event.data.get("interrupt_id"),
        )

    if event.type == "native_notice":
        return StreamEvent(
            type="native_notice",
            text=str(event.data.get("text", "")),
            native_metadata=event.data.get("metadata"),
        )

    if event.type == "error":
        return StreamEvent(
            type="error",
            text=str(event.data.get("message", "Unknown runtime error")),
        )

    if event.type == "final":
        return None

    return None


CompactionTrigger = tuple[str, int]
"""Trigger для compaction: ('messages', N) или ('tokens', N)."""


_ARG_TRUNCATION_MAX = 2000
"""Максимальная длина content для tool messages перед summarization."""


_TRUNCATABLE_ROLES = frozenset({"tool", "function"})


def truncate_long_args(
    messages: list[dict[str, str]],
    max_chars: int = _ARG_TRUNCATION_MAX,
) -> list[dict[str, str]]:
    """Truncate long args."""
    result = []
    for msg in messages:
        content = msg["content"]
        if msg["role"] in _TRUNCATABLE_ROLES and len(content) > max_chars:
            truncated = content[:max_chars] + "... [truncated]"
            result.append({**msg, "content": truncated})
        else:
            result.append(msg)
    return result


class BaseRuntimePort:
    """Base Runtime Port implementation."""

    def __init__(
        self,
        system_prompt: str,
        config: RuntimeConfig | None = None,
        history_max: int = HISTORY_MAX,
        summarizer: Any | None = None,
        compaction_trigger: CompactionTrigger | None = None,
        memory_sources: list[str] | None = None,
    ) -> None:
        self._system_prompt = system_prompt
        self._config = config or RuntimeConfig(runtime_name="thin")
        self._connected = False
        self._history: list[Message] = []
        self._history_max = history_max
        self._summarizer = summarizer  # LLMSummaryGenerator or None
        self._rolling_summary: str = ""
        self._compaction_trigger = compaction_trigger or ("messages", history_max)
        self._memory_sources = memory_sources or []

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        """Connect."""
        self._connected = True

    async def disconnect(self) -> None:
        """Disconnect."""
        self._connected = False
        self._history.clear()

    def _append_to_history(self, role: str, content: str) -> None:
        """Append to history."""
        append_to_history(self._history, self._history_max, role, content)

    def _should_compact(self) -> bool:
        """Check trigger for compaction."""
        return should_compact(self._history, self._compaction_trigger)

    async def _maybe_summarize(self) -> None:
        """Maybe summarize."""
        summary = await maybe_summarize(
            self._history,
            self._summarizer,
            self._compaction_trigger,
        )
        if summary is not None:
            self._rolling_summary = summary

    def _build_system_prompt(self) -> str:
        """Build system prompt."""
        return build_system_prompt(
            self._system_prompt,
            self._rolling_summary,
            self._memory_sources,
        )

    async def _run_runtime(
        self,
        messages: list[Message],
        system_prompt: str,
    ) -> AsyncIterator[RuntimeEvent]:
        """Run runtime."""
        raise NotImplementedError  # pragma: no cover
        yield  # pragma: no cover

    async def stream_reply(self, user_text: str) -> AsyncIterator[StreamEvent]:
        """Stream reply."""
        if not self._connected:
            yield StreamEvent(type="error", text="Runtime not connected")
            return

        self._append_to_history("user", user_text)
        await self._maybe_summarize()
        async for event in stream_runtime_reply(
            messages=list(self._history),
            system_prompt=self._build_system_prompt(),
            run_runtime=self._run_runtime,
            convert_event_fn=convert_event,
            append_assistant=lambda text: self._append_to_history("assistant", text),
        ):
            yield event
