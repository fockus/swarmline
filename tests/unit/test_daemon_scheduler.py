"""Unit tests for Scheduler."""

from __future__ import annotations

import asyncio
import time

import pytest

from cognitia.daemon.scheduler import Scheduler


class TestSchedulerRegistration:

    def test_every_returns_name(self) -> None:
        sched = Scheduler()
        name = sched.every(10, _noop, name="test")
        assert name == "test"

    def test_every_auto_name(self) -> None:
        sched = Scheduler()
        name = sched.every(10, _noop)
        assert name.startswith("periodic-")

    def test_every_negative_interval_raises(self) -> None:
        sched = Scheduler()
        with pytest.raises(ValueError, match="positive"):
            sched.every(-1, _noop)

    def test_once_at_returns_name(self) -> None:
        sched = Scheduler()
        name = sched.once_at(time.time() + 100, _noop, name="init")
        assert name == "init"

    def test_cancel_existing(self) -> None:
        sched = Scheduler()
        sched.every(10, _noop, name="x")
        assert sched.cancel("x") is True
        assert sched.cancel("x") is False

    def test_cancel_missing(self) -> None:
        sched = Scheduler()
        assert sched.cancel("nonexistent") is False

    def test_list_tasks(self) -> None:
        sched = Scheduler()
        sched.every(60, _noop, name="health")
        sched.once_at(time.time() + 300, _noop, name="init")
        tasks = sched.list_tasks()
        assert len(tasks) == 2
        names = {t.name for t in tasks}
        assert names == {"health", "init"}

    def test_list_tasks_interval(self) -> None:
        sched = Scheduler()
        sched.every(30, _noop, name="t")
        tasks = sched.list_tasks()
        assert tasks[0].interval_seconds == 30.0

    def test_list_tasks_one_shot_interval_none(self) -> None:
        sched = Scheduler()
        sched.once_at(time.time() + 5, _noop, name="t")
        tasks = sched.list_tasks()
        assert tasks[0].interval_seconds is None


class TestSchedulerPauseResume:

    def test_initial_not_paused(self) -> None:
        sched = Scheduler()
        assert sched.is_paused is False

    def test_pause_resume(self) -> None:
        sched = Scheduler()
        sched.pause()
        assert sched.is_paused is True
        sched.resume()
        assert sched.is_paused is False

    async def test_paused_tasks_dont_fire(self) -> None:
        counter = _Counter()
        sched = Scheduler(tick_interval=0.05)
        sched.every(0.01, counter.increment, name="cnt")
        sched.pause()

        stop = asyncio.Event()
        asyncio.get_event_loop().call_later(0.2, stop.set)
        await sched.run_until(stop)

        assert counter.value == 0

    async def test_resume_fires_tasks(self) -> None:
        counter = _Counter()
        sched = Scheduler(tick_interval=0.05)
        sched.every(0.01, counter.increment, name="cnt")
        sched.pause()

        stop = asyncio.Event()

        async def resume_later():
            await asyncio.sleep(0.1)
            sched.resume()
            await asyncio.sleep(0.2)
            stop.set()

        asyncio.create_task(resume_later())
        await sched.run_until(stop)

        assert counter.value >= 1


class TestSchedulerExecution:

    async def test_every_fires_periodically(self) -> None:
        counter = _Counter()
        sched = Scheduler(tick_interval=0.05)
        sched.every(0.05, counter.increment, name="cnt")

        stop = asyncio.Event()
        asyncio.get_event_loop().call_later(0.3, stop.set)
        await sched.run_until(stop)

        # Should fire multiple times
        assert counter.value >= 2

    async def test_once_at_fires_once(self) -> None:
        counter = _Counter()
        sched = Scheduler(tick_interval=0.05)
        sched.once_at(time.time() + 0.01, counter.increment, name="once")

        stop = asyncio.Event()
        asyncio.get_event_loop().call_later(0.3, stop.set)
        await sched.run_until(stop)

        assert counter.value == 1

    async def test_once_at_removed_after_fire(self) -> None:
        sched = Scheduler(tick_interval=0.05)
        sched.once_at(time.time() + 0.01, _noop, name="once")

        stop = asyncio.Event()
        asyncio.get_event_loop().call_later(0.2, stop.set)
        await sched.run_until(stop)

        assert len(sched.list_tasks()) == 0

    async def test_exception_does_not_kill_scheduler(self) -> None:
        counter = _Counter()
        sched = Scheduler(tick_interval=0.05)

        async def failing():
            raise RuntimeError("boom")

        sched.every(0.05, failing, name="fail")
        sched.every(0.05, counter.increment, name="ok")

        stop = asyncio.Event()
        asyncio.get_event_loop().call_later(0.3, stop.set)
        await sched.run_until(stop)

        # "ok" task should have fired despite "fail" raising
        assert counter.value >= 2

    async def test_stop_event_stops_scheduler(self) -> None:
        sched = Scheduler(tick_interval=0.05)
        stop = asyncio.Event()
        stop.set()  # Already set

        await sched.run_until(stop)
        # Should return immediately — no hang

    async def test_run_count_increments(self) -> None:
        sched = Scheduler(tick_interval=0.05)
        sched.every(0.05, _noop, name="cnt")

        stop = asyncio.Event()
        asyncio.get_event_loop().call_later(0.25, stop.set)
        await sched.run_until(stop)

        tasks = sched.list_tasks()
        assert tasks[0].run_count >= 2


class TestSchedulerProtocol:

    def test_protocol_compliance(self) -> None:
        from cognitia.daemon.protocols import TaskScheduler
        sched = Scheduler()
        assert isinstance(sched, TaskScheduler)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _noop() -> None:
    pass


class _Counter:
    def __init__(self) -> None:
        self.value = 0

    async def increment(self) -> None:
        self.value += 1
