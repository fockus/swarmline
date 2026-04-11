"""Agent CLI commands (full mode only)."""

from __future__ import annotations

import click

from swarmline.cli._app import _print_result, _run_async


@click.group()
@click.pass_context
def agent(ctx: click.Context) -> None:
    """Manage LLM agents (create, query, list). Requires API key."""


@agent.command()
@click.option("--prompt", "-p", required=True, help="System prompt for the agent")
@click.option("--model", "-m", default="sonnet", help="Model alias")
@click.option("--runtime", default="thin", help="Runtime name")
@click.option("--max-turns", default=None, type=int, help="Max conversation turns")
@click.pass_context
def create(
    ctx: click.Context, prompt: str, model: str, runtime: str, max_turns: int | None
) -> None:
    """Create a new LLM-powered agent."""
    from swarmline.mcp._session import StatefulSession, resolve_mode

    session = StatefulSession(mode=resolve_mode("auto"))
    from swarmline.mcp._tools_agent import agent_create

    result = _run_async(agent_create(session, prompt, model, runtime, max_turns))
    _print_result(ctx, result)


@agent.command()
@click.argument("agent_id")
@click.argument("prompt")
@click.pass_context
def query(ctx: click.Context, agent_id: str, prompt: str) -> None:
    """Send a prompt to an existing agent."""
    from swarmline.mcp._session import StatefulSession, resolve_mode

    session = StatefulSession(mode=resolve_mode("auto"))
    from swarmline.mcp._tools_agent import agent_query

    result = _run_async(agent_query(session, agent_id, prompt))
    _print_result(ctx, result)


@agent.command(name="list")
@click.pass_context
def list_agents(ctx: click.Context) -> None:
    """List all created agents."""
    from swarmline.mcp._session import StatefulSession, resolve_mode

    session = StatefulSession(mode=resolve_mode("auto"))
    from swarmline.mcp._tools_agent import agent_list

    result = _run_async(agent_list(session))
    _print_result(ctx, result)
