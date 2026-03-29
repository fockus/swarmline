"""Unit tests for DaemonRunner."""

from __future__ import annotations

import asyncio
import os
import signal
import time
from typing import Any
from unittest.mock import AsyncMock

import pytest

from cognitia.daemon.health import HealthServer
from cognitia.daemon.pid import PidFile
from cognitia.daemon.runner import DaemonRunner
from cognitia.daemon.scheduler import Scheduler
from cognitia.daemon.types import DaemonConfig, DaemonState


@pytest.fixture()
def config(tmp_path) -> DaemonConfig:
    return DaemonConfig(
        pid_path=str(tmp_path / "test.pid"),
        health_port=0,  # ephemeral
        name="test-daemon",
        shutdown_timeout=5.0,
    )


def _fast_runner(config: DaemonConfig, **kwargs) -> DaemonRunner:
    """Create DaemonRunner with fast-ticking scheduler for tests."""
    sched = kwargs.pop("scheduler", None) or Scheduler(tick_interval=0.05)
    return DaemonRunner(config=config, scheduler=sched, **kwargs)


class TestDaemonRunnerLifecycle:

    async def test_start_and_stop(self, config: DaemonConfig) -> None:
        runner = DaemonRunner(config=config)
        assert runner.state == DaemonState.STOPPED

        # Run in background, then stop
        task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.1)

        assert runner.state == DaemonState.RUNNING
        await runner.stop()
        await asyncio.wait_for(task, timeout=5.0)

        assert runner.state == DaemonState.STOPPED

    async def test_pid_file_created_and_released(self, config: DaemonConfig) -> None:
        runner = DaemonRunner(config=config)

        task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.1)

        # PID file should exist
        assert os.path.exists(config.resolved_pid_path())
        pid_content = open(config.resolved_pid_path()).read().strip()
        assert pid_content == str(os.getpid())

        await runner.stop()
        await asyncio.wait_for(task, timeout=5.0)

        # PID file should be removed
        assert not os.path.exists(config.resolved_pid_path())

    async def test_scheduler_tasks_execute(self, config: DaemonConfig) -> None:
        counter = {"value": 0}

        async def inc():
            counter["value"] += 1

        runner = _fast_runner(config)
        runner.schedule_periodic(0.05, inc, name="inc")

        task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.3)
        await runner.stop()
        await asyncio.wait_for(task, timeout=5.0)

        assert counter["value"] >= 2

    async def test_schedule_once(self, config: DaemonConfig) -> None:
        result = {"ran": False}

        async def once():
            result["ran"] = True

        runner = _fast_runner(config)
        runner.schedule_once(time.time() + 0.05, once, name="init")

        task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.3)
        await runner.stop()
        await asyncio.wait_for(task, timeout=5.0)

        assert result["ran"] is True


class TestDaemonRunnerStatus:

    async def test_get_status(self, config: DaemonConfig) -> None:
        runner = DaemonRunner(config=config)

        task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.1)

        status = runner.get_status()
        assert status["name"] == "test-daemon"
        assert status["state"] == "running"
        assert status["pid"] == os.getpid()
        assert status["uptime_seconds"] >= 0

        await runner.stop()
        await asyncio.wait_for(task, timeout=5.0)

    async def test_status_counts_tasks(self, config: DaemonConfig) -> None:
        runner = DaemonRunner(config=config)
        runner.schedule_periodic(60, _noop, name="t1")
        runner.schedule_periodic(60, _noop, name="t2")

        task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.1)

        status = runner.get_status()
        assert status["scheduled_tasks"] == 2

        await runner.stop()
        await asyncio.wait_for(task, timeout=5.0)


class TestDaemonRunnerEventBus:

    async def test_emits_events(self, config: DaemonConfig) -> None:
        events: list[tuple[str, dict]] = []

        class FakeBus:
            async def emit(self, topic: str, data: dict) -> None:
                events.append((topic, data))

        runner = DaemonRunner(config=config, event_bus=FakeBus())

        task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.1)
        await runner.stop()
        await asyncio.wait_for(task, timeout=5.0)

        topics = [e[0] for e in events]
        assert "daemon.started" in topics
        assert "daemon.stopping" in topics
        assert "daemon.stopped" in topics


class TestDaemonRunnerCustomComponents:

    async def test_custom_pid_file(self, tmp_path) -> None:
        """DaemonRunner accepts custom ProcessLock implementation."""
        custom_pid = PidFile(str(tmp_path / "custom.pid"))
        config = DaemonConfig(
            pid_path=str(tmp_path / "ignored.pid"),
            health_port=0,
        )
        runner = DaemonRunner(config=config, pid_file=custom_pid)

        task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.1)

        # Custom PID file should be used
        assert os.path.exists(str(tmp_path / "custom.pid"))
        assert not os.path.exists(str(tmp_path / "ignored.pid"))

        await runner.stop()
        await asyncio.wait_for(task, timeout=5.0)

    async def test_custom_scheduler(self, config: DaemonConfig) -> None:
        """DaemonRunner accepts custom TaskScheduler implementation."""
        custom_sched = Scheduler(tick_interval=0.05)
        runner = DaemonRunner(config=config, scheduler=custom_sched)

        counter = {"val": 0}
        async def inc():
            counter["val"] += 1

        custom_sched.every(0.05, inc, name="custom")

        task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.3)
        await runner.stop()
        await asyncio.wait_for(task, timeout=5.0)

        assert counter["val"] >= 2

    def test_scheduler_property(self, config: DaemonConfig) -> None:
        runner = DaemonRunner(config=config)
        assert isinstance(runner.scheduler, Scheduler)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _noop() -> None:
    pass
