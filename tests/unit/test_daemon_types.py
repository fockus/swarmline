"""Unit tests for daemon domain types."""

from __future__ import annotations

import time

from swarmline.daemon.types import (
    DaemonConfig,
    DaemonState,
    DaemonStatus,
    ScheduledTaskInfo,
)


class TestDaemonConfig:

    def test_defaults(self) -> None:
        cfg = DaemonConfig()
        assert cfg.pid_path == "~/.swarmline/daemon.pid"
        assert cfg.log_path is None
        assert cfg.health_host == "127.0.0.1"
        assert cfg.health_port == 8471
        assert cfg.health_check_interval == 60.0
        assert cfg.max_concurrent_tasks == 5
        assert cfg.shutdown_timeout == 30.0
        assert cfg.name == "swarmline-daemon"
        assert cfg.metadata == {}

    def test_resolved_pid_path_expands_tilde(self) -> None:
        cfg = DaemonConfig(pid_path="~/my.pid")
        resolved = cfg.resolved_pid_path()
        assert "~" not in resolved
        assert resolved.endswith("/my.pid")

    def test_resolved_log_path_none(self) -> None:
        cfg = DaemonConfig(log_path=None)
        assert cfg.resolved_log_path() is None

    def test_resolved_log_path_expands_tilde(self) -> None:
        cfg = DaemonConfig(log_path="~/daemon.log")
        resolved = cfg.resolved_log_path()
        assert "~" not in resolved
        assert resolved.endswith("/daemon.log")

    def test_custom_config(self) -> None:
        cfg = DaemonConfig(
            pid_path="/tmp/test.pid",
            health_port=9999,
            name="test-daemon",
            metadata={"version": "1.0"},
        )
        assert cfg.health_port == 9999
        assert cfg.name == "test-daemon"
        assert cfg.metadata["version"] == "1.0"

    def test_frozen(self) -> None:
        cfg = DaemonConfig()
        try:
            cfg.name = "changed"  # type: ignore[misc]
            raise AssertionError("Should be frozen")
        except AttributeError:
            pass


class TestDaemonState:

    def test_all_states(self) -> None:
        assert DaemonState.STARTING == "starting"
        assert DaemonState.RUNNING == "running"
        assert DaemonState.PAUSED == "paused"
        assert DaemonState.STOPPING == "stopping"
        assert DaemonState.STOPPED == "stopped"


class TestDaemonStatus:

    def test_creation(self) -> None:
        status = DaemonStatus(
            pid=12345,
            name="test",
            state=DaemonState.RUNNING,
            uptime_seconds=100.0,
        )
        assert status.pid == 12345
        assert status.state == DaemonState.RUNNING
        assert status.scheduled_tasks == 0
        assert status.active_tasks == 0

    def test_with_metadata(self) -> None:
        status = DaemonStatus(
            pid=1,
            name="d",
            state=DaemonState.PAUSED,
            uptime_seconds=0,
            metadata={"pipeline": "sprint-3"},
        )
        assert status.metadata["pipeline"] == "sprint-3"

    def test_started_at_default(self) -> None:
        before = time.time()
        status = DaemonStatus(pid=1, name="d", state=DaemonState.RUNNING, uptime_seconds=0)
        after = time.time()
        assert before <= status.started_at <= after


class TestScheduledTaskInfo:

    def test_periodic_task(self) -> None:
        task = ScheduledTaskInfo(
            name="health_check",
            interval_seconds=60.0,
            next_run_at=time.time() + 60,
        )
        assert task.interval_seconds == 60.0
        assert task.is_active is True
        assert task.run_count == 0

    def test_one_shot_task(self) -> None:
        task = ScheduledTaskInfo(
            name="initial_scan",
            interval_seconds=None,
            next_run_at=time.time() + 5,
        )
        assert task.interval_seconds is None

    def test_inactive_task(self) -> None:
        task = ScheduledTaskInfo(
            name="done",
            interval_seconds=10.0,
            next_run_at=0,
            is_active=False,
            run_count=5,
        )
        assert task.is_active is False
        assert task.run_count == 5
