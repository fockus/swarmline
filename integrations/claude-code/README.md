# Swarmline Integration for Claude Code

Connect Swarmline's persistent memory, planning, and team coordination to Claude Code via MCP.

## Prerequisites

- Python 3.11+
- Claude Code CLI installed and working

```bash
pip install swarmline[code-agent]
```

Verify the entry point is available:

```bash
swarmline-mcp --help
```

## Configuration

Copy the example settings and merge with your existing Claude Code config:

```bash
# If you have no existing config:
cp settings.json.example ~/.claude/settings.json

# If you already have ~/.claude/settings.json, merge the "swarmline" key
# into your existing mcpServers block.
```

The `--mode auto` argument detects available API keys at startup. If `ANTHROPIC_API_KEY` is set, full mode activates (agent creation + querying). Otherwise, headless mode runs with zero LLM calls.

## Verification

```bash
# Start the server manually to confirm it launches:
swarmline-mcp --mode headless

# In another terminal, check the CLI:
swarmline status
```

If the server starts without errors, Claude Code will be able to connect to it.

## Usage

### Headless mode (default, no API key needed)

All memory, planning, and team tools work without any LLM calls:

- **Memory** -- store facts, messages, summaries per user/session
- **Plans** -- create, list, approve, update step-by-step plans
- **Team** -- register agents, create/claim tasks, coordinate work
- **Code execution** -- run code in a sandboxed environment

### Full mode (requires API key)

Set your API key in the `env` block of `settings.json`:

```json
{
  "mcpServers": {
    "swarmline": {
      "command": "swarmline-mcp",
      "args": ["--mode", "auto"],
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-..."
      }
    }
  }
}
```

Full mode adds agent creation and querying tools on top of all headless tools.

## Available Tools (20)

| Category | Tools |
|----------|-------|
| Memory | `memory_upsert_fact`, `memory_get_facts`, `memory_save_message`, `memory_get_messages`, `memory_save_summary`, `memory_get_summary` |
| Plans | `plan_create`, `plan_list`, `plan_get`, `plan_approve`, `plan_update_step` |
| Team | `team_register_agent`, `team_list_agents`, `team_create_task`, `team_list_tasks`, `team_claim_task` |
| Code | `exec_code` |
| Agents (full mode) | `agent_create`, `agent_list`, `agent_query` |

## Troubleshooting

**`swarmline-mcp: command not found`** -- The package entry point is not on PATH. Run `pip show swarmline` to find the install location, then ensure its `bin/` or `Scripts/` directory is on PATH. Alternatively, use the module form: set `"command"` to `"python"` and `"args"` to `["-m", "swarmline.mcp", "--mode", "auto"]`.

**`ImportError: fastmcp`** -- The `[code-agent]` extra was not installed. Run `pip install swarmline[code-agent]`.

**Logs polluting stdout** -- Swarmline uses structlog and writes all logs to stderr. MCP communication happens on stdout. If you see log noise, ensure your terminal is not merging streams.

**Server starts but tools not visible** -- Restart Claude Code after changing `settings.json`. The MCP connection is established at startup.
