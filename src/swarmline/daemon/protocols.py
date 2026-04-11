"""Protocols for daemon module — ISP-compliant, ≤5 methods each."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

from swarmline.daemon.types import ScheduledTaskInfo


@runtime_checkable
class ProcessLock(Protocol):
    """Prevent double-start of daemon process. ISP: 3 methods."""

    def acquire(self) -> None:
        """Acquire lock. Raises if already held by another process."""
        ...

    def release(self) -> None:
        """Release lock."""
        ...

    def is_running(self) -> bool:
        """Check if daemon is already running."""
        ...


@runtime_checkable
class HealthEndpoint(Protocol):
    """HTTP/socket health endpoint for monitoring. ISP: 2 methods."""

    async def start(self) -> None:
        """Start serving health checks."""
        ...

    async def stop(self) -> None:
        """Stop serving."""
        ...


@runtime_checkable
class TaskScheduler(Protocol):
    """Periodic task scheduler. ISP: 5 methods."""

    def every(
        self,
        seconds: float,
        coro_factory: Callable[[], Awaitable[Any]],
        *,
        name: str = "",
    ) -> str:
        """Register periodic task. Returns task name."""
        ...

    def cancel(self, name: str) -> bool:
        """Cancel task by name."""
        ...

    def list_tasks(self) -> list[ScheduledTaskInfo]:
        """List registered tasks."""
        ...

    def pause(self) -> None:
        """Pause all scheduling."""
        ...

    def resume(self) -> None:
        """Resume scheduling."""
        ...


@runtime_checkable
class RunnableScheduler(TaskScheduler, Protocol):
    """Extended scheduler that can be run until a stop event.

    DaemonRunner requires this extended interface to drive the main loop.
    Standard TaskScheduler is sufficient for consumers who only register tasks.
    """

    async def run_until(self, stop_event: asyncio.Event) -> None:
        """Run scheduler until stop event is set."""
        ...

    def once_at(
        self,
        timestamp: float,
        coro_factory: Callable[[], Awaitable[Any]],
        *,
        name: str = "",
    ) -> str:
        """Schedule a one-shot task at a unix timestamp."""
        ...
