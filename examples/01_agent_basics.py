"""Agent basics: query, stream, and multi-turn conversation.

Demonstrates: Agent, AgentConfig, query(), stream(), conversation().
Runs offline by default via swarmline.testing.MockRuntime — no API key needed.
Pass ``--live`` with ``ANTHROPIC_API_KEY`` to use the real ``thin`` runtime.
"""

from __future__ import annotations

import asyncio
import os
import sys

from swarmline import Agent, AgentConfig
from swarmline.testing import MockRuntime


def _runtime_name() -> str:
    if "--live" in sys.argv:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("ANTHROPIC_API_KEY is required for --live mode")
        return "thin"
    MockRuntime.register_default()
    return MockRuntime.NAME


async def main() -> None:
    runtime = _runtime_name()

    # --- 1. One-shot query ---
    agent = Agent(
        AgentConfig(
            system_prompt="You are a helpful assistant. Reply concisely.",
            runtime=runtime,
            model="sonnet",
        )
    )
    result = await agent.query("What is the capital of France?")
    print(f"Query result: {result.text}")
    print(f"Session ID: {result.session_id}")
    if result.usage:
        print(f"Tokens used: {result.usage}")

    # --- 2. Streaming response ---
    print("\nStreaming:")
    async for event in agent.stream("Write a haiku about Python"):
        if event.type == "text_delta":
            print(event.text, end="", flush=True)
        elif event.type == "tool_use_start":
            print(f"\n[Tool: {event.tool_name}]")
    print()

    # --- 3. Multi-turn conversation ---
    print("\nConversation:")
    async with agent.conversation() as conv:
        r1 = await conv.say("My name is Alice")
        print(f"Turn 1: {r1.text}")
        r2 = await conv.say("What's my name?")
        print(f"Turn 2: {r2.text}")
        print("Turn 3 (stream): ", end="")
        async for event in conv.stream("Tell me a one-line joke"):
            if event.type == "text_delta":
                print(event.text, end="", flush=True)
        print()

    # --- 4. Context manager cleanup ---
    async with Agent(
        AgentConfig(system_prompt="You are a math tutor.", runtime=runtime)
    ) as math_agent:
        r = await math_agent.query("What is 17 * 23?")
        print(f"\nMath: {r.text}")


if __name__ == "__main__":
    asyncio.run(main())
