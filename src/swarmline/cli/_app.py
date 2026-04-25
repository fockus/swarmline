"""Swarmline CLI application."""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import click
import structlog

from swarmline.cli._output import format_output


def _configure_logging_to_stderr() -> None:
    """Route structlog output to stderr so stdout stays clean for command output."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def _run_async(coro: Any) -> Any:
    """Run async coroutine from sync Click command."""
    return asyncio.run(coro)


@click.group()
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["auto", "json", "text"]),
    default="auto",
    help="Output format",
)
@click.pass_context
def cli(ctx: click.Context, fmt: str) -> None:
    """Swarmline -- AI Agent Framework CLI."""
    _configure_logging_to_stderr()
    ctx.ensure_object(dict)
    ctx.obj["fmt"] = fmt


def _print_result(ctx: click.Context, result: dict[str, Any]) -> None:
    """Print tool result with format from context."""
    fmt = ctx.obj.get("fmt", "auto")
    click.echo(format_output(result, fmt))
    if not result.get("ok", True):
        ctx.exit(2)


# Register subcommand groups -- lazy imports to keep click as only top-level dep
from swarmline.cli._commands_memory import memory  # noqa: E402
from swarmline.cli._commands_plan import plan  # noqa: E402
from swarmline.cli._commands_team import team  # noqa: E402
from swarmline.cli._commands_agent import agent  # noqa: E402
from swarmline.cli._commands_run import run  # noqa: E402
from swarmline.cli._commands_mcp import mcp_serve  # noqa: E402
from swarmline.cli._commands_status import status  # noqa: E402
from swarmline.cli.init_cmd import init_command  # noqa: E402

cli.add_command(memory)
cli.add_command(plan)
cli.add_command(team)
cli.add_command(agent)
cli.add_command(run)
cli.add_command(mcp_serve)
cli.add_command(status)
cli.add_command(init_command, name="init")


if __name__ == "__main__":
    cli()
