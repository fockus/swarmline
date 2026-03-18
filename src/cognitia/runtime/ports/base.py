"""Base module."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from cognitia.runtime.types import Message, RuntimeConfig, RuntimeEvent

logger = logging.getLogger(__name__)

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


def _estimate_tokens(messages: list[Message]) -> int:
    """Estimate tokens."""
    return sum(len(msg.content) for msg in messages) // 4


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
        self._history.append(Message(role=role, content=content))
        if len(self._history) > self._history_max:
            self._history = self._history[-self._history_max :]

    def _should_compact(self) -> bool:
        """Check trigger for compaction."""
        trigger_type, threshold = self._compaction_trigger
        if trigger_type == "tokens":
            return _estimate_tokens(self._history) >= threshold
        if trigger_type == "messages":
            return len(self._history) >= threshold
        msg = f"Unknown compaction trigger type: {trigger_type!r}. Allowed: 'tokens', 'messages'"
        raise ValueError(msg)

    async def _maybe_summarize(self) -> None:
        """Maybe summarize."""
        if not self._summarizer or not self._should_compact():
            return

        from cognitia.memory.types import MemoryMessage


        raw = [{"role": msg.role, "content": msg.content} for msg in self._history]
        truncated = truncate_long_args(raw)


        mem_messages = [MemoryMessage(role=m["role"], content=m["content"]) for m in truncated]

        try:
            if hasattr(self._summarizer, "asummarize"):
                self._rolling_summary = await self._summarizer.asummarize(mem_messages)
            else:
                self._rolling_summary = self._summarizer.summarize(mem_messages)
        except Exception:
            logger.warning("Ошибка auto-summarization", exc_info=True)

    def _build_system_prompt(self) -> str:
        """Build system prompt."""
        from cognitia.runtime.portable_memory import inject_memory_into_prompt, load_agents_md

        prompt = self._system_prompt

        # Inject memory from AGENTS.md
        if self._memory_sources:
            memory_content = load_agents_md(self._memory_sources)
            prompt = inject_memory_into_prompt(prompt, memory_content)

        # Add rolling summary
        if self._rolling_summary:
            prompt = f"{prompt}\n\n## Краткое содержание предыдущего диалога\n{self._rolling_summary}"

        return prompt

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

        full_text = ""
        final_text = ""
        final_data: dict[str, Any] | None = None
        saw_terminal_event = False

        try:
            async for event in self._run_runtime(
                messages=list(self._history),
                system_prompt=self._build_system_prompt(),
            ):

                if event.type == "final":
                    final_data = event.data
                    final_text = str(event.data.get("text", ""))
                    saw_terminal_event = True
                    continue

                if event.type == "error":
                    stream_event = convert_event(event)
                    if stream_event:
                        yield stream_event
                    saw_terminal_event = True
                    return

                stream_event = convert_event(event)
                if stream_event:
                    if stream_event.type == "text_delta":
                        full_text += stream_event.text
                    yield stream_event

        except Exception as e:
            error_msg = f"Ошибка runtime: {type(e).__name__}: {e}"
            logger.error(error_msg, exc_info=True)
            yield StreamEvent(type="error", text=error_msg)
            return

        if not saw_terminal_event:
            yield StreamEvent(
                type="error",
                text="runtime stream ended without final RuntimeEvent",
            )
            return


        if not full_text and final_text:
            full_text = final_text
            yield StreamEvent(type="text_delta", text=full_text)

        if full_text:
            self._append_to_history("assistant", full_text)

        done_event = StreamEvent(type="done", text=full_text, is_final=True)
        if final_data is not None:
            done_event.session_id = final_data.get("session_id")
            done_event.total_cost_usd = final_data.get("total_cost_usd")
            done_event.usage = final_data.get("usage")
            done_event.structured_output = final_data.get("structured_output")
            done_event.native_metadata = final_data.get("native_metadata")

        yield done_event
