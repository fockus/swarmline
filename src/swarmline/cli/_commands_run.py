"""Code execution CLI command."""

from __future__ import annotations

import click

from swarmline.cli._app import _print_result, _run_async


@click.command()
@click.argument("code")
@click.option("--timeout", default=30, type=int, help="Execution timeout in seconds")
@click.pass_context
def run(ctx: click.Context, code: str, timeout: int) -> None:
    """Execute Python code in an isolated subprocess."""
    from swarmline.mcp._tools_code import exec_code

    result = _run_async(exec_code(code, timeout, trusted=True))
    _print_result(ctx, result)
