"""Swarmline Daemon — long-running process manager.

Universal daemon module for running pipelines and workloads as
background processes with health monitoring, scheduling, and
graceful shutdown.

Usage::

    from swarmline.daemon import DaemonRunner, DaemonConfig, Scheduler

    runner = DaemonRunner(config=DaemonConfig(name="my-daemon"))
    runner.schedule_periodic(300, my_health_check, name="health")
    await runner.run()  # blocks until SIGTERM/SIGINT
"""

from swarmline.daemon.health import HealthServer
from swarmline.daemon.pid import DaemonAlreadyRunningError, PidFile
from swarmline.daemon.protocols import (
    HealthEndpoint,
    ProcessLock,
    RunnableScheduler,
    TaskScheduler,
)
from swarmline.daemon.routine_bridge import RoutineBridge, RoutineManager
from swarmline.daemon.routine_types import (
    Routine,
    RoutineRun,
    RoutineStatus,
    RunStatus,
)
from swarmline.daemon.runner import DaemonRunner
from swarmline.daemon.scheduler import Scheduler
from swarmline.daemon.types import (
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
    # Routine bridge
    "RoutineBridge",
    "Routine",
    "RoutineRun",
    "RoutineStatus",
    "RunStatus",
    # Protocols
    "ProcessLock",
    "HealthEndpoint",
    "TaskScheduler",
    "RunnableScheduler",
    "RoutineManager",
    # Errors
    "DaemonAlreadyRunningError",
]
