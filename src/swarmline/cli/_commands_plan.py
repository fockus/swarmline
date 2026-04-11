"""Plan CLI commands."""

from __future__ import annotations

from typing import Optional

import click

from swarmline.cli._app import _print_result, _run_async


@click.group()
@click.pass_context
def plan(ctx: click.Context) -> None:
    """Manage agent plans (create, approve, track steps)."""


@plan.command()
@click.argument("goal")
@click.option(
    "--steps",
    "-s",
    multiple=True,
    required=True,
    help="Step descriptions (repeat for each step)",
)
@click.option("--user-id", default="default", help="User namespace")
@click.option("--topic-id", default="default", help="Topic namespace")
@click.pass_context
def create(
    ctx: click.Context, goal: str, steps: tuple[str, ...], user_id: str, topic_id: str
) -> None:
    """Create a new plan with a goal and steps."""
    from swarmline.mcp._session import StatefulSession
    from swarmline.mcp._tools_plans import plan_create

    session = StatefulSession(mode="headless")
    result = _run_async(plan_create(session, goal, list(steps), user_id, topic_id))
    _print_result(ctx, result)


@plan.command(name="get")
@click.argument("plan_id")
@click.pass_context
def get_plan(ctx: click.Context, plan_id: str) -> None:
    """Load a plan by its ID."""
    from swarmline.mcp._session import StatefulSession
    from swarmline.mcp._tools_plans import plan_get

    session = StatefulSession(mode="headless")
    result = _run_async(plan_get(session, plan_id))
    _print_result(ctx, result)


@plan.command(name="list")
@click.option("--user-id", default="default", help="User namespace")
@click.option("--topic-id", default="default", help="Topic namespace")
@click.pass_context
def list_plans(ctx: click.Context, user_id: str, topic_id: str) -> None:
    """List all plans in the given namespace."""
    from swarmline.mcp._session import StatefulSession
    from swarmline.mcp._tools_plans import plan_list

    session = StatefulSession(mode="headless")
    result = _run_async(plan_list(session, user_id, topic_id))
    _print_result(ctx, result)


@plan.command()
@click.argument("plan_id")
@click.option("--approved-by", default="user", help="Approver identity")
@click.pass_context
def approve(ctx: click.Context, plan_id: str, approved_by: str) -> None:
    """Approve a draft plan."""
    from swarmline.mcp._session import StatefulSession
    from swarmline.mcp._tools_plans import plan_approve

    session = StatefulSession(mode="headless")
    result = _run_async(plan_approve(session, plan_id, approved_by))
    _print_result(ctx, result)


@plan.command()
@click.argument("plan_id")
@click.argument("step_id")
@click.option(
    "--status",
    required=True,
    type=click.Choice(["in_progress", "completed", "failed", "skipped"]),
)
@click.option("--result", "result_text", default=None, help="Step result description")
@click.pass_context
def step(
    ctx: click.Context,
    plan_id: str,
    step_id: str,
    status: str,
    result_text: Optional[str],
) -> None:
    """Update a step within a plan."""
    from swarmline.mcp._session import StatefulSession
    from swarmline.mcp._tools_plans import plan_update_step

    session = StatefulSession(mode="headless")
    result = _run_async(
        plan_update_step(session, plan_id, step_id, status, result_text)
    )
    _print_result(ctx, result)
