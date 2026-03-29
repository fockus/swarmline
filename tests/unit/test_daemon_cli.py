"""Unit tests for daemon CLI entry point."""

from __future__ import annotations

import os
import signal
from unittest.mock import patch

import pytest

from cognitia.daemon.cli_entry import main, _load_config
from cognitia.daemon.types import DaemonConfig


class TestCliParsing:

    def test_no_command_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1

    def test_help_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0

    def test_start_subcommand_help(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["start", "--help"])
        assert exc_info.value.code == 0


class TestLoadConfig:

    def test_defaults_from_args(self) -> None:
        import argparse
        args = argparse.Namespace(
            config=None,
            pid_path=None,
            port=None,
            host=None,
            name=None,
        )
        cfg = _load_config(args)
        assert isinstance(cfg, DaemonConfig)
        # DaemonConfig defaults used when CLI args are None
        assert cfg.health_port == 8471
        assert cfg.name == "cognitia-daemon"

    def test_cli_args_override(self) -> None:
        import argparse
        args = argparse.Namespace(
            config=None,
            pid_path="/tmp/test.pid",
            port=9999,
            host="0.0.0.0",
            name="my-daemon",
        )
        cfg = _load_config(args)
        assert cfg.pid_path == "/tmp/test.pid"
        assert cfg.health_port == 9999
        assert cfg.health_host == "0.0.0.0"
        assert cfg.name == "my-daemon"

    def test_yaml_config(self, tmp_path) -> None:
        import argparse

        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text(
            "max_concurrent_tasks: 10\nshutdown_timeout: 60.0\nhealth_port: 9090\n"
        )

        args = argparse.Namespace(
            config=str(yaml_path),
            pid_path=None,
            port=None,
            host=None,
            name=None,
        )
        cfg = _load_config(args)
        # YAML-only keys preserved
        assert cfg.max_concurrent_tasks == 10
        assert cfg.shutdown_timeout == 60.0
        # YAML health_port preserved (CLI not provided)
        assert cfg.health_port == 9090

    def test_cli_overrides_yaml(self, tmp_path) -> None:
        import argparse

        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text("name: from-yaml\nhealth_port: 7777\n")

        args = argparse.Namespace(
            config=str(yaml_path),
            pid_path=None,
            port=9999,
            host=None,
            name="from-cli",
        )
        cfg = _load_config(args)
        # Explicit CLI args override YAML
        assert cfg.name == "from-cli"
        assert cfg.health_port == 9999
        # YAML-only keys preserved when CLI is None
        # (pid_path falls back to DaemonConfig default since not in YAML and not in CLI)


class TestStopCommand:

    def test_stop_no_pid_file(self, tmp_path, capsys) -> None:
        pid_path = str(tmp_path / "nonexistent.pid")
        with pytest.raises(SystemExit) as exc_info:
            main(["stop", "--pid-path", pid_path])
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "No PID file" in captured.out

    def test_stop_stale_pid(self, tmp_path, capsys) -> None:
        pid_path = str(tmp_path / "stale.pid")
        with open(pid_path, "w") as f:
            f.write("999999999\n")

        main(["stop", "--pid-path", pid_path])
        captured = capsys.readouterr()
        assert "stale" in captured.out.lower() or "not running" in captured.out.lower()

    def test_stop_sends_sigterm(self, tmp_path) -> None:
        pid_path = str(tmp_path / "running.pid")
        current_pid = os.getpid()
        # Write PID file
        with open(pid_path, "w") as f:
            f.write(f"{current_pid}\n")
        # Create lock file to simulate running daemon
        lock_path = pid_path + ".lock"
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        import fcntl
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        try:
            with patch("os.kill") as mock_kill:
                main(["stop", "--pid-path", pid_path])
                mock_kill.assert_called_once_with(current_pid, signal.SIGTERM)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
