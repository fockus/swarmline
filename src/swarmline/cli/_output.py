"""Output formatting for CLI -- JSON for pipes, text for terminals."""

from __future__ import annotations

import json
import sys
from typing import Any


def format_output(data: dict[str, Any], fmt: str = "auto") -> str:
    """Format tool result for display.

    Args:
        data: Tool result dict with ``ok``, ``data``, and optionally ``error``.
        fmt: ``"json"`` forces JSON, ``"text"`` forces human-readable,
             ``"auto"`` picks JSON when stdout is piped, text otherwise.
    """
    if fmt == "json" or (fmt == "auto" and not sys.stdout.isatty()):
        return json.dumps(data, indent=2, default=str, ensure_ascii=False)

    if not data.get("ok", True):
        return f"Error: {data.get('error', 'Unknown error')}"

    result = data.get("data")
    if result is None:
        return "OK"
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        if not result:
            return "(empty)"
        return "\n".join(
            json.dumps(item, default=str, ensure_ascii=False)
            if isinstance(item, dict)
            else str(item)
            for item in result
        )
    if isinstance(result, dict):
        return json.dumps(result, indent=2, default=str, ensure_ascii=False)
    return str(result)
