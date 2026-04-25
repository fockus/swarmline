"""Map PI bridge JSON events to Swarmline RuntimeEvent objects."""

from __future__ import annotations

from typing import Any

from swarmline.runtime.types import Message, RuntimeErrorData, RuntimeEvent, TurnMetrics


def map_pi_bridge_event(data: dict[str, Any]) -> RuntimeEvent | None:
    """Convert a normalized bridge event into a RuntimeEvent."""
    event_type = data.get("type")
    if event_type == "assistant_delta":
        text = str(data.get("text", ""))
        return RuntimeEvent.assistant_delta(text) if text else None
    if event_type == "thinking_delta":
        text = str(data.get("text", ""))
        return RuntimeEvent.thinking_delta(text) if text else None
    if event_type == "status":
        return RuntimeEvent.status(str(data.get("text", "")))
    if event_type == "tool_call_started":
        return RuntimeEvent.tool_call_started(
            name=str(data.get("name", "")),
            args=_ensure_dict(data.get("args")),
            correlation_id=_optional_str(data.get("correlation_id")),
        )
    if event_type == "tool_call_finished":
        return RuntimeEvent.tool_call_finished(
            name=str(data.get("name", "")),
            correlation_id=str(data.get("correlation_id", "")),
            ok=bool(data.get("ok", True)),
            result_summary=str(data.get("result_summary", "")),
        )
    if event_type == "final":
        return RuntimeEvent.final(
            text=str(data.get("text", "")),
            new_messages=_extract_messages(data.get("new_messages")),
            metrics=_extract_metrics(data),
            session_id=_optional_str(data.get("session_id")),
            total_cost_usd=_extract_cost(data),
            usage=_ensure_optional_dict(data.get("usage")),
            native_metadata={
                **_ensure_dict(data.get("native_metadata")),
                "runtime_name": "pi_sdk",
            },
        )
    if event_type == "error":
        return RuntimeEvent.error(
            RuntimeErrorData(
                kind=str(data.get("kind") or "runtime_crash"),
                message=str(data.get("message") or "PI SDK runtime error"),
                recoverable=bool(data.get("recoverable", False)),
                details=_ensure_dict(data.get("details")),
            )
        )
    return None


def _ensure_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _ensure_optional_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _optional_str(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _extract_cost(data: dict[str, Any]) -> float | None:
    value = data.get("total_cost_usd") or data.get("cost")
    if isinstance(value, int | float):
        return float(value)
    return None


def _extract_metrics(data: dict[str, Any]) -> TurnMetrics | None:
    metrics = data.get("metrics")
    if not isinstance(metrics, dict):
        return None
    return TurnMetrics(
        tokens_in=_int_or_zero(metrics.get("input_tokens")),
        tokens_out=_int_or_zero(metrics.get("output_tokens")),
        tool_calls_count=_int_or_zero(metrics.get("tool_calls_count")),
        model=_optional_str(metrics.get("model")) or "",
    )


def _int_or_zero(value: Any) -> int:
    return int(value) if isinstance(value, int | float) else 0


def _extract_messages(value: Any) -> list[Message]:
    messages: list[Message] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, Message):
            messages.append(item)
            continue
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        if role not in {"user", "assistant", "system", "tool"}:
            continue
        messages.append(
            Message(
                role=str(role),
                content=str(item.get("content", "")),
                name=_optional_str(item.get("name")),
                metadata=_ensure_dict(item.get("metadata")),
            )
        )
    return messages
