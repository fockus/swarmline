# Structured Output

Parse and validate LLM responses against Pydantic models or JSON Schema — with automatic retry on validation failure.

## Quick Start

```python
from pydantic import BaseModel
from swarmline import Agent, AgentConfig

class WeatherReport(BaseModel):
    city: str
    temperature: float
    summary: str

agent = Agent(AgentConfig(
    system_prompt="You are a weather bot. Always respond with structured data.",
    runtime="thin",
    output_type=WeatherReport,
))

result = await agent.query("Weather in Berlin?")
report = result.structured_output  # WeatherReport(city="Berlin", temperature=18.5, summary="Partly cloudy")
```

Setting `output_type` automatically:

1. Extracts JSON Schema from the Pydantic model
2. Appends schema instructions to the system prompt
3. Parses and validates the LLM response
4. Retries on validation failure (configurable)

## Configuration

### With Pydantic model (recommended)

```python
from swarmline.runtime.types import RuntimeConfig

config = RuntimeConfig(
    runtime_name="thin",
    output_type=WeatherReport,       # Pydantic BaseModel subclass
    max_model_retries=2,             # retry on validation failure (default: 0)
)
```

`output_format` is set automatically from `output_type.model_json_schema()`.

### With raw JSON Schema

```python
config = RuntimeConfig(
    runtime_name="thin",
    output_format={"type": "object", "properties": {"x": {"type": "integer"}}},
)
```

Without `output_type`, the parsed result is a plain `dict`.

## Retry on Validation Failure

When `max_model_retries > 0` and validation fails, the runtime re-prompts the LLM with the error message. The retry loop runs up to `max_model_retries` additional attempts.

```python
config = RuntimeConfig(
    runtime_name="thin",
    output_type=WeatherReport,
    max_model_retries=3,       # up to 3 extra attempts after initial failure
    max_iterations=10,         # overall iteration budget
)
```

If all retries are exhausted, a `RuntimeEvent` with `kind="bad_model_output"` is emitted.

## Nested Models

Nested Pydantic models work out of the box — the full JSON Schema is extracted recursively.

```python
class Address(BaseModel):
    city: str
    country: str

class Person(BaseModel):
    name: str
    address: Address

config = RuntimeConfig(runtime_name="thin", output_type=Person)
```

## Low-level API

The `structured_output` module exposes stateless functions for custom use cases:

```python
from swarmline.runtime.structured_output import (
    validate_structured_output,        # parse JSON + Pydantic validation, raises on failure
    try_resolve_structured_output,     # returns (result, error_str), never raises
    extract_structured_output,         # extract first JSON object from text
    extract_pydantic_schema,           # model_json_schema() wrapper
    append_structured_output_instruction,  # inject schema into system prompt
)

# Safe parse — returns (result, None) or (None, error_message)
result, err = try_resolve_structured_output(
    text='{"city": "Berlin", "temperature": 18.5, "summary": "Sunny"}',
    output_format=None,
    output_type=WeatherReport,
)
```

## How It Works

```
System prompt
    │
    ▼
append_structured_output_instruction()  ← adds JSON Schema instructions
    │
    ▼
LLM call
    │
    ▼
try_resolve_structured_output()  ← parse + validate
    │
    ├─ success → final event with structured_output
    └─ failure → retry (if retries remaining) or error event
```

## Accessing the Result

The structured output is available in the final `RuntimeEvent`:

```python
async for event in runtime.run(messages=..., system_prompt=..., active_tools=[]):
    if event.is_final:
        model_instance = event.structured_output  # Pydantic model or dict
        raw_text = event.text                      # original LLM text
```

Or via the Agent facade:

```python
result = await agent.query("...")
result.structured_output  # the validated model instance
```

## Agent.query_structured() (Recommended)

The simplest way to get type-safe structured output:

```python
from pydantic import BaseModel
from swarmline.agent import Agent, AgentConfig, StructuredOutputError

class Sentiment(BaseModel):
    label: str
    score: float
    reasoning: str

agent = Agent(AgentConfig(
    system_prompt="Analyze sentiment of the given text.",
    runtime="thin",
))

# Returns a validated Sentiment instance — not Result, not str
sentiment = await agent.query_structured(
    "I love sunny days!",
    Sentiment,
)
print(sentiment.label)   # "positive"
print(sentiment.score)   # 0.95
```

`query_structured()` handles:

1. Setting `output_type` and `output_format` on a temporary config
2. Running the query through the normal pipeline (with retry)
3. Extracting and returning `result.structured_output` as type `T`
4. Raising `StructuredOutputError` if validation fails after all retries

### Error Handling

```python
try:
    result = await agent.query_structured("...", Sentiment)
except StructuredOutputError as exc:
    print(f"Failed: {exc}")
    # exc.raw_text — the raw LLM response that failed validation
```

### Differences from query()

| | `query()` | `query_structured()` |
|---|-----------|---------------------|
| Return type | `Result` | `T` (Pydantic model) |
| Access output | `result.structured_output` | direct |
| Requires `output_type` in config | yes | no (set automatically) |
| Error on validation failure | `result.text` has raw text | raises `StructuredOutputError` |
