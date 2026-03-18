"""ToolIdCodec - normalization of tool names (architecture section 4.4).

Provides consistent handling of tool_name/server_id
regardless of hyphens, underscores, and mcp__ prefixes.
"""

from __future__ import annotations

# SDK separator between server and tool
_SEP = "__"
_MCP_PREFIX = "mcp"


class DefaultToolIdCodec:
    """Default ToolIdCodec implementation.

    SDK tool_name format: mcp__<server_id>__<tool_name>
    Separator: double underscore.
    server_id may contain hyphens (iss-price).
    """

    def matches(self, tool_name: str, server_id: str) -> bool:
        """Check whether tool_name belongs to the given server_id."""
        extracted = self.extract_server(tool_name)
        if extracted is None:
            return False
        return extracted == server_id

    def encode(self, server_id: str, tool_name: str) -> str:
        """Build the full tool name: mcp__<server_id>__<tool_name>."""
        return f"{_MCP_PREFIX}{_SEP}{server_id}{_SEP}{tool_name}"

    def extract_server(self, tool_name: str) -> str | None:
        """Extract server_id from a tool_name in the mcp__<server>__<tool> format.

        Supports server_id values with hyphens (iss-price):
        we split on '__' (double underscore), not on '_'.
        """
        if not tool_name.startswith(f"{_MCP_PREFIX}{_SEP}"):
            return None

        # Strip the "mcp__" prefix
        rest = tool_name[len(f"{_MCP_PREFIX}{_SEP}") :]

        # Find the next "__" separator between server and tool
        idx = rest.find(_SEP)
        if idx <= 0:
            return None

        return rest[:idx]
