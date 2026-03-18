"""NDJSON parsers for CLI Agent Runtime."""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

from cognitia.runtime.types import RuntimeEvent


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
