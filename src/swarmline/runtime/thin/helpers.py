"""Shared helpers for strategy functions ThinRuntime."""

from __future__ import annotations

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
        d: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.name:
            d["name"] = m.name
        if m.content_blocks is not None:
            d["content_blocks"] = [b.to_dict() for b in m.content_blocks]
        result.append(d)
    return result


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
