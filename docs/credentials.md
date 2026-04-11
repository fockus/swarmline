# Credentials & Provider Setup

This page is the canonical reference for API keys, environment variables, and provider-specific parameters across Swarmline runtimes.

## Quick Matrix

| Runtime | Typical provider path | Primary credentials | Where to pass params |
|---------|------------------------|---------------------|----------------------|
| `thin` | Anthropic, OpenAI-compatible, Google | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` | Process env for `AgentConfig`; `RuntimeConfig(model=..., base_url=...)` for direct runtime usage |
| `claude_sdk` | Claude Agent SDK / Claude ecosystem | existing Claude login or `ANTHROPIC_API_KEY` | `AgentConfig.env`, process env, or SDK/CLI login state |
| `deepagents` | Anthropic baseline; OpenAI/Google via provider package | provider-specific env for LangChain model class | Process env for `AgentConfig`; `RuntimeConfig(model=..., base_url=...)` for direct runtime usage |
| `cli` | Wrapped external CLI | whatever the wrapped CLI expects | `CliConfig.env` or inherited shell environment |

## Important Rules

### 1. `AgentConfig.env` is not a universal provider injector

`AgentConfig.env` is currently used by the `claude_sdk` runtime path. Portable runtimes built through the facade (`thin`, `deepagents`) resolve credentials from the current process environment instead.

If you use the facade:

```python
from swarmline import Agent, AgentConfig

agent = Agent(
    AgentConfig(
        system_prompt="You are helpful.",
        runtime="thin",
        model="openai:gpt-4.1-mini",
    )
)
```

set provider credentials in the shell environment before creating the agent.

### 2. `RuntimeConfig.base_url` is only available on direct runtime construction

If you instantiate a runtime directly, you can pass `base_url` explicitly:

```python
from swarmline.runtime.types import RuntimeConfig
from swarmline.runtime.thin.runtime import ThinRuntime

runtime = ThinRuntime(
    config=RuntimeConfig(
        runtime_name="thin",
        model="openai:gpt-4.1-mini",
        base_url="https://openrouter.ai/api/v1",
    )
)
```

The high-level `AgentConfig` facade does not currently expose `base_url`.

### 3. OpenRouter is an OpenAI-compatible path in Swarmline

For Swarmline portable runtimes, OpenRouter should be treated as an OpenAI-compatible endpoint:

- `thin`: use `model="openrouter:..."` or another OpenAI-compatible model with `OPENAI_API_KEY`
- `deepagents`: use the OpenAI provider path, for example `model="openai:anthropic/claude-3.5-haiku"`

Do **not** assume that pointing Anthropic-specific clients at `https://openrouter.ai/api/v1` is a drop-in replacement.

## Thin Runtime

`thin` supports three SDK families:

- Anthropic
- OpenAI-compatible
- Google

### Anthropic path

Use this when you want native Anthropic credentials and Anthropic model aliases such as `sonnet`, `opus`, `haiku`.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

```python
agent = Agent(AgentConfig(
    system_prompt="You are helpful.",
    runtime="thin",
    model="sonnet",
))
```

Equivalent explicit models:

- `anthropic:claude-sonnet-4-20250514`
- `claude-sonnet-4-20250514`

### OpenAI-compatible path

Use this for:

- OpenAI
- OpenRouter
- Together
- Groq
- Fireworks
- DeepSeek
- Ollama
- local OpenAI-compatible servers

Canonical credential:

```bash
export OPENAI_API_KEY=sk-...
```

#### OpenAI

```python
agent = Agent(AgentConfig(
    system_prompt="You are helpful.",
    runtime="thin",
    model="openai:gpt-4.1-mini",
))
```

#### OpenRouter

```bash
export OPENAI_API_KEY=sk-or-...
```

```python
agent = Agent(AgentConfig(
    system_prompt="You are helpful.",
    runtime="thin",
    model="openrouter:anthropic/claude-3.5-haiku",
))
```

No manual `base_url` is required here; Swarmline auto-resolves OpenRouter's endpoint for the `openrouter:` provider prefix.

#### Custom OpenAI-compatible endpoint

For direct runtime usage:

```python
runtime = ThinRuntime(
    config=RuntimeConfig(
        runtime_name="thin",
        model="openai:gpt-4.1-mini",
        base_url="https://your-gateway.example.com/v1",
    )
)
```

### Google path

```bash
export GOOGLE_API_KEY=...
```

```python
agent = Agent(AgentConfig(
    system_prompt="You are helpful.",
    runtime="thin",
    model="google:gemini-2.5-pro",
))
```

## Claude SDK Runtime

`claude_sdk` uses the Claude Agent SDK / Claude local environment.

Typical options:

