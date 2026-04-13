# Phase 14: Session Resume — Context

## Goal

Agents can persist their conversation state and resume where they left off across process restarts, with automatic compaction when restored history is too large.

## Requirements

- **SESS-01**: Conversation history is persisted to MessageStore between run() calls and survives process restart
- **SESS-02**: Resuming by session_id loads the previous conversation and continues seamlessly
- **SESS-03**: When restored history exceeds token budget, auto-compaction triggers before the resumed run proceeds
- **SESS-04**: JSONL persistence format round-trips all message types (user, assistant, tool_call, tool_result) without data loss

## What Already Exists

### MessageStore protocol (protocols/memory.py:10-38)
- save_message(user_id, topic_id, role, content, tool_calls)
- get_messages(user_id, topic_id, limit) → list[MemoryMessage]
- count_messages, delete_messages_before
- 3 implementations: InMemory, SQLite, PostgreSQL

### SessionBackend (session/backends.py)
- save(key, state), load(key), delete(key), list_keys()
- 2 implementations: InMemory, SQLite (file-based)

### SessionSnapshotStore (session/snapshot_store.py)
- Already persists runtime_messages to SessionBackend as JSON
- Restores with is_rehydrated=True flag
- Has TTL-based expiration

### Conversation (agent/conversation.py)
- Maintains _history: list[Message] across say() calls
- session_id param exists but doesn't auto-load
- No auto-persist after turns

### ThinRuntime.run() (runtime/thin/runtime.py:216)
- Accepts messages: list[Message] as input
- Returns AsyncIterator[RuntimeEvent] — includes RuntimeEvent.final with new_messages

## What Phase 14 Adds

### 1. JsonlMessageStore (NEW)
Lightweight file-based MessageStore using JSONL format:
- One JSON line per message
- Fields: role, content, name, tool_calls, metadata, timestamp
- Append-only writes (fast, no SQL overhead)
- Read: load all lines, parse, return as list
- File per session: `{base_dir}/{session_id}.jsonl`

### 2. Conversation.resume(session_id) (EXTEND)
- Load history from MessageStore by session_id
- Populate _history with loaded messages
- Continue conversation seamlessly

### 3. Auto-persist in Conversation (EXTEND)
- After each say() → save new messages to MessageStore
- Configurable: auto_persist=True (default when message_store provided)

### 4. Auto-compaction on resume (NEW)
- When loaded history exceeds compaction threshold
- Apply ConversationCompactionFilter before first run()
- Uses existing compaction from Phase 13

## Design

### JsonlMessageStore
```python
class JsonlMessageStore:
    """File-based message persistence using JSONL format."""
    
    def __init__(self, base_dir: str | Path):
        self._base_dir = Path(base_dir)
    
    async def save_message(self, user_id, topic_id, role, content, tool_calls=None):
        # Append one JSON line to {base_dir}/{user_id}_{topic_id}.jsonl
    
    async def get_messages(self, user_id, topic_id, limit=10):
        # Read JSONL file, return last N as MemoryMessage
```

### Conversation resume flow
```python
class Conversation:
    async def resume(self, session_id: str) -> None:
        """Load conversation history from message store."""
        if self._message_store:
            stored = await self._message_store.get_messages(
                user_id=self._user_id, topic_id=session_id, limit=1000
            )
            self._history = [Message(role=m.role, content=m.content, ...) for m in stored]
```

### Auto-compaction on resume
```python
# In Conversation._maybe_compact():
if self._compaction_config and len(self._history) > 0:
    filter = ConversationCompactionFilter(config=self._compaction_config)
    self._history, _ = await filter.filter(self._history, self._system_prompt)
```

## Files

### New
- `src/swarmline/session/jsonl_store.py` — JsonlMessageStore
- `tests/unit/test_jsonl_store.py` — unit tests
- `tests/integration/test_session_resume.py` — integration tests

### Modified
- `src/swarmline/agent/conversation.py` — resume(), auto-persist, auto-compact
- `src/swarmline/__init__.py` — export JsonlMessageStore
