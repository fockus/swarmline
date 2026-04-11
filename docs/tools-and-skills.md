# Tools & Skills

Swarmline provides two mechanisms for giving agents capabilities: **tools** (code-defined) and **skills** (declarative MCP).

## @tool Decorator

Define tools as async Python functions with automatic JSON Schema inference:

```python
from swarmline import tool

@tool(name="lookup_user", description="Look up user by email")
async def lookup_user(email: str) -> str:
    # Auto-inferred schema: {"type": "object", "properties": {"email": {"type": "string"}}, "required": ["email"]}
    user = await db.find_by_email(email)
    return f"Found: {user.name}" if user else "Not found"
```

### Type mapping

| Python | JSON Schema |
|--------|-------------|
| `str` | `"string"` |
| `int` | `"integer"` |
| `float` | `"number"` |
| `bool` | `"boolean"` |
| `T \| None = None` | not in `required` |

### Using tools with Agent

```python
from swarmline import Agent, AgentConfig

agent = Agent(AgentConfig(
    runtime="thin",
    tools=(lookup_user, another_tool),
))
```

### Handler contract

The `@tool` decorator handles the conversion between your natural Python function signature and the MCP protocol format automatically:

- Your handler: `async def fn(a: int, b: str) -> str`
- SDK expects: `handler({"a": 1, "b": "hello"}) -> {"content": [{"type": "text", "text": "result"}]}`

Swarmline's `_adapt_handler` bridges this gap transparently. If your handler raises an exception, it's caught and returned as an error in MCP format.

## MCP Skills

Skills are declarative MCP server connections with tool allowlists and agent instructions. Swarmline supports **two formats**:

### Format 1: Swarmline Native (skill.yaml + INSTRUCTION.md)

```yaml
# skills/finuslugi/skill.yaml
id: finuslugi
title: "Banking Products API"
description: "Search bank deposits and credits"
mcp:
  servers:
    - id: finuslugi-server
      transport: url
      url: "https://api.example.com/mcp"
tools:
  include:
    - mcp__finuslugi__get_bank_deposits
    - mcp__finuslugi__get_bank_credits
when:
  intents: [deposits, credits]
```

```markdown
# skills/finuslugi/INSTRUCTION.md
Use `get_bank_deposits` to search for deposit products.
Always specify amount and term in months.
```

**YAML fields:**

| Field | Required | Description |
|-------|----------|-------------|
| `id` | no | Skill ID (defaults to directory name) |
| `title` | no | Display name (defaults to id) |
| `description` | no | Short description for discovery |
| `mcp.servers` | no | MCP server connections |
| `tools.include` | no | Tool allowlist |
| `local_tools` | no | Local tool IDs |
| `when.intents` | no | Keywords for role-based activation |
| `instruction` | no | Custom path to instruction file |

### Format 2: Claude Code Compatible (SKILL.md)

Single file with YAML frontmatter — compatible with Claude Code skills:

```markdown
# skills/my-skill/SKILL.md
---
name: my-skill
description: "Short description for matching"
allowed-tools:
  - Bash
  - Read
  - Write
---

# My Skill Instructions

Use these tools to accomplish the task...
```

**Frontmatter fields:**

| Field | Maps to | Description |
|-------|---------|-------------|
| `name` | `skill_id` | Skill identifier (defaults to dir name) |
| `description` | `description` | Short description |
| `allowed-tools` | `tool_include` | Tool allowlist |
| `mcp-servers` | `mcp_servers` | MCP servers (Swarmline extension) |
| `intents` | `intents` | Activation keywords (Swarmline extension) |
| `local-tools` | `local_tools` | Local tool IDs (Swarmline extension) |

**Priority:** When both `skill.yaml` and `SKILL.md` exist in the same directory, `skill.yaml` takes precedence.

### Loading skills

```python
from swarmline.skills import SkillRegistry
from swarmline.skills.loader import YamlSkillLoader

loader = YamlSkillLoader("./skills")
skills = loader.load_all()  # Loads both skill.yaml and SKILL.md formats
registry = SkillRegistry(skills)

# Get MCP servers for active skills
servers = registry.get_mcp_servers_for_skills(["finuslugi"])

# Get tool allowlist
tools = registry.get_tool_allowlist(["finuslugi"])
# -> {"mcp__finuslugi__get_bank_deposits", "mcp__finuslugi__get_bank_credits"}
```

### Skill transports

| Transport | Config | Use Case |
|-----------|--------|----------|
| `url` | `url: "https://..."` | Remote MCP server (SSE) |
| `stdio` | `command: "python server.py"` | Local subprocess |
| `sse` | `url: "https://..."` | Server-Sent Events |

## Tool Policy

Default-deny policy controls which tools agents can use:

```python
from swarmline.policy import DefaultToolPolicy

policy = DefaultToolPolicy()

# Check if a tool is allowed
result = policy.can_use_tool(
    tool_name="mcp__finuslugi__get_deposits",
    input_data={"amount": 500000},
    state=policy_state,  # contains active_skill_ids, allowed_local_tools
)
```

### Always denied tools

These tools are blocked regardless of configuration:
`Bash`, `Read`, `Write`, `Edit`, `MultiEdit`, `Glob`, `Grep`, `LS`, `TodoRead`, `TodoWrite`, `WebFetch`, `WebSearch`.

### Allow rules

A tool is allowed if:
1. It matches an active skill's tool allowlist (`mcp__<skill>__<tool>`)
2. It's in the `allowed_local_tools` set
3. It's in the `allowed_system_tools` set (for web tools etc.)

## Tool ID Codec

MCP tools use a namespaced format: `mcp__<server>__<tool>`.

```python
from swarmline.policy import DefaultToolIdCodec

codec = DefaultToolIdCodec()
codec.encode("finuslugi", "get_deposits")     # "mcp__finuslugi__get_deposits"
codec.extract_server("mcp__finuslugi__get_deposits")  # "finuslugi"
codec.matches("mcp__finuslugi__get_deposits", "finuslugi")  # True
```

## Role-Skill Mapping

Map roles to their allowed skills and local tools:

```yaml
# role_skills.yaml
coach:
  skills: []
  local_tools: [calculate_goal_plan]

deposit_advisor:
  skills: [finuslugi, funds]
  local_tools: [calculate_goal_plan]
```

```python
from swarmline.config import YamlRoleSkillsLoader

loader = YamlRoleSkillsLoader("./prompts/role_skills.yaml")
skills = loader.get_skills("deposit_advisor")  # ["finuslugi", "funds"]
tools = loader.get_local_tools("deposit_advisor")  # ["calculate_goal_plan"]
```
