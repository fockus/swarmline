"""NDJSON parsers for CLI Agent Runtime."""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

from swarmline.runtime.types import Message, RuntimeErrorData, RuntimeEvent


@runtime_checkable
class NdjsonParser(Protocol):
    """Parse a single NDJSON line into a RuntimeEvent."""

    def parse_line(self, line: str) -> RuntimeEvent | None:
        """Parse one NDJSON line. Returns None for unparseable/unknown lines."""
        ...  # pragma: no cover


class ClaudeNdjsonParser:
    """Parse Claude Code stream-JSON NDJSON output into RuntimeEvents.

  Supported event mappings:
  - assistant + text content -> RuntimeEvent.assistant_delta
  - assistant + tool_use content -> RuntimeEvent.tool_call_started
  - result -> RuntimeEvent.final
  - invalid JSON / unknown type -> None
  """

    def parse_line(self, line: str) -> RuntimeEvent | None:
        """Parse a Claude Code NDJSON line."""
        if not line.strip():
            return None

        try:
            data: dict[str, Any] = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return None

        event_type = data.get("type")

        if event_type == "assistant":
            return self._parse_assistant(data)
        if event_type == "result":
            return self._parse_result(data)

        return None

    def _parse_assistant(self, data: dict[str, Any]) -> RuntimeEvent | None:
        """Parse assistant message with content blocks."""
        message = data.get("message", {})
        content_blocks: list[dict[str, Any]] = message.get("content", [])
        if not content_blocks:
            return None

        block = content_blocks[0]
        block_type = block.get("type")

        if block_type == "text":
            return RuntimeEvent.assistant_delta(block.get("text", ""))

        if block_type == "tool_use":
            return RuntimeEvent.tool_call_started(
                name=block.get("name", ""),
                args=block.get("input", {}),
            )

        return None

    def _parse_result(self, data: dict[str, Any]) -> RuntimeEvent | None:
        """Parse result event into final RuntimeEvent."""
        result_text = data.get("result", "")
        return RuntimeEvent.final(text=str(result_text))


class GenericNdjsonParser:
    """Fallback parser: wraps raw JSON as RuntimeEvent status data.

  Any valid JSON object is passed through as a status event.
  Invalid JSON returns None.
  """

    def parse_line(self, line: str) -> RuntimeEvent | None:
        """Parse a generic NDJSON line."""
        if not line.strip():
            return None

        try:
            data: dict[str, Any] = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return None

        if not isinstance(data, dict):
            return None

        return RuntimeEvent(type="status", data=data)


