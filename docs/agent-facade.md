# Agent Facade API

The `swarmline.agent` module provides a high-level API for building AI agents in 3-5 lines of code.

## Overview

```python
from swarmline import Agent, AgentConfig, tool

agent = Agent(AgentConfig(runtime="thin"))
result = await agent.query("Hello!")
print(result.text)
```

## AgentConfig

Frozen dataclass with all agent configuration:

```python
from swarmline import AgentConfig

config = AgentConfig(
    runtime="thin",                    # "thin" | "claude_sdk" | "deepagents" | "cli"
    model="sonnet",                    # model alias or full ID
    system_prompt="You are helpful.",  # system prompt
    tools=(my_tool,),                  # tuple of @tool-decorated functions
    middleware=(tracker, guard),        # middleware chain
    max_turns=10,                      # max conversation turns
    permission_mode="bypassPermissions",  # SDK permission mode
    cwd="/path/to/project",           # working directory for tools
    output_format={"type": "object"},  # JSON Schema for structured output
    mcp_servers={"my_server": config}, # MCP server configs
)
```

`system_prompt` is required (rejected if empty by `AgentConfig.__post_init__`); `runtime` defaults to `"thin"`. All other fields have sensible defaults.

## Agent

### query(prompt) -> Result

One-shot request. Applies middleware chain, executes through runtime, collects result.

```python
result = await agent.query("What is 2+2?")
print(result.text)           # "4"
print(result.ok)             # True
print(result.total_cost_usd) # 0.001
print(result.usage)          # {"input_tokens": 10, "output_tokens": 5}
```

### stream(prompt) -> AsyncIterator

Streaming mode. Yields events as they arrive from the runtime.

```python
async for event in agent.stream("Write a poem"):
    if event.type == "text_delta":
        print(event.text, end="", flush=True)
    elif event.type == "tool_use_start":
        print(f"\n[Using tool: {event.tool_name}]")
    elif event.type == "done":
        print("\n[Done]")
```

Event types: `text_delta`, `tool_use_start`, `tool_use_result`, `done`, `error`.

### conversation(session_id=None) -> Conversation

Create a multi-turn conversation with persistent context.

```python
conv = agent.conversation()

# Or as async context manager (auto-cleanup)
async with agent.conversation() as conv:
    r1 = await conv.say("My name is Alice")
    r2 = await conv.say("What's my name?")
    print(r2.text)  # "Your name is Alice."
    print(conv.history)  # list of Message objects
```

### cleanup()

Release resources (runtime subprocess, adapters).

```python
await agent.cleanup()

# Or use as context manager
async with Agent(config) as agent:
    result = await agent.query("Hello")
# cleanup called automatically
```

## Result

Frozen dataclass returned by `query()` and `conversation.say()`:

```python
@dataclass(frozen=True)
class Result:
    text: str = ""
    session_id: str | None = None
    total_cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    structured_output: Any = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None
```

## @tool Decorator

Define tools with automatic JSON Schema inference from type hints:

```python
from swarmline import tool

@tool(name="weather", description="Get current weather")
async def get_weather(city: str, units: str = "celsius") -> str:
    # city is required (str -> {"type": "string"})
    # units is optional (has default)
    return f"Weather in {city}: 22 {units}"
```

### Auto-inferred types

| Python Type | JSON Schema Type |
|------------|-----------------|
| `str`      | `"string"`      |
| `int`      | `"integer"`     |
| `float`    | `"number"`      |
| `bool`     | `"boolean"`     |

Parameters without defaults go into `required`. Optional parameters (with `None` default) are excluded from `required`.

### Explicit schema

Override auto-inference with a custom schema:

```python
custom_schema = {
    "type": "object",
    "properties": {"query": {"type": "string", "maxLength": 200}},
    "required": ["query"],
}

@tool(name="search", description="Search", schema=custom_schema)
async def search(query: str) -> str:
    return "results"
```

### ToolDefinition

The `@tool` decorator attaches a `ToolDefinition` to the function:

```python
td = get_weather.__tool_definition__
td.name          # "weather"
td.description   # "Get current weather"
td.parameters    # {"type": "object", "properties": {...}, "required": [...]}
td.handler       # reference to the original async function
td.to_tool_spec()  # convert to swarmline ToolSpec for runtime
```

## Middleware

Middleware intercepts the request/response lifecycle:

```python
from swarmline.agent import Middleware

class LoggingMiddleware(Middleware):
    async def before_query(self, prompt: str, config) -> str:
        print(f"Query: {prompt}")
        return prompt  # can modify prompt

    async def after_result(self, result) -> Result:
        print(f"Result: {result.text[:50]}")
        return result  # can modify result
```

### Built-in: CostTracker

Tracks cumulative cost and blocks queries when budget exceeded:

```python
from swarmline.agent import CostTracker

tracker = CostTracker(budget_usd=5.0)
agent = Agent(AgentConfig(middleware=(tracker,)))

result = await agent.query("Hello")
print(tracker.total_cost_usd)  # 0.002
```

If a request pushes the cumulative spend above the configured budget,
`CostTracker` raises `BudgetExceededError`.

### Built-in: SecurityGuard

Blocks prompts containing sensitive patterns:

```python
from swarmline.agent import SecurityGuard

guard = SecurityGuard(
    block_patterns=["password", "api_key", "secret"],
)
```

### Built-in: ToolOutputCompressor

Compresses large tool outputs between turns. Content-type aware: JSON arrays are truncated, HTML tags are stripped, plain text uses head+tail strategy.

```python
from swarmline.agent import ToolOutputCompressor

compressor = ToolOutputCompressor(max_result_chars=10000)
agent = Agent(AgentConfig(middleware=(compressor,)))
```

Integrates with `HookRegistry` via `on_post_tool_use` callback.

### build_middleware_stack()

Factory function for common middleware combinations:

```python
from swarmline.agent import build_middleware_stack

stack = build_middleware_stack(
    cost_tracker=True,
    tool_compressor=True,
    security_guard=True,
    budget_usd=5.0,
    blocked_patterns=["rm -rf"],
    max_result_chars=10000,
)

agent = Agent(AgentConfig(middleware=stack))
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `cost_tracker` | `bool` | `False` | Enable CostTracker |
| `tool_compressor` | `bool` | `True` | Enable ToolOutputCompressor |
| `security_guard` | `bool` | `False` | Enable SecurityGuard |
| `max_result_chars` | `int` | `10000` | Max chars for tool output |
| `budget_usd` | `float` | `0.0` | Cost budget limit |
| `blocked_patterns` | `list[str]` | `[]` | Patterns to block |

### Middleware chain order

Middleware executes in declaration order for both `before_query` and `after_result`:

```python
# before_query: mw1 -> mw2 -> mw3
# after_result: mw1 -> mw2 -> mw3
config = AgentConfig(middleware=(mw1, mw2, mw3))
```

## Conversation

Multi-turn dialog management with history tracking.

### say(message) -> Result

Send a message and get a response:

```python
async with agent.conversation() as conv:
    r = await conv.say("Hello")
    print(r.text)
```

### stream(message) -> AsyncIterator

Stream a response in a conversation:

```python
async with agent.conversation() as conv:
    async for event in conv.stream("Tell me a story"):
        if event.type == "text_delta":
            print(event.text, end="")
```

### Properties

```python
conv.session_id  # unique session identifier
conv.history     # list[Message] - accumulated messages
```

### Runtime behavior

- **claude_sdk**: warm subprocess, continues conversation natively
- **thin/deepagents**: accumulated messages sent each turn via `AgentRuntime.run()`
