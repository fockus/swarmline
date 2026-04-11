"""Map OpenAI Agents SDK streaming events to Swarmline RuntimeEvent."""

from __future__ import annotations

from typing import Any

from swarmline.runtime.types import RuntimeErrorData, RuntimeEvent


def map_stream_event(event: Any) -> RuntimeEvent | None:
    """Convert an OpenAI Agents SDK stream event to RuntimeEvent.

    Event types from Runner.run_streamed():
    - RunItemStreamEvent (name=message_output_created|tool_called|tool_output|...)
    - AgentUpdatedStreamEvent
    - RawResponsesStreamEvent

    Returns None for events that should be skipped.
    """
    event_type = getattr(event, "type", "")

    if event_type == "run_item_stream_event":
        return _map_run_item_event(event)

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
        return None

    return None


def _map_run_item_event(event: Any) -> RuntimeEvent | None:
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

    if name == "tool_called":
        raw_item = getattr(item, "raw_item", None)
        tool_name = getattr(raw_item, "name", "") if raw_item else ""
        tool_args = getattr(raw_item, "arguments", "{}") if raw_item else "{}"
        call_id = getattr(raw_item, "call_id", "") if raw_item else ""
        return RuntimeEvent.tool_call_started(
            name=tool_name,
            args={"raw_arguments": tool_args},
            correlation_id=call_id,
        )

    if name == "tool_output":
        raw_item = getattr(item, "raw_item", None)
        output = getattr(raw_item, "output", "") if raw_item else ""
        call_id = getattr(raw_item, "call_id", "") if raw_item else ""
        return RuntimeEvent.tool_call_finished(
            name="",
            correlation_id=call_id,
            ok=True,
            result_summary=str(output)[:500],
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


def map_run_error(error: Exception) -> RuntimeEvent:
    """Convert an exception from Runner into a RuntimeEvent error."""
    return RuntimeEvent.error(
        RuntimeErrorData(
            kind="runtime_crash",
            message=f"OpenAI Agents SDK error: {error}",
            recoverable=False,
        )
    )
