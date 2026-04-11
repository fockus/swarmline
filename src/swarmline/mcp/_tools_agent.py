"""Agent tools for Swarmline MCP server (full mode only).

These tools require an LLM API key (ANTHROPIC_API_KEY or OPENAI_API_KEY).
In headless mode, they return a clear error message.
"""

from __future__ import annotations

from typing import Any

import structlog

from swarmline.mcp._session import StatefulSession

logger = structlog.get_logger(__name__)


async def agent_create(
    session: StatefulSession,
    system_prompt: str,
    model: str = "sonnet",
    runtime: str = "thin",
    max_turns: int | None = None,
) -> dict[str, Any]:
    """Create a new LLM-powered agent. Requires full mode."""
    try:
        agent_id = await session.create_agent(
            system_prompt=system_prompt,
            model=model,
            runtime=runtime,
            max_turns=max_turns,
        )
        return {
            "ok": True,
            "data": {"agent_id": agent_id, "model": model, "runtime": runtime},
        }
    except Exception as exc:
        logger.warning("agent_create_failed", error=str(exc))
        return {"ok": False, "error": str(exc)}


async def agent_query(
    session: StatefulSession,
    agent_id: str,
    prompt: str,
) -> dict[str, Any]:
    """Send a prompt to an existing agent. Requires full mode."""
    try:
        result = await session.query_agent(agent_id, prompt)
        return {
            "ok": result.ok,
            "data": {
                "text": result.text,
                "agent_id": agent_id,
                "error": result.error,
            },
        }
    except Exception as exc:
        logger.warning("agent_query_failed", error=str(exc))
        return {"ok": False, "error": str(exc)}


async def agent_list(session: StatefulSession) -> dict[str, Any]:
    """List all created agents."""
    try:
        agents = session.list_agents()
        return {"ok": True, "data": agents}
    except Exception as exc:
        logger.warning("agent_list_failed", error=str(exc))
        return {"ok": False, "error": str(exc)}
