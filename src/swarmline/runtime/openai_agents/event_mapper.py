"""Map OpenAI Agents SDK streaming events to Swarmline RuntimeEvent."""

from __future__ import annotations

import json
from typing import Any

from swarmline.observability.redaction import redact_secrets
from swarmline.runtime.types import RuntimeErrorData, RuntimeEvent

_RESULT_SUMMARY_LIMIT = 500


class StreamEventMapper:
    """Stateful mapper for one Runner.run_streamed() event stream.

    Tracks tool call_id -> tool name so that ``tool_call_finished`` carries
    the tool name, and inspects tool output for the bridge error contract
    (``{"error": ...}`` JSON) so that ``ok`` reflects the real outcome.
    """

    def __init__(self) -> None:
        self._tool_names_by_call_id: dict[str, str] = {}

    def map_event(self, event: Any) -> RuntimeEvent | None:
        """Convert an OpenAI Agents SDK stream event to RuntimeEvent.

        Event types from Runner.run_streamed():
        - RunItemStreamEvent (name=message_output_created|tool_called|tool_output|...)
        - AgentUpdatedStreamEvent
        - RawResponsesStreamEvent

        Returns None for events that should be skipped.
        """
        event_type = getattr(event, "type", "")

        if event_type == "run_item_stream_event":
            return self._map_run_item_event(event)

        if event_type == "agent_updated_stream_event":
            agent = getattr(event, "new_agent", None)
            agent_name = getattr(agent, "name", "unknown") if agent else "unknown"
            return RuntimeEvent.status(f"agent: {agent_name}")

        if event_type == "raw_response_stream_event":
            data = getattr(event, "data", None)
            if data is not None:
                delta_type = getattr(data, "type", "")
                if delta_type == "response.output_text.delta":
                    text = getattr(data, "delta", "")
                    if text:
                        return RuntimeEvent.assistant_delta(text)
                if delta_type == "response.reasoning_summary_text.delta":
                    reasoning = getattr(data, "delta", "")
                    if reasoning:
                        return RuntimeEvent.thinking_delta(reasoning)
            return None

        return None

    def _map_run_item_event(self, event: Any) -> RuntimeEvent | None:
        """Map RunItemStreamEvent based on its name field."""
        name = getattr(event, "name", "")
        item = getattr(event, "item", None)

        if name == "message_output_created":
            raw_item = getattr(item, "raw_item", None)
            if raw_item is not None:
                text = getattr(raw_item, "text", "")
                if text:
                    return RuntimeEvent.assistant_delta(text)
            return None

        if name == "reasoning_item_created":
            raw_item = getattr(item, "raw_item", None)
            reasoning = _extract_reasoning_text(raw_item)
            if reasoning:
                return RuntimeEvent.thinking_delta(reasoning)
            return None

        if name == "tool_called":
            raw_item = getattr(item, "raw_item", None)
            tool_name = getattr(raw_item, "name", "") if raw_item else ""
            tool_args = getattr(raw_item, "arguments", "{}") if raw_item else "{}"
            call_id = getattr(raw_item, "call_id", "") if raw_item else ""
            if call_id and tool_name:
                self._tool_names_by_call_id[call_id] = tool_name
            return RuntimeEvent.tool_call_started(
                name=tool_name,
                args={"raw_arguments": tool_args},
                correlation_id=call_id,
            )

        if name == "tool_output":
            raw_item = getattr(item, "raw_item", None)
            output = _extract_tool_output(item, raw_item)
            call_id = _extract_call_id(raw_item)
            return RuntimeEvent.tool_call_finished(
                name=self._tool_names_by_call_id.pop(call_id, ""),
                correlation_id=call_id,
                ok=not _output_is_error(output),
                result_summary=str(output)[:_RESULT_SUMMARY_LIMIT],
            )

        if name == "handoff_requested":
            agent = getattr(item, "target_agent", None)
            target = getattr(agent, "name", "unknown") if agent else "unknown"
            return RuntimeEvent.status(f"handoff → {target}")

        if name == "handoff_occurred":
            agent = getattr(item, "target_agent", None)
            target = getattr(agent, "name", "unknown") if agent else "unknown"
            return RuntimeEvent.status(f"handoff complete → {target}")

        return None


def _extract_call_id(raw_item: Any) -> str:
    if raw_item is None:
        return ""
    if isinstance(raw_item, dict):
        return str(raw_item.get("call_id", "") or "")
    return getattr(raw_item, "call_id", "") or ""


def _extract_tool_output(item: Any, raw_item: Any) -> Any:
    output = getattr(item, "output", None)
    if output is not None:
        return output
    if isinstance(raw_item, dict):
        return raw_item.get("output", "")
    return getattr(raw_item, "output", "") if raw_item is not None else ""


def _extract_reasoning_text(raw_item: Any) -> str:
    """Extract reasoning summary text from a ResponseReasoningItem."""
    if raw_item is None:
        return ""
    summary = getattr(raw_item, "summary", None)
    if not summary:
        return ""
    parts: list[str] = []
    for entry in summary:
        text = getattr(entry, "text", None)
        if text is None and isinstance(entry, dict):
            text = entry.get("text")
        if text:
            parts.append(str(text))
    return "".join(parts)


def _output_is_error(output: Any) -> bool:
    """Detect the tool-bridge error contract: a JSON object with 'error'."""
    if not isinstance(output, str):
        return False
    stripped = output.strip()
    if not stripped.startswith("{"):
        return False
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return False
    return isinstance(parsed, dict) and "error" in parsed


def map_stream_event(event: Any) -> RuntimeEvent | None:
    """Stateless convenience wrapper around :class:`StreamEventMapper`.

    Tool names cannot be correlated across events without shared state;
    prefer a per-run ``StreamEventMapper`` instance.
    """
    return StreamEventMapper().map_event(event)


def map_run_error(error: Exception) -> RuntimeEvent:
    """Convert an exception from Runner into a RuntimeEvent error."""
    redacted = redact_secrets(str(error))
    return RuntimeEvent.error(
        RuntimeErrorData(
            kind="runtime_crash",
            message=f"OpenAI Agents SDK error ({type(error).__name__}): {redacted}",
            recoverable=False,
        )
    )
