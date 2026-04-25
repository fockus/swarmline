"""Status command for quick runtime and environment introspection."""

from __future__ import annotations

import platform
from typing import Any

import click

from swarmline.cli._app import _print_result

PUBLIC_RUNTIMES = ["thin", "claude_sdk", "deepagents", "cli", "openai_agents", "pi_sdk"]
INTERNAL_MODES = ["headless"]


@click.command(name="status")
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show Swarmline package, Python, and runtime status."""
    from swarmline import __version__
    from swarmline.runtime.registry import get_default_registry

    registry = get_default_registry()
    available = sorted(registry.list_available())
    data: dict[str, Any] = {
        "version": __version__,
        "python": platform.python_version(),
        "public_runtimes": PUBLIC_RUNTIMES,
        "internal_modes": INTERNAL_MODES,
        "registered_runtimes": available,
    }
    _print_result(ctx, {"ok": True, "data": data})
