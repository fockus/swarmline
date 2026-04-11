# UI Event Projection

Transform the `RuntimeEvent` stream into serializable `UIState` snapshots for frontend rendering.

## Quick Start

```python
from swarmline.ui.projection import ChatProjection, project_stream

projection = ChatProjection()

# Stream UIState snapshots directly
async for state in project_stream(runtime.run(...), projection):
    payload = state.to_dict()  # JSON-ready for WebSocket/SSE
    await websocket.send_json(payload)
```

## Core Concepts

### UIState

A serializable snapshot of the current UI state:

```python
@dataclass
class UIState:
    messages: list[UIMessage]    # conversation messages
    status: str                   # "thinking", "tool_calling", "done", etc.
    metadata: dict                # session_id, total_cost_usd, etc.
```

### UIMessage

A single message with typed content blocks:

```python
@dataclass
class UIMessage:
    role: str                     # "assistant", "tool", etc.
    blocks: list[UIBlock]         # content blocks
    timestamp: float | None
```

### UIBlock Types

| Block | Fields | When |
|-------|--------|------|
| `TextBlock` | `text` | Assistant text responses (accumulated from deltas) |
| `ToolCallBlock` | `name`, `args`, `correlation_id` | Tool invocation started |
| `ToolResultBlock` | `name`, `ok`, `summary`, `correlation_id` | Tool execution completed |
| `ErrorBlock` | `kind`, `message` | Runtime error occurred |

## Usage Patterns

### Pattern 1: Streaming to Frontend

```python
from swarmline.ui.projection import ChatProjection, project_stream

projection = ChatProjection()

async for state in project_stream(runtime.run(messages, system_prompt, tools), projection):
    # state.to_dict() is JSON-serializable
    await send_to_frontend(state.to_dict())
```

### Pattern 2: Manual Event Application

```python
projection = ChatProjection()

async for event in runtime.run(messages, system_prompt, tools):
    state = projection.apply(event)
    # Process state after each event
```

### Pattern 3: Post-hoc Reconstruction

```python
projection = ChatProjection()
events = collect_all_events(...)

for event in events:
    state = projection.apply(event)

# Final state contains the complete conversation
print(state.messages)
```

## Serialization

`UIState` supports round-trip serialization with type-discriminated blocks:

```python
# Serialize
payload = state.to_dict()
# {
#   "messages": [
#     {
#       "role": "assistant",
#       "blocks": [
#         {"type": "text", "text": "Let me check..."},
#         {"type": "tool_call", "name": "search", "args": {"q": "..."}, "correlation_id": "abc"},
#         {"type": "tool_result", "name": "search", "ok": true, "summary": "Found 3 results", "correlation_id": "abc"},
#         {"type": "text", "text": "Based on the results..."}
#       ]
#     }
#   ],
#   "status": "done",
#   "metadata": {"session_id": "...", "total_cost_usd": 0.003}
# }

# Deserialize
restored = UIState.from_dict(payload)
```

## Event Mapping

`ChatProjection` maps `RuntimeEvent` types to UI updates:

| RuntimeEvent.type | UI Action |
|-------------------|-----------|
| `assistant_delta` | Accumulate text in last `TextBlock` (or create new one) |
| `tool_call_started` | Add `ToolCallBlock` |
| `tool_call_finished` | Add `ToolResultBlock` |
| `error` | Add `ErrorBlock` |
| `status` | Update `UIState.status` |
| `final` | Set `status="done"`, copy metadata |

## Custom Projections

Implement the `EventProjection` protocol for custom UI representations:

```python
from swarmline.ui.projection import EventProjection, UIState
from swarmline.runtime.types import RuntimeEvent

class MinimalProjection:
    def __init__(self):
        self._state = UIState(messages=[], status="idle", metadata={})

    def apply(self, event: RuntimeEvent) -> UIState:
        # Custom event handling logic
        if event.is_final:
            self._state.status = "done"
        return self._state
```
