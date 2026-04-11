"""Memory CLI commands."""

from __future__ import annotations

import click

from swarmline.cli._app import _print_result, _run_async


@click.group()
@click.pass_context
def memory(ctx: click.Context) -> None:
    """Manage agent memory (facts, messages, summaries)."""


@memory.command()
@click.argument("user_id")
@click.argument("key")
@click.argument("value")
@click.option("--topic-id", default=None, help="Topic scope")
@click.pass_context
def upsert(
    ctx: click.Context, user_id: str, key: str, value: str, topic_id: str | None
) -> None:
    """Store or update a fact."""
    from swarmline.mcp._session import StatefulSession
    from swarmline.mcp._tools_memory import memory_upsert_fact

    session = StatefulSession(mode="headless")
    result = _run_async(memory_upsert_fact(session, user_id, key, value, topic_id))
    _print_result(ctx, result)


@memory.command(name="get")
@click.argument("user_id")
@click.option("--topic-id", default=None, help="Topic scope")
@click.pass_context
def get_facts(ctx: click.Context, user_id: str, topic_id: str | None) -> None:
    """Get all facts for a user."""
    from swarmline.mcp._session import StatefulSession
    from swarmline.mcp._tools_memory import memory_get_facts

    session = StatefulSession(mode="headless")
    result = _run_async(memory_get_facts(session, user_id, topic_id))
    _print_result(ctx, result)


@memory.command()
@click.argument("user_id")
@click.argument("topic_id")
@click.option("--limit", default=10, help="Max messages")
@click.pass_context
def messages(ctx: click.Context, user_id: str, topic_id: str, limit: int) -> None:
    """Get recent messages from a conversation."""
    from swarmline.mcp._session import StatefulSession
    from swarmline.mcp._tools_memory import memory_get_messages

    session = StatefulSession(mode="headless")
    result = _run_async(memory_get_messages(session, user_id, topic_id, limit))
    _print_result(ctx, result)