class PiRpcParser:
    """Parse PI CLI RPC JSONL output into RuntimeEvents."""

    def parse_line(self, line: str) -> RuntimeEvent | None:
        """Parse a PI RPC JSONL line."""
        if not line.strip():
            return None

        try:
            data: dict[str, Any] = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return None

        if not isinstance(data, dict):
            return None

        event_type = data.get("type")
        if event_type == "message_update":
            return self._parse_message_update(data)
        if event_type == "tool_execution_start":
            return RuntimeEvent.tool_call_started(
                name=str(data.get("toolName", "")),
                args=_ensure_dict(data.get("args")),
                correlation_id=str(data.get("toolCallId", "")),
            )
        if event_type == "tool_execution_update":
            return RuntimeEvent.status(_summarize_tool_result(data.get("partialResult")))
        if event_type == "tool_execution_end":
            return RuntimeEvent.tool_call_finished(
                name=str(data.get("toolName", "")),
                correlation_id=str(data.get("toolCallId", "")),
                ok=not bool(data.get("isError", False)),
                result_summary=_summarize_tool_result(data.get("result")),
            )
        if event_type == "agent_start":
            return RuntimeEvent.status("PI agent started")
        if event_type == "agent_end":
            return RuntimeEvent.final(
                text=_extract_last_assistant_text(data.get("messages")),
                new_messages=_extract_messages(data.get("messages")),
                session_id=_extract_session_id(data),
                usage=_extract_usage(data),
                total_cost_usd=_extract_cost(data),
                native_metadata={"runtime_name": "cli", "cli_preset": "pi"},
            )
        if event_type == "turn_start":
            return RuntimeEvent.status("PI turn started")
        if event_type == "turn_end":
            return RuntimeEvent.status("PI turn completed")
        if event_type == "compaction_start":
            return RuntimeEvent.status("PI compaction started")
        if event_type == "compaction_end":
            return RuntimeEvent.status("PI compaction completed")
        if event_type == "auto_retry_start":
            return RuntimeEvent.status("PI auto retry started")
        if event_type == "auto_retry_end":
            return RuntimeEvent.status("PI auto retry completed")
        if event_type == "queue_update":
            return RuntimeEvent.status("PI queue updated")
        if event_type == "extension_ui_request":
            return RuntimeEvent.user_input_requested(
                prompt=str(data.get("title") or data.get("message") or data.get("method") or ""),
                interrupt_id=str(data.get("id", "")),
            )
        if event_type == "extension_error":
            return RuntimeEvent.error(
                RuntimeErrorData(
                    kind="runtime_crash",
                    message=str(data.get("error") or "PI extension error"),
                    recoverable=False,
                )
            )
        if event_type == "response" and data.get("success") is False:
            return RuntimeEvent.error(
                RuntimeErrorData(
                    kind="runtime_crash",
                    message=str(data.get("error") or "PI RPC command failed"),
                    recoverable=False,
                    details={"command": data.get("command")},
                )
            )
        return None

    @staticmethod
    def _parse_message_update(data: dict[str, Any]) -> RuntimeEvent | None:
        assistant_event = _ensure_dict(data.get("assistantMessageEvent"))
        kind = assistant_event.get("type")
        if kind == "text_delta":
            text = str(assistant_event.get("delta", ""))
            return RuntimeEvent.assistant_delta(text) if text else None
        if kind == "thinking_delta":
            text = str(assistant_event.get("delta", ""))
            return RuntimeEvent.thinking_delta(text) if text else None
        if kind == "toolcall_start":
            tool_call = _ensure_dict(assistant_event.get("toolCall"))
            return RuntimeEvent.tool_call_started(
                name=str(tool_call.get("name", "")),
                args=_ensure_dict(tool_call.get("args")),
                correlation_id=str(tool_call.get("id", "")),
            )
        if kind == "toolcall_end":
            tool_call = _ensure_dict(assistant_event.get("toolCall"))
            return RuntimeEvent.tool_call_finished(
                name=str(tool_call.get("name", "")),
                correlation_id=str(tool_call.get("id", "")),
                ok=True,
                result_summary=str(tool_call.get("result", "")),
            )
        if kind == "error":
            return RuntimeEvent.error(
                RuntimeErrorData(
                    kind="runtime_crash",
                    message=str(assistant_event.get("reason") or "PI message error"),
                    recoverable=False,
                )
            )
        return None


def _ensure_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _extract_last_assistant_text(messages: Any) -> str:
    for message in reversed(messages if isinstance(messages, list) else []):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
    return ""


def _extract_messages(messages: Any) -> list[Message]:
    result: list[Message] = []
    for message in messages if isinstance(messages, list) else []:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role not in {"user", "assistant", "tool", "system"}:
            continue
        content = message.get("content", "")
        if isinstance(content, list):
            content = "".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        result.append(Message(role=str(role), content=str(content)))
    return result


def _extract_session_id(data: dict[str, Any]) -> str | None:
    value = data.get("sessionId") or data.get("session_id")
    return str(value) if value else None


def _extract_usage(data: dict[str, Any]) -> dict[str, Any] | None:
    usage = data.get("usage") or data.get("tokens")
    return usage if isinstance(usage, dict) else None


def _extract_cost(data: dict[str, Any]) -> float | None:
    value = data.get("cost") or data.get("totalCostUsd") or data.get("total_cost_usd")
    if isinstance(value, int | float):
        return float(value)
    return None


def _summarize_tool_result(value: Any) -> str:
    if isinstance(value, str):
        return value[:500]
    if isinstance(value, dict):
        content = value.get("content")
        if isinstance(content, list):
            text = "\n".join(
                str(item.get("text", ""))
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            )
            if text:
                return text[:500]
        return json.dumps(value, ensure_ascii=False, default=str)[:500]
    if value is None:
        return ""
    return str(value)[:500]
