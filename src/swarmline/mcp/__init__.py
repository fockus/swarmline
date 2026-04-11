"""Swarmline MCP Server -- expose agent framework as MCP tools.

Two modes:
- headless (default): memory, plans, team coordination, code execution (0 LLM calls)
- full (opt-in): + agent creation/querying (requires API key)

Usage:
    swarmline-mcp              # headless mode (auto-detect)
    swarmline-mcp full         # full mode (needs ANTHROPIC_API_KEY or OPENAI_API_KEY)
    python -m swarmline.mcp    # alternative

Configuration for Claude Code (~/.claude/settings.json):
    {"mcpServers": {"swarmline": {"command": "swarmline-mcp"}}}

Configuration for Codex CLI (~/.codex/config.toml):
    [mcp_servers.swarmline]
    command = "swarmline-mcp"
"""

from swarmline.mcp._server import create_server, main
from swarmline.mcp._session import StatefulSession

__all__ = ["create_server", "main", "StatefulSession"]
