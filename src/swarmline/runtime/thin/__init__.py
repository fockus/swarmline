"""Thin package."""

try:
    from swarmline.runtime.thin.mcp_client import McpClient
    from swarmline.runtime.thin.runtime import ThinRuntime
except ImportError:
    pass

__all__ = ["McpClient", "ThinRuntime"]
