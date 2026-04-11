# Codex CLI Integration

Guide for using Swarmline's MCP server with OpenAI Codex CLI. This gives Codex persistent memory, structured planning, team coordination, and code execution tools.

## 1. Install Swarmline

```bash
pip install swarmline[code-agent]
```

Verify the entry point:

```bash
swarmline-mcp headless
```

The server starts and waits for JSON-RPC input over STDIO. Press `Ctrl+C` to stop.

## 2. Configure MCP Server

Add Swarmline to your `codex.json` in the project root:

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

If `swarmline-mcp` is in a virtual environment, use the full path:

```json
{
  "mcpServers": {
    "swarmline": {
      "command": "/path/to/venv/bin/swarmline-mcp",
      "args": ["auto"]
    }
  }
}
```

## 3. Set API Keys (Optional)

For full mode (agent creation and querying), export an API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
# or
export OPENAI_API_KEY=sk-...
```

Without an API key, the server runs in headless mode with 17 tools. With a key, it runs in full mode with 20 tools.

## 4. Available Tools

Once configured, Codex CLI can call any Swarmline tool. The most useful for Codex workflows:

**Memory** -- store and retrieve project facts:
- `swarmline_memory_upsert_fact` -- save a key-value pair
- `swarmline_memory_get_facts` -- retrieve stored facts

**Plans** -- track multi-step work:
- `swarmline_plan_create` -- create a plan with goal and steps
- `swarmline_plan_update_step` -- mark steps as completed/failed

**Code** -- run Python in isolation:
- `swarmline_exec_code` -- execute code with timeout

See [MCP Server](mcp-server.md) for the full tool reference.

## 5. Example Usage

Start Codex CLI in your project directory. The MCP server starts automatically.

Store a project convention:

> Remember that we use ruff for linting and mypy for type checking

Codex calls `swarmline_memory_upsert_fact` to persist these facts.

Create a work plan:

> Plan the API refactoring: 1) Extract interfaces 2) Write tests 3) Implement adapters

Codex calls `swarmline_plan_create` and tracks progress through `swarmline_plan_update_step`.

## Troubleshooting

**Tools not showing up**
Make sure `codex.json` is in the project root (not a subdirectory). Restart Codex CLI after editing the config.

**"FastMCP is required" error**
Install the full extra: `pip install swarmline[code-agent]`.

**State lost between sessions**
The MCP server stores state in memory for the duration of the process. Each Codex CLI session starts a fresh server. For cross-session persistence, use Swarmline's SQLite or PostgreSQL memory backends via the Python API.
