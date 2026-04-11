# Configuration

## CognitiaStack -- Unified Assembly Point

`CognitiaStack.create()` assembles all library components into a single object.
Each capability is an independent toggle -- pass a provider to enable it, or `None` to disable.

```python
from cognitia.bootstrap.stack import CognitiaStack
from cognitia.runtime.types import RuntimeConfig
from cognitia.policy.tool_selector import ToolBudgetConfig

stack = CognitiaStack.create(
    # === Required ===
    prompts_dir=Path("prompts"),
    skills_dir=Path("skills"),
    project_root=Path("."),

    # === Runtime ===
    runtime_config=RuntimeConfig(runtime_name="thin", model="claude-sonnet-4-20250514"),

    # === Capability toggles ===
    sandbox_provider=sandbox,             # SandboxProvider | None
    web_provider=web,                     # WebProvider | None
    todo_provider=todo,                   # TodoProvider | None
    memory_bank_provider=memory,          # MemoryBankProvider | None
    memory_bank_prompt=None,              # str | None (None = built-in default)
    plan_manager=plan_mgr,               # PlanManager | None
    plan_user_id="user-42",              # str (namespace for plans)
    plan_topic_id="project-7",           # str (namespace for plans)
    thinking_enabled=True,               # bool

    # === Security ===
    allowed_system_tools={"bash", "read", "write"},  # whitelist
    tool_budget_config=ToolBudgetConfig(max_tools=25),

    # === Routing ===
    escalate_roles={"strategy_planner"},
    local_tool_resolver=my_resolver,
)
```

### What You Get

```python
stack.capability_specs      # dict[str, ToolSpec] -- all capability tool specs
stack.capability_executors  # dict[str, Callable] -- executors for capability tools
stack.tool_policy           # DefaultToolPolicy with whitelist
stack.context_builder       # DefaultContextBuilder with P_MEMORY support
stack.runtime_factory       # RuntimeFactory
stack.skill_registry        # SkillRegistry (MCP skills)
stack.role_router           # KeywordRoleRouter
stack.model_policy          # ModelPolicy (role-based model escalation)
stack.runtime_config        # RuntimeConfig
```

## Security Defaults

The current release family is secure by default at the relevant boundary:

| Surface | Default | Explicit opt-in |
| ------- | ------- | --------------- |
| MCP host execution | closed (`enable_host_exec=False`) | set `enable_host_exec=True` only for trusted operators |
| `LocalSandboxProvider` host execution | closed (`allow_host_execution=False`) | set `allow_host_execution=True` only for trusted hosts |
| HTTP `/v1/query` without auth | closed (`allow_unauthenticated_query=False`) | require auth or turn on unauthenticated access intentionally |

`LocalSandboxProvider` is a file and command capability for isolated environments; keep host execution off unless you explicitly trust the boundary.

---

## AgentConfig

`AgentConfig` is the frozen configuration for the Agent facade. The only required parameter is `system_prompt`.

```python
from cognitia.agent.config import AgentConfig

config = AgentConfig(
    system_prompt="You are a helpful assistant.",

    model="sonnet",                          # alias or full model name
    runtime="claude_sdk",                    # claude_sdk | thin | deepagents

    tools=(),                                # tuple of @tool-decorated ToolDefinitions
    middleware=(),                            # middleware chain (applied in order)
    mcp_servers={},                           # remote MCP server configs

    max_turns=None,                          # turn limit per conversation
    max_budget_usd=None,                     # USD budget limit

    output_format=None,                      # JSON Schema for structured output
    cwd=None,                                # working directory
    env={},                                  # environment variables

    # Runtime convergence
    feature_mode="portable",                 # portable | native
    allow_native_features=False,
)
```

---

## RuntimeConfig

`RuntimeConfig` controls which runtime executes the agent loop and its operational limits.

```python
from cognitia.runtime.types import RuntimeConfig

config = RuntimeConfig(
    runtime_name="thin",                        # claude_sdk | thin | deepagents
    model="claude-sonnet-4-20250514",           # or alias: "sonnet", "opus", "haiku"
    base_url=None,                              # for compatible APIs (OpenRouter, Groq, Together)
    max_iterations=6,                           # ReAct iteration limit (thin runtime)
    max_tool_calls=8,                           # tool call limit per turn (thin runtime)
    max_model_retries=2,                        # retry limit on model errors (thin runtime)
    output_format=None,                         # JSON Schema for structured output
    output_type=None,                           # Pydantic model for auto-validated output
)
```

### Models and Aliases

Model names are resolved via the `ModelRegistry`, configured in `runtime/models.yaml`.
Resolution priority: exact alias match > exact full name > prefix match > default model.

| Alias          | Model                    | Provider  |
| -------------- | ------------------------ | --------- |
| `sonnet`       | claude-sonnet-4-20250514 | Anthropic |
| `opus`         | claude-opus-4-20250514   | Anthropic |
| `haiku`        | claude-haiku-3-20250307  | Anthropic |
| `4o`           | gpt-4o                   | OpenAI    |
| `4o-mini`      | gpt-4o-mini              | OpenAI    |
| `o3`           | o3                       | OpenAI    |
| `gemini`       | gemini-2.5-pro           | Google    |
| `gemini-flash` | gemini-2.5-flash         | Google    |
| `deepseek`     | deepseek-chat            | DeepSeek  |
| `r1`           | deepseek-reasoner        | DeepSeek  |

