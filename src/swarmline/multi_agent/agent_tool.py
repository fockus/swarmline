"""Agent-as-tool: expose a runtime as a callable tool for other agents.

Provides two functions:
- execute_agent_tool: run an agent runtime and collect the final result
- create_agent_tool_spec: build a ToolSpec for an agent-as-tool
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from swarmline.multi_agent.types import AgentToolResult
from swarmline.runtime.types import ToolSpec, Message


async def execute_agent_tool(
    run_fn: Callable[..., Any],
    query: str,
    system_prompt: str = "You are a helpful assistant.",
    timeout_seconds: float = 60.0,
) -> AgentToolResult:
    """Execute an agent runtime as a tool, collecting final result.

    Args:
        run_fn: Async generator function with signature
            (messages, system_prompt, active_tools) -> AsyncIterator[RuntimeEvent].
        query: User query to send to the sub-agent.
        system_prompt: System prompt for the sub-agent.
        timeout_seconds: Maximum execution time before timeout.

    Returns:
        AgentToolResult with success/failure and output text.
    """
    messages = [Message(role="user", content=query)]

    async def _run() -> str:
        final_text = ""
        final_seen = False
        async for event in run_fn(
            messages=messages,
            system_prompt=system_prompt,
            active_tools=[],
        ):
            if event.is_error:
                error_message = event.data.get("message") or "Sub-agent runtime failed"
                raise RuntimeError(error_message)
            if event.is_final:
                final_text = event.text or ""
                final_seen = True
                break
        if not final_seen:
            raise RuntimeError("Sub-agent runtime ended without a final event")
        return final_text

    try:
        final_text = await asyncio.wait_for(_run(), timeout=timeout_seconds)
        return AgentToolResult(success=True, output=final_text)
    except asyncio.TimeoutError:
        return AgentToolResult(success=False, output="", error="Timeout exceeded")
    except Exception as e:
        return AgentToolResult(success=False, output="", error=str(e))


def create_agent_tool_spec(name: str, description: str) -> ToolSpec:
    """Create a ToolSpec for an agent-as-tool.

    Args:
        name: Tool name visible to the orchestrating agent.
        description: Tool description for the LLM.

    Returns:
        ToolSpec with a single required 'query' string parameter.
    """
    return ToolSpec(
        name=name,
        description=description,
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The query to send to the sub-agent",
                },
            },
            "required": ["query"],
        },
        is_local=True,
    )
