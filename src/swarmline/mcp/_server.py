"""Swarmline MCP Server -- FastMCP-based STDIO server.

Entry points:
    swarmline-mcp          -> main()
    python -m swarmline.mcp -> main()

Modes:
    headless (default): memory, plans, team (0 LLM calls)
    full: + agent creation/querying (needs API key)
    auto: detects API keys -> full if found, else headless
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

import structlog

from swarmline.mcp._session import StatefulSession, resolve_mode
from swarmline.mcp._tools_agent import agent_create, agent_list, agent_query
from swarmline.mcp._tools_code import exec_code
from swarmline.mcp._tools_memory import (
    memory_get_facts,
    memory_get_messages,
    memory_get_summary,
    memory_save_message,
    memory_save_summary,
    memory_upsert_fact,
)
from swarmline.mcp._tools_plans import (
    plan_approve,
    plan_create,
    plan_get,
    plan_list,
    plan_update_step,
)
from swarmline.mcp._tools_team import (
    team_claim_task,
    team_create_task,
    team_list_agents,
    team_list_tasks,
    team_register_agent,
)

logger = structlog.get_logger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse swarmline-mcp arguments.

    Supports the legacy positional mode and the newer ``--mode`` flag.
    """
    parser = argparse.ArgumentParser(
        prog="swarmline-mcp",
        description="Start the Swarmline MCP server over stdio.",
    )
    parser.add_argument(
        "positional_mode",
        nargs="?",
        choices=("auto", "headless", "full"),
        help="Server mode (legacy positional form).",
    )
    parser.add_argument(
        "--mode",
        choices=("auto", "headless", "full"),
        help="Server mode.",
    )
    args = parser.parse_args(argv)
    if args.positional_mode and args.mode and args.positional_mode != args.mode:
        parser.error("positional mode and --mode must match when both are provided")
    args.mode = args.mode or args.positional_mode or "auto"
    delattr(args, "positional_mode")
    return args


