"""Thin package."""

try:
    from cognitia.runtime.thin.mcp_client import McpClient
    from cognitia.runtime.thin.runtime import ThinRuntime
except ImportError:
    pass

__all__ = ["McpClient", "ThinRuntime"]
