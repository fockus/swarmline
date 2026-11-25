"""Message filtering utilities for context assembly (extracted from builder.py
to keep the builder module within the ≤400-line file-size threshold).

Filters out error/noise messages (MCP errors, timeouts, empty content) so
they do not pollute the ``last_messages`` layer of the assembled system
prompt.
"""

from __future__ import annotations

# Markers for error messages that do not provide useful context to the model.
_ERROR_MARKERS = (
    '{"error"',
    "MCP error",
    "Таймаут при вызове",
    "HTTP ошибка MCP",
    "Runtime не ответил вовремя",
    "Не удалось получить ответ",
    "SDK subprocess упал",
    "Ошибка SDK",
    "Client error",
)


def is_error_message(content: str) -> bool:
    """Check whether a message is an error/noise that should not be added to context."""
    if not content:
        return True
    # Quick check by the first characters
    if content.startswith(('{"error"', "⚠️")):
        return True
    # Check markers (within the first 200 characters for speed)
    prefix = content[:200]
    return any(marker in prefix for marker in _ERROR_MARKERS)
