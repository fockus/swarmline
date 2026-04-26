"""Hello-world swarmline agent — the smallest possible example.

Runs offline by default via swarmline.testing.MockRuntime — no API key needed.
Pass ``--live`` with ``ANTHROPIC_API_KEY`` set to use the real ``thin`` runtime.
"""

from __future__ import annotations

import asyncio
import os
import sys

from swarmline import Agent, AgentConfig
from swarmline.testing import MockRuntime


async def main() -> None:
    if "--live" in sys.argv:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("ANTHROPIC_API_KEY is required for --live mode")
        runtime = "thin"
    else:
        MockRuntime.register_default()
        runtime = MockRuntime.NAME

    agent = Agent(AgentConfig(system_prompt="You are a helpful assistant.", runtime=runtime))
    result = await agent.query("What is the capital of France?")
    print(result.text)


if __name__ == "__main__":
    asyncio.run(main())