You can also use prefix matching: `"claude-sonnet"` resolves to `"claude-sonnet-4-20250514"`.

---

## ToolPolicy -- Access Control

`DefaultToolPolicy` implements a default-deny approach to tool access.

```python
from cognitia.policy import DefaultToolPolicy

policy = DefaultToolPolicy(
    allowed_system_tools={"bash", "read", "write"},  # whitelist
    extra_denied={"dangerous_tool"},                  # additional deny entries
)
```

### Evaluation Logic

1. Tool is in `ALWAYS_DENIED_TOOLS` and **not** in `allowed_system_tools` -- **deny**
2. Tool is in `allowed_local_tools` (including `mcp__app_tools__*`) -- **allow**
3. Tool name starts with `mcp__` and the MCP server is active -- **allow**
4. Otherwise -- **deny**

### ALWAYS_DENIED_TOOLS

Both PascalCase (Claude SDK naming) and snake_case (builtin naming) variants are covered:

```text
Bash/bash, Read/read, Write/write, Edit/edit, MultiEdit/multi_edit,
Glob/glob, Grep/grep, LS/ls, TodoRead/todo_read, TodoWrite/todo_write,
WebFetch/web_fetch, WebSearch/web_search
```

These tools are denied by default. Add them to `allowed_system_tools` to whitelist specific ones.

---

## ToolBudgetConfig -- Tool Budget

Controls how many tools are exposed to the model and in what priority order.

```python
from cognitia.policy.tool_selector import ToolBudgetConfig, ToolGroup

config = ToolBudgetConfig(
    max_tools=30,                           # total tool limit (default: 30)
    group_priority=[                        # fill order (highest priority first)
        ToolGroup.ALWAYS,                   # thinking, todo
        ToolGroup.MCP,                      # business tools via MCP
        ToolGroup.MEMORY,                   # memory bank tools
        ToolGroup.PLANNING,                 # plan_create / plan_status / plan_execute
        ToolGroup.SANDBOX,                  # bash, read, write, ...
        ToolGroup.WEB,                      # web_fetch, web_search
    ],
    group_limits={                          # per-group limits (optional)
        ToolGroup.MCP: 12,
        ToolGroup.SANDBOX: 4,
    },
)
```

---

## MemoryBankConfig

```python
from cognitia.memory_bank.types import MemoryBankConfig

config = MemoryBankConfig(
    enabled=True,
    backend="filesystem",               # filesystem | database
    root_path=Path("/data/memory"),
    max_file_size_bytes=100 * 1024,     # 100 KB per file
    max_total_size_bytes=1024 * 1024,   # 1 MB total
    max_entries=200,                     # max number of files
    max_depth=2,                        # root/subfolder/file
    auto_load_on_turn=True,             # load MEMORY.md into system prompt
    auto_load_max_lines=200,
    default_folders=["plans", "reports", "notes"],
    prompt_path=None,                   # None = built-in default prompt
)
```

---

## TodoConfig

```python
from cognitia.todo.types import TodoConfig

config = TodoConfig(
    enabled=True,
    backend="memory",                   # memory | filesystem | database
    root_path=Path("/data/todos"),      # for filesystem backend
    max_todos=100,
    auto_cleanup_completed=False,
)
```

---

## SandboxConfig

```python
from cognitia.tools.types import SandboxConfig

config = SandboxConfig(
    root_path="/data/sandbox",
    user_id="user-42",
    topic_id="project-7",
    max_file_size_bytes=10 * 1024 * 1024,   # 10 MB
    timeout_seconds=30,
    allowed_extensions=frozenset({".py", ".txt", ".md", ".json"}),
    denied_commands=frozenset({"rm", "sudo", "kill", "chmod"}),
    allow_host_execution=False,              # opt-in only
)
```

Each agent gets an isolated workspace at `{root_path}/{user_id}/{topic_id}/workspace/`.

---

## Environment Variables

| Variable             | Description                                                                        | Default                    |
| -------------------- | ---------------------------------------------------------------------------------- | -------------------------- |
| `ANTHROPIC_API_KEY`  | Anthropic API key                                                                  | --                         |
| `OPENAI_API_KEY`     | API key for OpenAI-compatible providers (OpenAI, OpenRouter, Groq, Together, etc.) | --                         |
| `OPENAI_BASE_URL`    | Endpoint override for OpenAI-compatible clients / provider bridges                 | --                         |
| `GOOGLE_API_KEY`     | Google GenAI API key                                                               | --                         |
| `OPENROUTER_API_KEY` | Convenience variable for OpenRouter (mapped to OpenAI-compatible path)             | --                         |
| `ANTHROPIC_MODEL`    | Anthropic model (alias or full name)                                               | `claude-sonnet-4-20250514` |
| `COGNITIA_RUNTIME`   | Runtime selection (`claude_sdk`, `thin`, `deepagents`, `cli`)                      | `claude_sdk`               |
| `E2B_API_KEY`        | E2B API key (cloud sandbox)                                                        | --                         |
| `DATABASE_URL`       | PostgreSQL connection string                                                       | --                         |

For a detailed matrix of `runtime > provider > env vars > params`, see
[Credentials & Provider Setup](credentials.md).
