"""Internal helpers for runtime port state and stream handling."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable, Sequence
from typing import TYPE_CHECKING, Any

from swarmline.runtime.types import Message, RuntimeEvent

logger = logging.getLogger(__name__)

CompactionTrigger = tuple[str, int]

if TYPE_CHECKING:
    from swarmline.runtime.ports.base import StreamEvent


def _estimate_tokens(messages: Sequence[Message]) -> int:
    """Estimate token count from message contents."""
    return sum(len(msg.content) for msg in messages) // 4


def append_to_history(
    history: list[Message],
    history_max: int,
    role: str,
    content: str,
) -> None:
    """Append a message and keep the sliding window bounded."""
    history.append(Message(role=role, content=content))
    if len(history) > history_max:
        del history[:-history_max]


def should_compact(
    history: Sequence[Message], compaction_trigger: CompactionTrigger
) -> bool:
    """Check whether history should be compacted."""
    trigger_type, threshold = compaction_trigger
    if trigger_type == "tokens":
        return _estimate_tokens(history) >= threshold
    if trigger_type == "messages":
        return len(history) >= threshold
    msg = f"Unknown compaction trigger type: {trigger_type!r}. Allowed: 'tokens', 'messages'"
    raise ValueError(msg)


async def maybe_summarize(
    history: Sequence[Message],
    summarizer: Any | None,
    compaction_trigger: CompactionTrigger,
) -> str | None:
    """Summarize history when the compaction trigger fires."""
    if not summarizer or not should_compact(history, compaction_trigger):
        return None

    from swarmline.memory.types import MemoryMessage
    from swarmline.runtime.ports.base import truncate_long_args

    raw = [{"role": msg.role, "content": msg.content} for msg in history]
    truncated = truncate_long_args(raw)
    mem_messages = [
        MemoryMessage(role=item["role"], content=item["content"]) for item in truncated
    ]

    try:
        if hasattr(summarizer, "asummarize"):
            return await summarizer.asummarize(mem_messages)
        return summarizer.summarize(mem_messages)
    except Exception:
        logger.warning("Ошибка auto-summarization", exc_info=True)
        return None


def build_system_prompt(
    system_prompt: str,
    rolling_summary: str,
    memory_sources: Sequence[str],
) -> str:
    """Assemble final system prompt with memory and rolling summary."""
    from swarmline.runtime.portable_memory import (
        inject_memory_into_prompt,
        load_agents_md,
    )

    prompt = system_prompt

    if memory_sources:
        memory_content = load_agents_md(list(memory_sources))
        prompt = inject_memory_into_prompt(prompt, memory_content)

    if rolling_summary:
        prompt = (
            f"{prompt}\n\n## Краткое содержание предыдущего диалога\n{rolling_summary}"
        )

    return prompt


async def stream_runtime_reply(
    *,
    messages: list[Message],
    system_prompt: str,
    run_runtime: Callable[..., AsyncIterator[RuntimeEvent]],
    convert_event_fn: Callable[[RuntimeEvent], StreamEvent | None],
    append_assistant: Callable[[str], None] | None = None,
) -> AsyncIterator[StreamEvent]:
    """Consume runtime events and emit StreamEvent values."""
    from swarmline.runtime.ports.base import StreamEvent

    full_text = ""
    final_text = ""
    final_data: dict[str, Any] | None = None
    saw_terminal_event = False

    try:
        async for event in run_runtime(messages=messages, system_prompt=system_prompt):
            if event.type == "final":
                final_data = event.data
                final_text = str(event.data.get("text", ""))
                saw_terminal_event = True
                continue

            if event.type == "error":
                stream_event = convert_event_fn(event)
                if stream_event:
                    yield stream_event
                saw_terminal_event = True
                return

            stream_event = convert_event_fn(event)
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

    if full_text and append_assistant:
        append_assistant(full_text)

    done_event = StreamEvent(type="done", text=full_text, is_final=True)
    if final_data is not None:
        done_event.session_id = final_data.get("session_id")
        done_event.total_cost_usd = final_data.get("total_cost_usd")
        done_event.usage = final_data.get("usage")
        done_event.structured_output = final_data.get("structured_output")
        done_event.native_metadata = final_data.get("native_metadata")

    yield done_event
