"""Session persistence and memory scopes.

Demonstrates: InMemorySessionBackend, SqliteSessionBackend, MemoryScope, scoped_key.
No API keys required.
"""

import asyncio

from swarmline.session.backends import InMemorySessionBackend, MemoryScope, scoped_key


async def main() -> None:
    backend = InMemorySessionBackend()

    # 1. Scoped keys -- namespace isolation
    global_key = scoped_key(MemoryScope.GLOBAL, "app:config")
    agent_key = scoped_key(MemoryScope.AGENT, "user:42:session:abc")
    shared_key = scoped_key(MemoryScope.SHARED, "team:alpha:context")

    print("Scoped keys:")
    print(f"  GLOBAL: {global_key}")
    print(f"  AGENT:  {agent_key}")
    print(f"  SHARED: {shared_key}")

    # 2. Save and load session data
    await backend.save(agent_key, {"turn": 7, "role": "coach", "model": "sonnet"})
    await backend.save(global_key, {"default_model": "sonnet", "max_turns": 50})

    loaded = await backend.load(agent_key)
    print(f"\nLoaded agent session: {loaded}")

    global_data = await backend.load(global_key)
    print(f"Loaded global config: {global_data}")

    # 3. Update existing session
    await backend.save(agent_key, {"turn": 8, "role": "coach", "model": "sonnet"})
    updated = await backend.load(agent_key)
    print(f"\nUpdated session (turn 8): {updated}")

    # 4. Delete session
    await backend.delete(agent_key)
    deleted = await backend.load(agent_key)
    print(f"After delete: {deleted}")

    # 5. SqliteSessionBackend (persistent, same API)
    # from swarmline.session.backends import SqliteSessionBackend
    # sqlite_backend = SqliteSessionBackend(db_path="sessions.db")
    # await sqlite_backend.save(agent_key, {"turn": 1})
    # data = await sqlite_backend.load(agent_key)


if __name__ == "__main__":
    asyncio.run(main())
