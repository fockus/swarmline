"""asyncio-based periodic task scheduler."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import structlog

from cognitia.daemon.types import ScheduledTaskInfo

logger = structlog.get_logger(component="daemon.scheduler")


@dataclass
class _Task:
    """Internal task record."""

    name: str
    coro_factory: Callable[[], Awaitable[Any]]
    interval: float | None  # None = one-shot
    next_run: float  # monotonic
    last_run: float | None = None  # monotonic
    last_run_wall: float | None = None  # wall-clock for external use
    run_count: int = 0
    active: bool = True


class Scheduler:
    """asyncio-based periodic task scheduler.

    Implements ``TaskScheduler`` protocol.

    Runs coroutine factories on intervals. Tasks are fire-and-forget:
    exceptions are logged, not propagated. Scheduler runs until
    stop event is set.

    Usage::

        sched = Scheduler()
        sched.every(60, my_health_check, name="health")
        sched.once_at(time.time() + 10, one_time_init, name="init")
        await sched.run_until(stop_event)
    """

    def __init__(
        self,
        *,
        tick_interval: float = 1.0,
        max_concurrent: int = 0,
    ) -> None:
        self._tasks: dict[str, _Task] = {}
        self._paused = False
        self._tick_interval = tick_interval
        self._pending_asyncio_tasks: set[asyncio.Task[None]] = set()
        # max_concurrent=0 means unlimited (no semaphore).
        self._semaphore: asyncio.Semaphore | None = (
            asyncio.Semaphore(max_concurrent) if max_concurrent > 0 else None
        )

    def every(
        self,
        seconds: float,
        coro_factory: Callable[[], Awaitable[Any]],
        *,
        name: str = "",
    ) -> str:
        """Register a periodic task. Returns task name."""
        if seconds <= 0:
            msg = "Interval must be positive"
            raise ValueError(msg)
        task_name = name or f"periodic-{uuid.uuid4().hex[:8]}"
        self._tasks[task_name] = _Task(
            name=task_name,
            coro_factory=coro_factory,
            interval=seconds,
            next_run=time.monotonic() + seconds,
        )
        return task_name

    def once_at(
        self,
        timestamp: float,
        coro_factory: Callable[[], Awaitable[Any]],
        *,
        name: str = "",
    ) -> str:
        """Schedule a one-shot task at a unix timestamp."""
        task_name = name or f"once-{uuid.uuid4().hex[:8]}"
        # Convert wall-clock to monotonic offset
        offset = timestamp - time.time()
        self._tasks[task_name] = _Task(
            name=task_name,
            coro_factory=coro_factory,
            interval=None,
            next_run=time.monotonic() + max(offset, 0),
        )
        return task_name

    def cancel(self, name: str) -> bool:
        """Cancel task by name. Returns True if found."""
        task = self._tasks.pop(name, None)
        return task is not None

    def list_tasks(self) -> list[ScheduledTaskInfo]:
        """List all registered tasks."""
        now = time.monotonic()
        wall_now = time.time()
        result: list[ScheduledTaskInfo] = []
        for t in self._tasks.values():
            # Convert monotonic next_run to wall-clock for external use
            wall_next = wall_now + (t.next_run - now)
            result.append(
                ScheduledTaskInfo(
                    name=t.name,
                    interval_seconds=t.interval,
                    next_run_at=wall_next,
                    last_run_at=t.last_run_wall,
                    run_count=t.run_count,
                    is_active=t.active,
                )
            )
        return result

    def pause(self) -> None:
        """Pause all scheduling (tasks don't fire)."""
        self._paused = True

    def resume(self) -> None:
        """Resume scheduling."""
        self._paused = False

    @property
    def is_paused(self) -> bool:
        """Whether scheduler is paused."""
        return self._paused

    async def run_until(self, stop_event: asyncio.Event) -> None:
        """Run scheduler until stop event is set.

        Checks tasks every tick_interval seconds. Ready tasks are
        launched as asyncio tasks (fire-and-forget). On stop, awaits
        all in-flight tasks with a 5s grace period.
        """
        while not stop_event.is_set():
            if not self._paused:
                await self._tick()
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self._tick_interval,
                )
                break  # stop event set
            except TimeoutError:
                continue

        # Drain in-flight tasks on shutdown
        if self._pending_asyncio_tasks:
            done, pending = await asyncio.wait(
                self._pending_asyncio_tasks,
                timeout=5.0,
            )
            for t in pending:
                t.cancel()
            self._pending_asyncio_tasks.clear()

    async def _tick(self) -> None:
        """Check and fire ready tasks."""
        now = time.monotonic()
        to_remove: list[str] = []

        for name, task in list(self._tasks.items()):
            if not task.active:
                continue
            if task.next_run <= now:
                # Fire task and track reference
                at = asyncio.create_task(self._run_task(task))
                self._pending_asyncio_tasks.add(at)
                at.add_done_callback(self._pending_asyncio_tasks.discard)
                task.last_run = now
                task.last_run_wall = time.time()
                task.run_count += 1

                if task.interval is not None:
                    # Reschedule periodic
                    task.next_run = now + task.interval
                else:
                    # One-shot done
                    task.active = False
                    to_remove.append(name)

        for name in to_remove:
            self._tasks.pop(name, None)

    async def _run_task(self, task: _Task) -> None:
        """Run a task, logging exceptions.

        If a concurrency semaphore is configured (max_concurrent > 0),
        the task waits to acquire a slot before executing.
        """
        if self._semaphore is not None:
            async with self._semaphore:
                await self._run_task_inner(task)
        else:
            await self._run_task_inner(task)

    async def _run_task_inner(self, task: _Task) -> None:
        """Execute the task coroutine, logging exceptions."""
        try:
            await task.coro_factory()
        except Exception:
            logger.warning(
                "scheduler.task.error",
                task_name=task.name,
                exc_info=True,
            )
