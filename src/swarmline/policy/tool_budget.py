"""ToolBudget - tool call limit per turn (architecture section 6.3).

Controls cost and latency:
- max_tool_calls: overall call limit per turn (default 8)
- max_mcp_calls: MCP call limit per turn (default 6)
- timeout_per_call_ms: timeout for a single MCP call (default 30s)
"""

from __future__ import annotations


class ToolBudget:
    """Counter and limiter for tool calls within one turn."""

    def __init__(
        self,
        max_tool_calls: int = 8,
        max_mcp_calls: int = 6,
        timeout_per_call_ms: int = 30_000,
    ) -> None:
        self._max_total = max_tool_calls
        self._max_mcp = max_mcp_calls
        self._timeout_ms = timeout_per_call_ms
        self._total: int = 0
        self._mcp: int = 0

    @property
    def total_calls(self) -> int:
        """Total number of calls in the turn."""
        return self._total

    @property
    def mcp_calls(self) -> int:
        """Number of MCP calls in the turn."""
        return self._mcp

    def record_call(self, is_mcp: bool = False) -> None:
        """Record a tool call."""
        self._total += 1
        if is_mcp:
            self._mcp += 1

    def can_call(self, is_mcp: bool = False) -> bool:
        """Check whether another call is allowed."""
        if self._total >= self._max_total:
            return False
        return not (is_mcp and self._mcp >= self._max_mcp)

    def is_exhausted(self) -> bool:
        """Return whether the budget is fully exhausted (no MCP or local calls left)."""
        return self._total >= self._max_total

    @property
    def timeout_per_call_ms(self) -> int:
        """Timeout for a single MCP call in ms (§6.3)."""
        return self._timeout_ms

    def reset(self) -> None:
        """Reset counters (start of a new turn)."""
        self._total = 0
        self._mcp = 0