def create_server(*, mode: str = "auto", enable_host_exec: bool = False) -> Any:
    """Create and configure the Swarmline MCP server.

    Returns a FastMCP instance with all tools registered.
    Lazy-imports fastmcp to keep it optional.
    """
    try:
        from fastmcp import FastMCP  # ty: ignore[unresolved-import]  # optional dep
    except ImportError as exc:
        raise ImportError(
            "FastMCP is required for the MCP server. "
            "Install it with: pip install swarmline[mcp]"
        ) from exc

    resolved = resolve_mode(mode)
    session = StatefulSession(mode=resolved)

    mcp = FastMCP(
        "swarmline",
        description=(
            "Swarmline AI Agent Framework -- memory, plans, team coordination, "
            "and agent orchestration for code agents."
        ),
    )

    # --- Memory tools (headless) ---

    @mcp.tool()
    async def swarmline_memory_upsert_fact(
        user_id: str, key: str, value: str, topic_id: str | None = None
    ) -> dict[str, Any]:
        """Store or update a key-value fact in agent memory."""
        return await memory_upsert_fact(session, user_id, key, value, topic_id)

    @mcp.tool()
    async def swarmline_memory_get_facts(
        user_id: str, topic_id: str | None = None
    ) -> dict[str, Any]:
        """Retrieve all facts for a user/namespace."""
        return await memory_get_facts(session, user_id, topic_id)

    @mcp.tool()
    async def swarmline_memory_save_message(
        user_id: str, topic_id: str, role: str, content: str
    ) -> dict[str, Any]:
        """Save a conversation message to memory."""
        return await memory_save_message(session, user_id, topic_id, role, content)

    @mcp.tool()
    async def swarmline_memory_get_messages(
        user_id: str, topic_id: str, limit: int = 10
    ) -> dict[str, Any]:
        """Get recent messages from a conversation."""
        return await memory_get_messages(session, user_id, topic_id, limit)

    @mcp.tool()
    async def swarmline_memory_save_summary(
        user_id: str, topic_id: str, summary: str, messages_covered: int = 0
    ) -> dict[str, Any]:
        """Save a conversation summary."""
        return await memory_save_summary(
            session, user_id, topic_id, summary, messages_covered
        )

    @mcp.tool()
    async def swarmline_memory_get_summary(
        user_id: str, topic_id: str
    ) -> dict[str, Any]:
        """Get the conversation summary."""
        return await memory_get_summary(session, user_id, topic_id)

    # --- Plan tools (headless) ---

    @mcp.tool()
    async def swarmline_plan_create(
        goal: str, steps: list[str], user_id: str = "default", topic_id: str = "default"
    ) -> dict[str, Any]:
        """Create a new plan with goal and steps."""
        return await plan_create(session, goal, steps, user_id, topic_id)

    @mcp.tool()
    async def swarmline_plan_get(plan_id: str) -> dict[str, Any]:
        """Load a plan by its ID."""
        return await plan_get(session, plan_id)

    @mcp.tool()
    async def swarmline_plan_list(
        user_id: str = "default", topic_id: str = "default"
    ) -> dict[str, Any]:
        """List all plans in a namespace."""
        return await plan_list(session, user_id, topic_id)

    @mcp.tool()
    async def swarmline_plan_approve(
        plan_id: str, approved_by: str = "user"
    ) -> dict[str, Any]:
        """Approve a draft plan for execution."""
        return await plan_approve(session, plan_id, approved_by)

    @mcp.tool()
    async def swarmline_plan_update_step(
        plan_id: str, step_id: str, status: str, result: str | None = None
    ) -> dict[str, Any]:
        """Update a plan step's status and optional result."""
        return await plan_update_step(session, plan_id, step_id, status, result)

    # --- Team tools (headless) ---

    @mcp.tool()
    async def swarmline_team_register_agent(
        id: str,
        name: str,
        role: str,
        parent_id: str | None = None,
        runtime_name: str = "thin",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Register an agent in the team registry."""
        return await team_register_agent(
            session, id, name, role, parent_id, runtime_name, metadata
        )

    @mcp.tool()
    async def swarmline_team_list_agents(
        role: str | None = None, status: str | None = None
    ) -> dict[str, Any]:
        """List registered agents with optional filters."""
        return await team_list_agents(session, role, status)

    @mcp.tool()
    async def swarmline_team_create_task(
        id: str,
        title: str,
        description: str = "",
        priority: str = "MEDIUM",
        assignee_agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a task in the team task queue."""
        return await team_create_task(
            session, id, title, description, priority, assignee_agent_id
        )

    @mcp.tool()
    async def swarmline_team_claim_task(
        assignee_agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Claim the next available task from the queue."""
        return await team_claim_task(session, assignee_agent_id)

    @mcp.tool()
    async def swarmline_team_list_tasks(
        status: str | None = None,
        priority: str | None = None,
        assignee_agent_id: str | None = None,
    ) -> dict[str, Any]:
        """List tasks with optional filters."""
        return await team_list_tasks(session, status, priority, assignee_agent_id)

    # --- Code execution (host exec, opt-in only) ---

    if enable_host_exec:

        @mcp.tool()
        async def swarmline_exec_code(
            code: str, timeout_seconds: int = 30
        ) -> dict[str, Any]:
            """Execute Python code on the host in a subprocess."""
            return await exec_code(code, timeout_seconds, trusted=True)

    # --- Agent tools (full mode only) ---

    if resolved == "full":

        @mcp.tool()
        async def swarmline_agent_create(
            system_prompt: str,
            model: str = "sonnet",
            runtime: str = "thin",
            max_turns: int | None = None,
        ) -> dict[str, Any]:
            """Create a new LLM-powered agent. Requires API key."""
            return await agent_create(session, system_prompt, model, runtime, max_turns)

        @mcp.tool()
        async def swarmline_agent_query(agent_id: str, prompt: str) -> dict[str, Any]:
            """Send a prompt to an existing agent. Requires API key."""
            return await agent_query(session, agent_id, prompt)

        @mcp.tool()
        async def swarmline_agent_list() -> dict[str, Any]:
            """List all created agents with their configs."""
            return await agent_list(session)

    # --- Status tool ---

    @mcp.tool()
    async def swarmline_status() -> dict[str, Any]:
        """Get Swarmline MCP server status."""
        agents = session.list_agents()
        return {
            "ok": True,
            "data": {
                "mode": resolved,
                "agents_count": len(agents),
            },
        }

    logger.info(
        "mcp_server_created",
        mode=resolved,
        tools_count="21"
        if resolved == "full" and enable_host_exec
        else "20"
        if resolved == "full"
        else "18"
        if enable_host_exec
        else "17",
    )
    return mcp


def main() -> None:
    """Entry point for swarmline-mcp and python -m swarmline.mcp."""
    args = parse_args(sys.argv[1:])

    server = create_server(mode=args.mode)
    server.run(transport="stdio")
