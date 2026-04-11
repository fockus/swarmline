"""Domain types for the daemon module."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DaemonState(str, Enum):
    """Daemon lifecycle state."""

    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"


@dataclass(frozen=True)
class DaemonConfig:
    """Configuration for daemon process.

    All paths support ``~`` expansion.
    """

    # Paths
    pid_path: str = "~/.swarmline/daemon.pid"
    log_path: str | None = None  # None = stdout

    # Health endpoint
    health_host: str = "127.0.0.1"
    health_port: int = 8471

    # Scheduling
    health_check_interval: float = 60.0  # seconds

    # Limits
    max_concurrent_tasks: int = 5
    shutdown_timeout: float = 30.0  # graceful shutdown deadline

    # Auth
    auth_token: str | None = None
    allow_unauthenticated_local: bool = False

    # Metadata
    name: str = "swarmline-daemon"
    metadata: dict[str, Any] = field(default_factory=dict)

    def resolved_pid_path(self) -> str:
        """Return PID path with ``~`` expanded."""
        return os.path.expanduser(self.pid_path)

    def resolved_log_path(self) -> str | None:
        """Return log path with ``~`` expanded, or None."""
        if self.log_path is None:
            return None
        return os.path.expanduser(self.log_path)


@dataclass(frozen=True)
class DaemonStatus:
    """Snapshot of daemon runtime state."""

    pid: int
    name: str
    state: DaemonState
    uptime_seconds: float
    scheduled_tasks: int = 0
    active_tasks: int = 0
    started_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScheduledTaskInfo:
    """Descriptor for a registered scheduled task."""

    name: str
    interval_seconds: float | None  # None = one-shot
    next_run_at: float
    last_run_at: float | None = None
    run_count: int = 0
    is_active: bool = True