- authenticated local Claude installation / existing login
- `ANTHROPIC_API_KEY` in the process environment
- `AgentConfig.env` for explicit env injection

```python
agent = Agent(AgentConfig(
    system_prompt="You are helpful.",
    runtime="claude_sdk",
    model="sonnet",
    env={"ANTHROPIC_API_KEY": "sk-ant-..."},
))
```

Use `AgentConfig.env` here when you want deterministic subprocess credentials instead of inheriting the current shell/session state.

## DeepAgents Runtime

`deepagents` supports only these provider prefixes today:

- `anthropic`
- `openai`
- `google`

It does **not** accept `openrouter:*`, `groq:*`, `together:*`, or other portable provider aliases directly.

### Anthropic baseline

Installed by `swarmline[deepagents]`:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

```python
agent = Agent(AgentConfig(
    system_prompt="You are helpful.",
    runtime="deepagents",
    model="sonnet",
))
```

### OpenAI / OpenRouter path

Install bridge packages first:

```bash
pip install swarmline[deepagents] langchain-openai openai
```

Environment:

```bash
export OPENAI_API_KEY=sk-...
```

Plain OpenAI:

```python
agent = Agent(AgentConfig(
    system_prompt="You are helpful.",
    runtime="deepagents",
    model="openai:gpt-4.1-mini",
))
```

OpenRouter through the OpenAI-compatible path:

```bash
export OPENAI_API_KEY=sk-or-...
export OPENAI_BASE_URL=https://openrouter.ai/api/v1
```

```python
agent = Agent(AgentConfig(
    system_prompt="You are helpful.",
    runtime="deepagents",
    model="openai:anthropic/claude-3.5-haiku",
))
```

For direct runtime construction you can pass `RuntimeConfig(base_url=...)` instead of relying on `OPENAI_BASE_URL`.

### Google path

Install bridge packages:

```bash
pip install swarmline[deepagents] langchain-google-genai
```

Environment:

```bash
export GOOGLE_API_KEY=...
```

```python
agent = Agent(AgentConfig(
    system_prompt="You are helpful.",
    runtime="deepagents",
    model="google:gemini-2.5-pro",
))
```

`deepagents` currently does not support `base_url` override on the Google provider path.

## CLI Runtime

`cli` does not define its own provider/auth scheme. It wraps an external command and passes environment variables to that process.

Two common patterns:

### Inherit the shell environment

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python your_script.py
```

### Pass explicit env via `CliConfig.env`

```python
from swarmline.runtime.cli.runtime import CliAgentRuntime
from swarmline.runtime.cli.types import CliConfig
from swarmline.runtime.types import RuntimeConfig

runtime = CliAgentRuntime(
    config=RuntimeConfig(runtime_name="cli"),
    cli_config=CliConfig(
        command=["claude", "--print", "--verbose", "--output-format", "stream-json", "-"],
        env={"ANTHROPIC_API_KEY": "sk-ant-..."},
    ),
)
```

If you wrap a non-Claude CLI, use the environment variables expected by that CLI, not Swarmline-specific names.

## Example-Specific Convenience Variables

Two examples expose a convenience wrapper around OpenRouter:

- `examples/24_deep_research.py --live`
- `examples/27_nano_claw.py --live`

They accept either:

- `ANTHROPIC_API_KEY`
- `OPENROUTER_API_KEY`

When `OPENROUTER_API_KEY` is present, the example maps it internally to the OpenAI-compatible path before building the agent.

## Environment Variable Reference

| Variable | Used by | Meaning |
|----------|---------|---------|
| `ANTHROPIC_API_KEY` | `thin` Anthropic path, `claude_sdk`, `deepagents` Anthropic path | Anthropic credentials |
| `OPENAI_API_KEY` | `thin` OpenAI-compatible path, `deepagents` OpenAI path | OpenAI-compatible credentials |
| `OPENAI_BASE_URL` | useful with `deepagents` OpenAI provider path | Override the underlying OpenAI-compatible endpoint |
| `GOOGLE_API_KEY` | `thin` Google path, `deepagents` Google path | Google GenAI credentials |
| `OPENROUTER_API_KEY` | example convenience only | Helper variable used by examples `24` and `27` to populate `OPENAI_API_KEY` |

## Recommended Defaults

- Want the simplest portable multi-provider path: use `runtime="thin"` and set provider env vars in the shell.
- Want Claude-native features and local SDK integration: use `runtime="claude_sdk"` and either local Claude login or `ANTHROPIC_API_KEY`.
- Want DeepAgents with OpenRouter: use the OpenAI-compatible path, not `openrouter:*`.
- Want a subprocess wrapper around an external agent: use `runtime="cli"` and pass credentials through `CliConfig.env` or shell env.
