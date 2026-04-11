"""Memory providers: persist messages, facts, goals, and summaries.

Demonstrates: InMemoryMemoryProvider with full CRUD operations.
No API keys required.
"""

import asyncio

from swarmline.memory.inmemory import InMemoryMemoryProvider


async def main() -> None:
    provider = InMemoryMemoryProvider()
    user_id = "user-1"
    topic_id = "project-alpha"

    # --- 1. Messages ---
    print("=== Messages ===")
    await provider.save_message(user_id, topic_id, "user", "How do I use asyncio?")
    await provider.save_message(user_id, topic_id, "assistant", "asyncio is Python's async framework...")
    await provider.save_message(user_id, topic_id, "user", "Show me an example")

    messages = await provider.get_messages(user_id, topic_id, limit=10)
    print(f"Stored {await provider.count_messages(user_id, topic_id)} messages:")
    for msg in messages:
        print(f"  {msg.role}: {msg.content[:50]}")

    # --- 2. Facts (key-value, global or per-topic) ---
    print("\n=== Facts ===")
    await provider.upsert_fact(user_id, "language", "Python", source="user")
    await provider.upsert_fact(user_id, "framework", "FastAPI", topic_id=topic_id, source="inferred")
    await provider.upsert_fact(user_id, "experience", "senior", source="user")

    facts = await provider.get_facts(user_id)
    print(f"Global facts: {facts}")

    topic_facts = await provider.get_facts(user_id, topic_id=topic_id)
    print(f"Topic facts: {topic_facts}")

    # --- 3. Summaries ---
    print("\n=== Summaries ===")
    await provider.save_summary(
        user_id, topic_id,
        summary="User is learning asyncio for a FastAPI project.",
        messages_covered=3,
    )
    summary = await provider.get_summary(user_id, topic_id)
    print(f"Summary: {summary}")

    # --- 4. Goals ---
    print("\n=== Goals ===")
    from swarmline.memory.types import GoalState

    # Note: save_goal stores by (user_id, goal.goal_id) key,
    # get_active_goal retrieves by (user_id, topic_id) key.
    # Use topic_id as goal_id so they match.
    goal = GoalState(
        goal_id=topic_id,
        title="Build a REST API with FastAPI",
        target_amount=100,
        current_amount=0,
        phase="planning",
    )
    await provider.save_goal(user_id, goal)
    active = await provider.get_active_goal(user_id, topic_id)
    print(f"Active goal: {active.title if active else 'none'}")

    # --- 5. Session state ---
    print("\n=== Session State ===")
    await provider.save_session_state(
        user_id, topic_id,
        role_id="developer",
        active_skill_ids=["code", "debug"],
    )
    state = await provider.get_session_state(user_id, topic_id)
    print(f"Session state: role={state.get('role_id')}, skills={state.get('active_skill_ids')}")

    # --- 6. Message cleanup ---
    print("\n=== Cleanup ===")
    deleted = await provider.delete_messages_before(user_id, topic_id, keep_last=1)
    print(f"Deleted {deleted} old messages, kept last 1")
    remaining = await provider.count_messages(user_id, topic_id)
    print(f"Remaining: {remaining}")


if __name__ == "__main__":
    asyncio.run(main())
