"""Cognitia Daemon — long-running process manager.

Universal daemon module for running pipelines and workloads as
background processes with health monitoring, scheduling, and
graceful shutdown.

Usage::

    from cognitia.daemon import DaemonRunner, DaemonConfig, Scheduler

    runner = DaemonRunner(config=DaemonConfig(name="my-daemon"))
    runner.schedule_periodic(300, my_health_check, name="health")
    await runner.run()  # blocks until SIGTERM/SIGINT
"""

from cognitia.daemon.health import HealthServer
from cognitia.daemon.pid import DaemonAlreadyRunningError, PidFile
from cognitia.daemon.protocols import (
    HealthEndpoint,
    ProcessLock,
    RunnableScheduler,
    TaskScheduler,
)
from cognitia.daemon.runner import DaemonRunner
from cognitia.daemon.scheduler import Scheduler
from cognitia.daemon.types import (
    DaemonConfig,
    DaemonState,
    DaemonStatus,
    ScheduledTaskInfo,
)

__all__ = [
    # Core
    "DaemonRunner",
    "DaemonConfig",
    "DaemonState",
    "DaemonStatus",
    "ScheduledTaskInfo",
    # Components
    "Scheduler",
    "HealthServer",
    "PidFile",
    # Protocols
    "ProcessLock",
    "HealthEndpoint",
    "TaskScheduler",
    "RunnableScheduler",
    # Errors
    "DaemonAlreadyRunningError",
]
