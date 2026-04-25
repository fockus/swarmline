# Swarmline Integration for Codex CLI

Connect Swarmline's persistent memory, planning, and team coordination to OpenAI Codex CLI via MCP.

## Prerequisites

- Python 3.11+
- Codex CLI installed and working

```bash
pip install swarmline[code-agent]
```

Verify the entry point:

```bash
swarmline-mcp --help
```

## Configuration

Add the Swarmline MCP server to your Codex CLI config. Codex reads MCP configuration from its config file (typically `~/.codex/config.toml` or the project-level `.codex/config.toml`).

Copy the TOML block from `config.toml.example` into your config file:

```toml
[mcp.swarmline]
transport = "stdio"
command = "swarmline-mcp"
args = ["--mode", "auto"]
```

The `auto` mode detects API keys at startup. Without `ANTHROPIC_API_KEY`, only headless tools (memory, plans, team, code execution) are available. With the key set, agent creation and querying tools activate.

## Verification

```bash
# Test the server starts correctly:
swarmline-mcp --mode headless

# Check CLI status:
swarmline status
```

## Usage

### Headless mode (no API key)

Available tool categories (17 tools, zero LLM calls):

- **Memory** -- fact storage, message history, summaries
- **Plans** -- create, list, approve, update step-by-step plans
- **Team** -- agent registration, task creation and claiming
- **Code** -- sandboxed code execution

### Full mode

Export your API key before launching Codex, or set it in your shell profile:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Full mode adds 3 agent tools: `agent_create`, `agent_list`, `agent_query`.

## Troubleshooting

**`swarmline-mcp: command not found`** -- Ensure the Python scripts directory is on PATH. Alternative: set `command = "python"` and `args = ["-m", "swarmline.mcp", "--mode", "auto"]`.

**`ImportError: fastmcp`** -- Run `pip install swarmline[code-agent]` to install the required extra.

**Logs on stderr** -- Swarmline writes all structured logs to stderr. MCP protocol uses stdout. This is expected behavior.

**Tools not appearing** -- Restart Codex CLI after config changes. Verify the config path is correct for your Codex version.
