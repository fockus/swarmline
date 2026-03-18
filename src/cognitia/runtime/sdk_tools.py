"""Sdk Tools module."""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import (
    McpSdkServerConfig,
    SdkMcpTool,
    create_sdk_mcp_server,
    tool,
)


mcp_tool = tool


def create_mcp_server(
    name: str,
    version: str = "1.0.0",
    tools: list[SdkMcpTool[Any]] | None = None,
) -> McpSdkServerConfig:
    """Create mcp server."""
    return create_sdk_mcp_server(name=name, version=version, tools=tools)
