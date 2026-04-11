# MCP Server

Swarmline exposes its agent infrastructure as an MCP (Model Context Protocol) server. Any MCP-compatible client -- Claude Code, Codex CLI, OpenCode, or custom applications -- can use Swarmline's memory, planning, team coordination, and code execution tools over STDIO transport.

## Installation

```bash
pip install swarmline[code-agent]
```

## Quick Start

```bash
# Auto-detect mode (uses full mode if API keys are found)
swarmline-mcp auto

# Headless only (no LLM calls, no API key needed)
swarmline-mcp headless

# Full mode (requires ANTHROPIC_API_KEY or OPENAI_API_KEY)
export ANTHROPIC_API_KEY=sk-ant-...
swarmline-mcp full
```

You can also start the server via the CLI:

```bash
swarmline mcp-serve --mode auto
```

Or as a Python module:

```bash
python -m swarmline.mcp auto
```

## Modes

| Mode | Description | API Key Required | Tools |
|------|-------------|-----------------|-------|
| `headless` | Memory, plans, team coordination, code execution | No | 17 |
| `full` | All headless tools + agent creation and querying | Yes | 20 |
| `auto` | Detects API keys in environment; chooses `full` if found, else `headless` | Depends | 17 or 20 |

## Available Tools

### Memory (6 tools)

| Tool | Description |
|------|-------------|
| `swarmline_memory_upsert_fact` | Store or update a key-value fact scoped by user and optional topic |
| `swarmline_memory_get_facts` | Retrieve all facts for a user, optionally filtered by topic |
| `swarmline_memory_save_message` | Save a conversation message (role + content) to history |
| `swarmline_memory_get_messages` | Get recent messages from a conversation with configurable limit |
| `swarmline_memory_save_summary` | Save a conversation summary with count of messages covered |
| `swarmline_memory_get_summary` | Retrieve the latest conversation summary for a user/topic pair |

### Plans (5 tools)

| Tool | Description |
|------|-------------|
| `swarmline_plan_create` | Create a plan with a goal and ordered steps |
| `swarmline_plan_get` | Load a plan by its ID |
| `swarmline_plan_list` | List all plans in a user/topic namespace |
| `swarmline_plan_approve` | Approve a draft plan for execution |
| `swarmline_plan_update_step` | Update a step's status (`in_progress`, `completed`, `failed`, `skipped`) with optional result |

### Team (5 tools)

| Tool | Description |
|------|-------------|
| `swarmline_team_register_agent` | Register an agent with id, name, role, and optional parent |
| `swarmline_team_list_agents` | List registered agents with optional role/status filters |
| `swarmline_team_create_task` | Create a task with id, title, priority, and optional assignee |
| `swarmline_team_claim_task` | Claim the highest-priority available task from the queue |
| `swarmline_team_list_tasks` | List tasks with optional status/priority/assignee filters |

### Code (1 tool)

| Tool | Description |
|------|-------------|
| `swarmline_exec_code` | Execute Python code in an isolated subprocess with configurable timeout (default 30s) |

### System (1 tool)

| Tool | Description |
|------|-------------|
| `swarmline_status` | Get server status: current mode, number of active agents |

### Agents (3 tools, full mode only)

These tools are only available when the server runs in `full` mode with a valid API key.

| Tool | Description |
|------|-------------|
| `swarmline_agent_create` | Create a new LLM-powered agent with system prompt, model alias, and runtime |
| `swarmline_agent_query` | Send a prompt to an existing agent and get its response |
| `swarmline_agent_list` | List all created agents with their configurations |

## Integration

### Claude Code

Add to `.claude/settings.json` (project-level) or `~/.claude/settings.json` (global):

```json
{
  "mcpServers": {
    "swarmline": {
      "command": "swarmline-mcp",
      "args": ["auto"]
    }
  }
}
```

### Codex CLI

Add to `codex.json` in your project root:

```json
{
  "mcpServers": {
    "swarmline": {
      "command": "swarmline-mcp",
      "args": ["auto"]
    }
  }
}
```

### Custom MCP Client

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    server = StdioServerParameters(command="swarmline-mcp", args=["auto"])
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # List available tools
            tools = await session.list_tools()
            print(f"Available: {[t.name for t in tools.tools]}")

            # Store a fact
            result = await session.call_tool(
                "swarmline_memory_upsert_fact",
                {"user_id": "alice", "key": "language", "value": "Python"},
            )
            print(result)

asyncio.run(main())
```

## Architecture

The server uses FastMCP with STDIO transport. All state is held in a `StatefulSession` object that persists across tool calls within a single server process. Memory uses an in-memory provider by default (no database setup required). Plans and team state are also in-memory and scoped to the server's lifetime.

Tool responses follow a uniform schema: `{"ok": true, "data": {...}}` on success and `{"ok": false, "error": "..."}` on failure.

## Troubleshooting

**"FastMCP is required" error on startup**
Install the MCP extra: `pip install swarmline[code-agent]`. The `fastmcp` package is an optional dependency.

**Agent tools not appearing**
The server is running in `headless` mode. Set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` in your environment and use `auto` or `full` mode.

**"Execution timed out" from exec_code**
The default timeout is 30 seconds. Pass a higher `timeout_seconds` value to the tool call, or break long-running code into smaller steps.

**Server exits immediately with no output**
The MCP server communicates over STDIO, not HTTP. It does not print anything to stdout on its own -- it waits for JSON-RPC messages from a client. Run it through an MCP client, not directly in a terminal.
