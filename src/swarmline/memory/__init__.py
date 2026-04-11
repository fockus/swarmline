"""Memory module - storage providers for agent data.

ISP: the monolithic MemoryProvider has been removed. Use the small protocols
from swarmline.protocols (MessageStore, FactStore, etc.).

PostgresMemoryProvider has been moved to the application's infrastructure layer.
Only InMemory + types live here.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from swarmline.memory.inmemory import InMemoryMemoryProvider
from swarmline.memory.types import (
    GoalState,
    MemoryMessage,
    PhaseState,
    ToolEvent,
    UserProfile,
)

__all__ = [
    "GoalState",
    "InMemoryMemoryProvider",
    "MemoryMessage",
    "PhaseState",
    "PostgresMemoryProvider",
    "SQLiteMemoryProvider",
    "SqliteMemoryProvider",
    "ToolEvent",
    "UserProfile",
]

_OPTIONAL_EXPORTS: dict[str, tuple[str, str, str]] = {
    "PostgresMemoryProvider": (
        "swarmline.memory.postgres",
        "PostgresMemoryProvider",
        "Install SQLAlchemy async dependencies to use PostgresMemoryProvider.",
    ),
    "SQLiteMemoryProvider": (
        "swarmline.memory.sqlite",
        "SQLiteMemoryProvider",
        "Install SQLAlchemy async dependencies to use SQLiteMemoryProvider.",
    ),
    "SqliteMemoryProvider": (
        "swarmline.memory.sqlite",
        "SQLiteMemoryProvider",
        "Install SQLAlchemy async dependencies to use SqliteMemoryProvider.",
    ),
}


def __getattr__(name: str) -> Any:
    optional = _OPTIONAL_EXPORTS.get(name)
    if optional is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name, hint = optional
    try:
        module = import_module(module_name)
        value = getattr(module, attr_name)
    except (ImportError, AttributeError) as exc:
        raise ImportError(f"{attr_name} is unavailable. {hint}") from exc

    globals()[name] = value
    return value
