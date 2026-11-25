"""LangChain compatibility helpers for DeepAgents runtime."""

from __future__ import annotations

from contextlib import suppress
from collections.abc import AsyncIterator, Callable, Mapping
from typing import Any

from swarmline.runtime.types import Message, RuntimeErrorData, RuntimeEvent


def build_cancelled_event() -> RuntimeEvent:
    """Canonical cancelled error event (mirrors thin runtime semantics)."""
    return RuntimeEvent.error(
        RuntimeErrorData(
            kind="cancelled",
            message="Operation cancelled",
            recoverable=False,
        )
    )


def extract_usage_metadata(output: Any) -> dict[str, int] | None:
    """Extract token usage from an ``on_chat_model_end`` payload output.

    Handles the astream_events v2 shape (AIMessage/AIMessageChunk carrying a
    ``usage_metadata`` dict), plain dict payloads with a ``usage_metadata``
    key, and LLMResult-like objects whose generations carry messages with
    ``usage_metadata``.
    """
    candidates: list[Any] = [getattr(output, "usage_metadata", None)]
    if isinstance(output, Mapping):
        candidates.append(output.get("usage_metadata"))
    generations = getattr(output, "generations", None)
    if isinstance(generations, list):
        for gen_group in generations:
            items = gen_group if isinstance(gen_group, list) else [gen_group]
            for gen in items:
                message = getattr(gen, "message", None)
                candidates.append(getattr(message, "usage_metadata", None))
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        try:
            return {
                "input_tokens": int(candidate.get("input_tokens", 0) or 0),
                "output_tokens": int(candidate.get("output_tokens", 0) or 0),
            }
        except (TypeError, ValueError):
            continue
    return None


def accumulate_usage(usage_totals: dict[str, int], output: Any) -> None:
    """Add usage from one ``on_chat_model_end`` output into running totals."""
    usage = extract_usage_metadata(output)
    if usage is None:
        return
    usage_totals["input_tokens"] = (
        usage_totals.get("input_tokens", 0) + usage["input_tokens"]
    )
    usage_totals["output_tokens"] = (
        usage_totals.get("output_tokens", 0) + usage["output_tokens"]
    )
    usage_totals["native_calls"] = usage_totals.get("native_calls", 0) + 1


def check_langchain_available() -> RuntimeErrorData | None:
    """Check langchain available."""
    try:
        import deepagents  # type: ignore[import-not-found] # noqa: F401
        import langchain_core  # noqa: F401

        return None
    except ImportError:
        return RuntimeErrorData(
            kind="dependency_missing",
            message=(
                "deepagents и/или langchain-core не установлены. "
                "Установите: pip install swarmline[deepagents]"
            ),
            recoverable=False,
        )


def build_langchain_messages(
    messages: list[Message],
    system_prompt: str,
    *,
    include_system_prompt: bool = True,
) -> list[Any]:
    """Build langchain messages."""
    from langchain_core.messages import (
        AIMessage,
        HumanMessage,
        SystemMessage,
        ToolMessage,
    )

    lc_messages: list[Any] = []
    if include_system_prompt:
        lc_messages.append(SystemMessage(content=system_prompt))
    for msg in messages:
        if msg.role == "user":
            lc_messages.append(HumanMessage(content=msg.content))
        elif msg.role == "assistant":
            ai_kwargs: dict[str, Any] = {"content": msg.content}
            if msg.tool_calls is not None:
                ai_kwargs["tool_calls"] = msg.tool_calls
            if msg.name is not None:
                ai_kwargs["name"] = msg.name
            lc_messages.append(AIMessage(**ai_kwargs))
        elif msg.role == "tool":
            tool_call_id = ""
            if isinstance(msg.metadata, dict):
                raw_id = msg.metadata.get("tool_call_id") or msg.metadata.get(
                    "correlation_id"
                )
                if raw_id is not None:
                    tool_call_id = str(raw_id)
            if not tool_call_id:
                tool_call_id = msg.name or "tool"
            lc_messages.append(
                ToolMessage(
                    content=msg.content,
                    name=msg.name,
                    tool_call_id=tool_call_id,
                )
            )
        elif msg.role == "system":
            lc_messages.append(SystemMessage(content=msg.content))
    return lc_messages


async def stream_langchain_runtime_events(
    *,
    runnable: Any,
    lc_messages: list[Any],
    cancel_check: Callable[[], bool] | None = None,
    usage_totals: dict[str, int] | None = None,
) -> AsyncIterator[RuntimeEvent]:
    """Stream langchain runtime events."""
    tool_correlation: dict[str, str] = {}

    if cancel_check is not None and cancel_check():
        yield build_cancelled_event()
        return

    stream = runnable.astream_events(lc_messages, version="v2")
    try:
        async for event in stream:
            if cancel_check is not None and cancel_check():
                yield build_cancelled_event()
                return

            kind = event.get("event", "")

            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    content = chunk.content
                    if isinstance(content, str) and content:
                        yield RuntimeEvent.assistant_delta(content)

            elif kind == "on_chat_model_end":
                if usage_totals is not None:
                    accumulate_usage(usage_totals, event.get("data", {}).get("output"))

            elif kind == "on_tool_start":
                tool_name = event.get("name", "")
                tool_input = event.get("data", {}).get("input", {})
                run_id = event.get("run_id", "")
                started_event = RuntimeEvent.tool_call_started(
                    name=tool_name,
                    args=tool_input if isinstance(tool_input, dict) else {},
                )
                correlation_id = started_event.data.get("correlation_id", "")
                if run_id:
                    tool_correlation[run_id] = correlation_id
                yield started_event

            elif kind == "on_tool_end":
                tool_name = event.get("name", "")
                run_id = event.get("run_id", "")
                correlation_id = tool_correlation.pop(run_id, run_id[:8])
                output = event.get("data", {}).get("output", "")
                result_str = str(output) if output else ""
                yield RuntimeEvent.tool_call_finished(
                    name=tool_name,
                    correlation_id=correlation_id,
                    result_summary=result_str[:500],
                )
    finally:
        # Breaking out of `async for` (cancel path) does not close the inner
        # async generator — close it explicitly so the provider HTTP stream
        # is released deterministically instead of at GC.
        aclose = getattr(stream, "aclose", None)
        if aclose is not None:
            with suppress(Exception):
                await aclose()
