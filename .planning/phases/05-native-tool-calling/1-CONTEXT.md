# Phase 5: Native Tool Calling — Context

## Goal

Developers can opt into provider-native tool calling API (Anthropic/OpenAI/Google) for structured tool invocation with parallel execution, while JSON-in-text remains the default (Strangler Fig).

## Requirements

- **NATV-01**: With use_native_tools=True, ThinRuntime sends tools via the provider's native API parameter and parses tool calls from the structured response
- **NATV-02**: Parallel tool calls (multiple tool_use blocks in one response) are executed concurrently via asyncio.gather
- **NATV-03**: With use_native_tools=False (default), behavior is identical to current JSON-in-text parsing
- **NATV-04**: If native tool calling fails, runtime falls back to JSON-in-text automatically (Strangler Fig safety net)
- **NATV-05**: ToolSpec → provider-specific tool format conversion is handled by each adapter
- **NATV-06**: NativeToolCallResult type carries structured response (text + tool calls)

## Existing Infrastructure

### LlmAdapter Protocol (`src/swarmline/runtime/thin/llm_providers.py`)
```python
@runtime_checkable
class LlmAdapter(Protocol):
    async def call(self, messages, system_prompt, **kwargs) -> str: ...
    def stream(self, messages, system_prompt, **kwargs) -> AsyncIterator[str]: ...
```

Three implementations:
- `AnthropicAdapter` — uses `anthropic.AsyncAnthropic`
- `OpenAICompatAdapter` — uses `openai.AsyncOpenAI`
- `GoogleAdapter` — uses `google.genai`

All return raw text. No tools parameter support.

### React Strategy (`src/swarmline/runtime/thin/react_strategy.py`)
- `run_react()` loops: LLM call → parse JSON envelope → execute tool → append result → next LLM call
- Parses `ActionEnvelope` from JSON-in-text: `{"type": "tool_call", "tool": {...}}`
- Executes tools ONE at a time (sequential)
- `parse_envelope()` in parsers.py handles JSON extraction

### RuntimeConfig (`src/swarmline/runtime/types.py`)
- Mutable dataclass with many optional fields
- Needs `use_native_tools: bool = False`

### ToolSpec (`src/swarmline/domain_types.py`)
- `name: str, description: str, parameters: dict[str, Any]`
- Already has JSON Schema format compatible with provider APIs

## Design Decisions

### ADR: NativeToolCallAdapter as Protocol extension

Add a new Protocol `NativeToolCallAdapter` that extends LlmAdapter with `call_with_tools()`.
Existing adapters that support native tools implement this new method.
Adapters that don't support it can remain as LlmAdapter only.

### ADR: Response type

`NativeToolCallResult` frozen dataclass:
- `text: str | None` — assistant text (if any)
- `tool_calls: list[NativeToolCall]` — structured tool calls
- `stop_reason: str` — "end_turn", "tool_use", etc.

`NativeToolCall` frozen dataclass:
- `id: str` — provider-assigned ID
- `name: str` — tool name
- `args: dict[str, Any]` — parsed arguments

### ADR: Strangler Fig fallback

In react strategy:
1. If `use_native_tools` and adapter supports it: use `call_with_tools()`
2. If call_with_tools raises or adapter doesn't support it: fall back to JSON-in-text `call()`
3. Default: `use_native_tools=False` → existing behavior unchanged

### ADR: Parallel execution

When native response contains multiple tool calls:
- Execute all concurrently with `asyncio.gather(*[executor.execute(tc.name, tc.args) for tc in tool_calls])`
- Emit tool_call_started/finished events for each
- Collect results, format as tool messages for next LLM turn

## Scope

- 1 new file: `src/swarmline/runtime/thin/native_tools.py` (Protocol, types, ToolSpec converter)
- Modify `llm_providers.py`: add `call_with_tools()` to each adapter
- Modify `react_strategy.py`: add native tool calling path + parallel execution + fallback
- Add `use_native_tools: bool = False` to RuntimeConfig
- ~15-20 tests (unit + integration)
