"""DaemonRunner — long-running daemon process manager."""

from __future__ import annotations

import asyncio
import os
import signal
import time
from typing import Any, Awaitable, Callable

import structlog

from swarmline.daemon.health import HealthServer
from swarmline.daemon.pid import PidFile
from swarmline.daemon.protocols import HealthEndpoint, ProcessLock, RunnableScheduler
from swarmline.daemon.scheduler import Scheduler
from swarmline.daemon.types import DaemonConfig, DaemonState, DaemonStatus

logger = structlog.get_logger(component="daemon.runner")


class DaemonRunner:
    """Long-running daemon process manager.

    Manages lifecycle: PID → signals → scheduler → health → workload.
    Accepts any async callable as workload, or use ``schedule_periodic``
    to register recurring tasks.

    All components (PidFile, Scheduler, HealthServer) can be replaced
    with custom implementations via constructor — they follow
    ``ProcessLock``, ``RunnableScheduler``, ``HealthEndpoint`` protocols.

    Usage::

        runner = DaemonRunner(config=DaemonConfig(name="my-daemon"))
        runner.schedule_periodic(300, check_status, name="status_check")
        await runner.run()  # blocks until SIGTERM/SIGINT
    """

    def __init__(
        self,
        config: DaemonConfig,
        *,
        pid_file: ProcessLock | None = None,
        scheduler: RunnableScheduler | None = None,
        health_server: HealthEndpoint | None = None,
        event_bus: Any | None = None,
    ) -> None:
        self._config = config
        self._pid: ProcessLock = pid_file or PidFile(config.resolved_pid_path())
        self._scheduler: RunnableScheduler = scheduler or Scheduler()
        self._event_bus = event_bus
        self._stop_event = asyncio.Event()
        self._state = DaemonState.STOPPED
        self._started_at: float = 0.0
        self._started_wall: float = 0.0
        self._prev_handlers: dict[int, Any] = {}

        # Health server wired to daemon controls
        self._health: HealthEndpoint = health_server or HealthServer(
            host=config.health_host,
            port=config.health_port,
            status_provider=self.get_status,
            on_pause=self._scheduler.pause,
            on_resume=self._scheduler.resume,
            auth_token=config.auth_token,
            allow_unauthenticated_local=config.allow_unauthenticated_local,
        )

    @property
    def state(self) -> DaemonState:
        """Current daemon state."""
        return self._state

    @property
    def scheduler(self) -> RunnableScheduler:
        """Access scheduler for direct task registration."""
        return self._scheduler

    async def run(self) -> None:
        """Main entry point. Blocks until shutdown signal.

        Lifecycle:
        1. Acquire PID lock
        2. Setup signal handlers (SIGTERM, SIGINT)
        3. Start health endpoint
        4. Emit ``daemon.started``
        5. Run scheduler loop until stop event
        6. Graceful shutdown + emit ``daemon.stopped``
        7. Release PID lock + restore signal handlers
        """
        self._state = DaemonState.STARTING
        self._pid.acquire()
        self._started_at = time.monotonic()
        self._started_wall = time.time()

        try:
            self._setup_signals()
            await self._health.start()
            self._state = DaemonState.RUNNING

            await self._emit(
                "daemon.started",
                {
                    "name": self._config.name,
                    "pid": os.getpid(),
                },
            )

            logger.info(
                "daemon.started",
                name=self._config.name,
                pid=os.getpid(),
                health_port=self._config.health_port,
            )

            await self._scheduler.run_until(self._stop_event)

        finally:
            self._state = DaemonState.STOPPING
            await self._emit("daemon.stopping", {})
            await self._graceful_shutdown()
            self._state = DaemonState.STOPPED
            await self._emit("daemon.stopped", {})
            self._pid.release()
            self._restore_signals()

    def schedule_periodic(
        self,
        seconds: float,
        coro_factory: Callable[[], Awaitable[Any]],
        *,
        name: str = "",
    ) -> str:
        """Register a periodic task on the scheduler."""
        return self._scheduler.every(seconds, coro_factory, name=name)

    def schedule_once(
        self,
        timestamp: float,
        coro_factory: Callable[[], Awaitable[Any]],
        *,
        name: str = "",
    ) -> str:
        """Schedule a one-shot task."""
        return self._scheduler.once_at(timestamp, coro_factory, name=name)

    async def stop(self) -> None:
        """Request daemon stop. Scheduler will exit on next tick."""
        logger.info("daemon.stop_requested")
        self._stop_event.set()

    def get_status(self) -> dict[str, Any]:
        """Return daemon status as dict (used by health endpoint)."""
        uptime = time.monotonic() - self._started_at if self._started_at else 0.0
        tasks = self._scheduler.list_tasks()
        status = DaemonStatus(
            pid=os.getpid(),
            name=self._config.name,
            state=self._state,
            uptime_seconds=round(uptime, 1),
            scheduled_tasks=len(tasks),
            active_tasks=sum(1 for t in tasks if t.is_active),
            started_at=self._started_wall,
        )
        return {
            "pid": status.pid,
            "name": status.name,
            "state": status.state.value,
            "uptime_seconds": status.uptime_seconds,
            "scheduled_tasks": status.scheduled_tasks,
            "active_tasks": status.active_tasks,
            "started_at": status.started_at,
        }

    def _setup_signals(self) -> None:
        """Register signal handlers for graceful shutdown."""
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            prev = loop.add_signal_handler(sig, self._stop_event.set)
            self._prev_handlers[sig] = prev

    def _restore_signals(self) -> None:
        """Restore previous signal handlers."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig)

    async def _graceful_shutdown(self) -> None:
        """Stop health server, log shutdown."""
        try:
            await asyncio.wait_for(
                self._health.stop(),
                timeout=self._config.shutdown_timeout,
            )
        except TimeoutError:
            logger.warning("daemon.shutdown.timeout", component="health")

        logger.info("daemon.stopped", name=self._config.name)

    async def _emit(self, topic: str, data: dict[str, Any]) -> None:
        """Emit event to bus if available."""
        if self._event_bus is not None:
            await self._event_bus.emit(topic, data)
