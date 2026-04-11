"""Agent-as-tool: one agent calls another agent as a tool.

Demonstrates: create_agent_tool_spec, execute_agent_tool, AgentToolResult.
No API keys required (uses mock runtime).
"""

import asyncio
from collections.abc import AsyncIterator

from swarmline.multi_agent.agent_tool import (
    AgentToolResult,
    create_agent_tool_spec,
    execute_agent_tool,
)
from swarmline.runtime.types import Message, RuntimeEvent, ToolSpec


# --- Mock runtime that simulates an expert agent ---

async def mock_expert_run(
    *,
    messages: list[Message],
    system_prompt: str,
    active_tools: list[ToolSpec],
    **kwargs,
) -> AsyncIterator[RuntimeEvent]:
    """Simulate an expert agent responding to queries."""
    query = messages[-1].content if messages else "no query"
    response = f"Expert analysis: '{query}' -- The answer is 42."
    yield RuntimeEvent.assistant_delta(text=response)
    yield RuntimeEvent.final(text=response, new_messages=[])


async def main() -> None:
    # 1. Create a tool spec for the expert agent
    print("=== Agent Tool Spec ===")
    spec = create_agent_tool_spec(
        name="math_expert",
        description="Ask a math expert agent to solve a problem.",
    )
    print(f"Tool: {spec.name}")
    print(f"Description: {spec.description}")
    print(f"Parameters: {spec.parameters}")

    # 2. Execute agent as tool
    print("\n=== Execute Agent Tool ===")
    result: AgentToolResult = await execute_agent_tool(
        run_fn=mock_expert_run,
        query="What is the integral of x^2?",
        system_prompt="You are a math expert.",
        timeout_seconds=10.0,
    )
    print(f"Success: {result.success}")
    print(f"Output: {result.output}")
    print(f"Error: {result.error}")

    # 3. Handle timeout/errors gracefully
    print("\n=== Error Handling ===")

    async def failing_run(**kwargs) -> AsyncIterator[RuntimeEvent]:
        raise RuntimeError("Agent crashed!")
        yield  # type: ignore  # make it an async generator

    error_result = await execute_agent_tool(
        run_fn=failing_run,
        query="This will fail",
        timeout_seconds=5.0,
    )
    print(f"Success: {error_result.success}")
    print(f"Error: {error_result.error}")

    # 4. Multi-agent composition pattern
    print("\n=== Multi-Agent Pattern ===")
    print("# Orchestrator agent has tools:")
    print("#   - math_expert (agent-as-tool)")
    print("#   - code_reviewer (agent-as-tool)")
    print("#   - get_weather (regular tool)")
    print("#")
    print("# When the LLM calls 'math_expert', the orchestrator:")
    print("#   1. Creates a sub-agent runtime")
    print("#   2. Runs execute_agent_tool() with the query")
    print("#   3. Returns AgentToolResult.output as the tool result")


if __name__ == "__main__":
    asyncio.run(main())
