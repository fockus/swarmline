#!/usr/bin/env python3
"""Example: Expose a Swarmline Agent as an A2A service + call it as a client.

Demonstrates the A2A (Agent-to-Agent) protocol: server discovery,
task send, and task lifecycle — all in-process with a mock agent.

No API keys required. No external HTTP server.

Requires: pip install swarmline[a2a]
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from swarmline.a2a.adapter import SwarmlineA2AAdapter
from swarmline.a2a.server import A2AServer
from swarmline.a2a.types import AgentSkill, Message, Task, TextPart
from swarmline.agent.result import Result


def _mock_agent() -> MagicMock:
    """Create a mock agent that returns canned responses."""
    agent = MagicMock()

    async def fake_query(prompt: str) -> Result:
        return Result(text=f"A2A response to: {prompt}")

    agent.query = AsyncMock(side_effect=fake_query)
    return agent


async def main() -> None:
    # 1. Create a mock Swarmline Agent
    agent = _mock_agent()

    # 2. Wrap it as an A2A service
    adapter = SwarmlineA2AAdapter(
        agent,
        name="ResearchBot",
        description="A research assistant powered by Swarmline",
        url="http://localhost:8000",
        skills=[
            AgentSkill(
                id="research",
                name="Web Research",
                description="Search and summarize web content",
                tags=["research", "search"],
            ),
            AgentSkill(
                id="summarize",
                name="Summarize",
                description="Summarize long documents",
                tags=["nlp", "summarize"],
            ),
        ],
    )

    # 3. Check the AgentCard (what other agents see at /.well-known/agent.json)
    card = adapter.agent_card
    print("=== Agent Card ===")
    print(f"  Name: {card.name}")
    print(f"  URL: {card.url}")
    print(f"  Skills: {[s.name for s in card.skills]}")
    print(f"  Streaming: {card.capabilities.streaming}")
    print()

    # 4. Send a task (non-streaming)
    print("=== Send Task ===")
    task = Task(
        id="demo-task-1",
        messages=[
            Message(
                role="user",
                parts=[TextPart(text="What are the latest trends in AI agents?")],
            )
        ],
    )
    result = await adapter.handle_task(task)
    print(f"  Task ID: {result.id}")
    print(f"  Status: {result.status.state.value}")
    if result.messages:
        last_msg = result.messages[-1]
        if last_msg.parts:
            text = last_msg.parts[0].text if hasattr(last_msg.parts[0], "text") else "N/A"
            print(f"  Response: {text}")
    print()

    # 5. Streaming task
    print("=== Streaming Task ===")
    stream_task = Task(
        id="demo-task-2",
        messages=[
            Message(role="user", parts=[TextPart(text="Summarize quantum computing")])
        ],
    )
    async for event in adapter.handle_task_streaming(stream_task):
        print(f"  Event: state={event.status.state.value}, final={event.final}")
    print()

    # 6. Retrieve a task
    found = adapter.get_task("demo-task-1")
    print(f"=== Get Task ===")
    print(f"  Found task: {found is not None}")
    print(f"  State: {found.status.state.value if found else 'N/A'}")

    print("\nAll A2A examples completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
