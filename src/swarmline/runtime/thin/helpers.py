"""Shared helpers for strategy functions ThinRuntime."""

from __future__ import annotations

import json
import time
from typing import Any

from swarmline.runtime.types import (
    Message,
    RuntimeConfig,
    TurnMetrics,
)


def _messages_to_lm(messages: list[Message]) -> list[dict[str, Any]]:
    """Messages to lm."""
    result: list[dict[str, Any]] = []
    for m in messages:
        d = _message_to_lm(m)
        if m.name:
            d["name"] = m.name
        if m.content_blocks is not None:
            d["content_blocks"] = [b.to_dict() for b in m.content_blocks]
        result.append(d)
    return result


def _message_to_lm(message: Message) -> dict[str, Any]:
    content = message.content
    role = message.role

    if message.tool_calls:
        rendered_calls = "\n".join(
            _render_tool_call(call)
            for call in message.tool_calls
            if isinstance(call, dict)
        )
        prefix = "Tool calls requested:"
        content = f"{content}\n{prefix}\n{rendered_calls}".strip()

    tool_call_name = None
    if isinstance(message.metadata, dict):
        raw_tool_call = message.metadata.get("tool_call")
        if isinstance(raw_tool_call, str) and raw_tool_call:
            tool_call_name = raw_tool_call
    if tool_call_name:
        content = f"{content}\nTool call requested: {tool_call_name}".strip()

    if role == "tool":
        role = "user"
        tool_name = message.name or tool_call_name or "tool"
        content = f"Tool result from {tool_name}: {content}"

    return {"role": role, "content": content}


def _json_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def _render_tool_call(call: dict[str, Any]) -> str:
    args = call.get("args", call.get("arguments", {}))
    return (
        f"- {call.get('name', '<unknown>')} "
        f"id={call.get('id', '<none>')} "
        f"args={_json_text(args)}"
    )


def _build_metrics(
    start_time: float,
    config: RuntimeConfig,
    iterations: int = 0,
    tool_calls: int = 0,
    tokens_in: int = 0,
    tokens_out: int = 0,
) -> TurnMetrics:
    """Build metrics."""
    return TurnMetrics(
        latency_ms=int((time.monotonic() - start_time) * 1000),
        iterations=iterations,
        tool_calls_count=tool_calls,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        model=config.model,
    )


def _should_buffer_postprocessing(config: RuntimeConfig) -> bool:
    """Should buffer postprocessing."""
    return bool(
        config.output_guardrails
        or config.output_type is not None
        or config.retry_policy is not None
        or config.thinking is not None
    )
