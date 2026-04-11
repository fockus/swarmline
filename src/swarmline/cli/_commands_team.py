"""Team coordination CLI commands."""

from __future__ import annotations

import click

from swarmline.cli._app import _print_result, _run_async


@click.group()
@click.pass_context
def team(ctx: click.Context) -> None:
    """Manage agent teams (register agents, create/claim tasks)."""


@team.command()
@click.argument("id")
@click.argument("name")
@click.argument("role")
@click.option("--parent-id", default=None, help="Parent agent ID")
@click.option("--runtime", "runtime_name", default="thin", help="Runtime name")
@click.pass_context
def register(
    ctx: click.Context,
    id: str,
    name: str,
    role: str,
    parent_id: str | None,
    runtime_name: str,
) -> None:
    """Register an agent in the team registry."""
    from swarmline.mcp._session import StatefulSession
    from swarmline.mcp._tools_team import team_register_agent

    session = StatefulSession(mode="headless")
    result = _run_async(
        team_register_agent(session, id, name, role, parent_id, runtime_name)
    )
    _print_result(ctx, result)


@team.command()
@click.option("--role", default=None, help="Filter by role")
@click.option("--status", default=None, help="Filter by status")
@click.pass_context
def agents(ctx: click.Context, role: str | None, status: str | None) -> None:
    """List registered agents."""
    from swarmline.mcp._session import StatefulSession
    from swarmline.mcp._tools_team import team_list_agents

    session = StatefulSession(mode="headless")
    result = _run_async(team_list_agents(session, role, status))
    _print_result(ctx, result)


@team.command()
@click.argument("id")
@click.argument("title")
@click.option("--description", default="", help="Task description")
@click.option(
    "--priority",
    default="MEDIUM",
    type=click.Choice(["LOW", "MEDIUM", "HIGH", "CRITICAL"], case_sensitive=False),
)
@click.option(
    "--assignee", "assignee_agent_id", default=None, help="Assign to agent ID"
)
@click.pass_context
def task(
    ctx: click.Context,
    id: str,
    title: str,
    description: str,
    priority: str,
    assignee_agent_id: str | None,
) -> None:
    """Create a task in the team queue."""
    from swarmline.mcp._session import StatefulSession
    from swarmline.mcp._tools_team import team_create_task

    session = StatefulSession(mode="headless")
    result = _run_async(
        team_create_task(session, id, title, description, priority, assignee_agent_id)
    )
    _print_result(ctx, result)


@team.command()
@click.option(
    "--assignee", "assignee_agent_id", default=None, help="Claim for specific agent"
)
@click.pass_context
def claim(ctx: click.Context, assignee_agent_id: str | None) -> None:
    """Claim the highest-priority available task."""
    from swarmline.mcp._session import StatefulSession
    from swarmline.mcp._tools_team import team_claim_task

    session = StatefulSession(mode="headless")
    result = _run_async(team_claim_task(session, assignee_agent_id))
    _print_result(ctx, result)


@team.command()
@click.option("--status", default=None, help="Filter by status")
@click.option("--priority", default=None, help="Filter by priority")
@click.option(
    "--assignee", "assignee_agent_id", default=None, help="Filter by assignee"
)
@click.pass_context
def tasks(
    ctx: click.Context,
    status: str | None,
    priority: str | None,
    assignee_agent_id: str | None,
) -> None:
    """List tasks with optional filters."""
    from swarmline.mcp._session import StatefulSession
    from swarmline.mcp._tools_team import team_list_tasks

    session = StatefulSession(mode="headless")
    result = _run_async(team_list_tasks(session, status, priority, assignee_agent_id))
    _print_result(ctx, result)
