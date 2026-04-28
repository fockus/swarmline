"""YAML command definitions loader.

Loads command definitions from YAML files for auto-discovery.
Supports: single file, directory scan, single-command and multi-command formats.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class LoadedCommand:
    """Command definition loaded from YAML.

    Supports both attribute access (cmd.name) and dict-like access (cmd['name'])
    for backward compatibility with code expecting a dict.
    """

    name: str
    description: str = ""
    category: str = ""
    parameters: dict[str, Any] | None = None
    aliases: list[str] = field(default_factory=list)

    def __getitem__(self, key: str) -> Any:
        """Dict-like access: cmd['name'], cmd['category']."""
        return getattr(self, key)


def _parse_yaml_data(data: Any) -> list[LoadedCommand]:
    """Parse YAML data into a list of LoadedCommand objects."""
    if not isinstance(data, dict):
        return []

    # Multi-command format: {commands: [{name: ..., ...}, ...]}
    if "commands" in data:
        commands: list[LoadedCommand] = []
        for cmd_def in data["commands"]:
            if not isinstance(cmd_def, dict) or "name" not in cmd_def:
                continue
            commands.append(
                LoadedCommand(
                    name=cmd_def["name"],
                    description=cmd_def.get("description", ""),
                    category=cmd_def.get("category", ""),
                    parameters=cmd_def.get("parameters"),
                    aliases=cmd_def.get("aliases", []),
                )
            )
        return commands

    # Single-command format: {name: ..., description: ..., ...}
    if "name" in data:
        return [
            LoadedCommand(
                name=data["name"],
                description=data.get("description", ""),
                category=data.get("category", ""),
                parameters=data.get("parameters"),
                aliases=data.get("aliases", []),
            )
        ]

    return []


def load_commands_from_yaml(
    path: str | Path,
    handler_registry: dict[str, Callable[..., Awaitable[str]]] | None = None,
) -> list[LoadedCommand]:
    """Load command definitions from a YAML file or directory.

    If path is a directory: scans all .yaml/.yml files (single-command format).
    If path is a file: supports multi-command (commands: [...]) and
    single-command (name: ...) formats.

    Args:
        path: Path to a directory or YAML file (str or Path).
        handler_registry: Reserved for compatibility with auto_discover_commands.

    Returns:
        List of LoadedCommand objects with attribute and dict-like (cmd['name']) access.
    """
    p = Path(path)

    if p.is_dir():
        results: list[LoadedCommand] = []
        for yaml_file in sorted(p.glob("*.yaml")):
            results.extend(_load_single_file(yaml_file))
        for yml_file in sorted(p.glob("*.yml")):
            results.extend(_load_single_file(yml_file))
        return results

    return _load_single_file(p)


def _load_single_file(path: Path) -> list[LoadedCommand]:
    """Load commands from a single YAML file. Returns [] on error."""
    try:
        data = yaml.safe_load(path.read_text())
    except Exception as exc:
        logger.warning("Failed to load command YAML path=%s error=%s", path, exc)
        return []
    return _parse_yaml_data(data)


def auto_discover_commands(
    registry: Any,
    directory: Path,
    handler_registry: dict[str, Callable[..., Awaitable[str]]] | None = None,
) -> int:
    """Discover and register commands from a YAML directory in CommandRegistry.

    Loads LoadedCommand objects from each .yaml/.yml file in the directory
    and registers them via registry.add().

    Args:
        registry: CommandRegistry used to register commands.
        directory: Directory with YAML files (single-command format).
        handler_registry: Optional name -> handler mapping.

    Returns:
        Number of successfully loaded and registered commands.
    """
    effective_handlers: dict[str, Callable[..., Awaitable[str]]] = (
        handler_registry or {}
    )
    commands = load_commands_from_yaml(directory, effective_handlers)

    for cmd in commands:
        handler = effective_handlers.get(cmd.name)

        if handler is None:
            cmd_name = cmd.name

            async def _noop(*args: Any, _name: str = cmd_name, **kwargs: Any) -> str:
                return f"Command '{_name}' executed (no handler registered)"

            handler = _noop

        registry.add(
            cmd.name,
            handler,
            aliases=cmd.aliases,
            description=cmd.description,
            category=cmd.category,
            parameters=cmd.parameters,
        )

    return len(commands)
