"""Plugin runner domain types — process-isolated plugin execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PluginState(str, Enum):
    """Lifecycle state of a plugin process."""

    STARTING = "starting"
    RUNNING = "running"
    CRASHED = "crashed"
    STOPPED = "stopped"


@dataclass(frozen=True)
class PluginManifest:
    """Declarative description of a plugin to launch."""

    name: str
    entry_point: str  # python module path, e.g. "my_plugin.main"
    timeout_seconds: float = 30.0
    max_restarts: int = 3
    restart_backoff_base: float = 2.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PluginHandle:
    """Immutable snapshot of a running (or stopped) plugin."""

    plugin_id: str
    name: str
    pid: int | None = None
    state: PluginState = PluginState.STOPPED
    restart_count: int = 0
    started_at: float | None = None
