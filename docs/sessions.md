# Session Backends

Pluggable session state persistence with namespace isolation via `MemoryScope`.

## Quick Start

```python
from swarmline.session.backends import SqliteSessionBackend, MemoryScope, scoped_key

backend = SqliteSessionBackend(db_path="sessions.db")

# Save session state with namespace isolation
key = scoped_key(MemoryScope.AGENT, "user:42:session:abc")
await backend.save(key, {"role": "coach", "turn": 7})

# Load it back
state = await backend.load(key)  # {"role": "coach", "turn": 7}

# List all keys
keys = await backend.list_keys()  # ["agent:user:42:session:abc"]

# Cleanup
backend.close()
```

## Available Backends

| Backend | Storage | Persistence | Dependencies |
|---------|---------|-------------|--------------|
| `InMemorySessionBackend` | Dict | Process lifetime only | None |
| `SqliteSessionBackend` | SQLite file | Persists across restarts | None (stdlib) |

Both implement the `SessionBackend` protocol:

```python
class SessionBackend(Protocol):
    async def save(self, key: str, state: dict[str, Any]) -> None: ...
    async def load(self, key: str) -> dict[str, Any] | None: ...
    async def delete(self, key: str) -> bool: ...
    async def list_keys(self) -> list[str]: ...
```

## Memory Scopes

`MemoryScope` provides namespace isolation — different agents or contexts can use the same key names without collisions.

| Scope | Prefix | Use case |
|-------|--------|----------|
| `MemoryScope.GLOBAL` | `global:` | Shared across all agents |
| `MemoryScope.AGENT` | `agent:` | Per-agent isolation |
| `MemoryScope.SHARED` | `shared:` | Shared between specific agent groups |

```python
from swarmline.session.backends import MemoryScope, scoped_key

global_key = scoped_key(MemoryScope.GLOBAL, "settings")     # "global:settings"
agent_key = scoped_key(MemoryScope.AGENT, "session:123")     # "agent:session:123"
shared_key = scoped_key(MemoryScope.SHARED, "team-context")  # "shared:team-context"
```

## Integration with SessionManager

`InMemorySessionManager` accepts an optional `backend` argument for persistence:

```python
from swarmline.session.manager import InMemorySessionManager
from swarmline.session.backends import SqliteSessionBackend

backend = SqliteSessionBackend(db_path="sessions.db")
manager = InMemorySessionManager(backend=backend)

# SessionManager syncs state to backend on register() and close()
```

Without a backend argument, SessionManager works as before (in-memory only).

## Custom Backends

Implement the `SessionBackend` protocol to add Redis, PostgreSQL, or any other storage:

```python
class RedisSessionBackend:
    def __init__(self, redis_url: str):
        self._redis = Redis.from_url(redis_url)

    async def save(self, key: str, state: dict[str, Any]) -> None:
        await self._redis.set(key, json.dumps(state))

    async def load(self, key: str) -> dict[str, Any] | None:
        data = await self._redis.get(key)
        return json.loads(data) if data else None

    async def delete(self, key: str) -> bool:
        return await self._redis.delete(key) > 0

    async def list_keys(self) -> list[str]:
        return [k.decode() for k in await self._redis.keys("*")]
```
