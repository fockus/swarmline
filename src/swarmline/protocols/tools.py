"""Tool protocols -- tool ID encoding and local tool resolution."""

from __future__ import annotations

from typing import Any, Protocol


class ToolIdCodec(Protocol):
    """Port: tool name normalization."""

    def matches(self, tool_name: str, server_id: str) -> bool: ...

    def encode(self, server_id: str, tool_name: str) -> str: ...

    def extract_server(self, tool_name: str) -> str | None: ...


class LocalToolResolver(Protocol):
    """Port: local tool resolver (ISP, 2 methods).

    Application implements this Protocol so the library can obtain
    a callable by tool_name. Library has no knowledge of concrete tools.
    """

    def resolve(self, tool_name: str) -> Any | None:
        """Get callable for a local tool by name.

        Returns:
            Callable or None if tool not found.
        """
        ...

    def list_tools(self) -> list[str]:
        """List available local tools."""
        ...
