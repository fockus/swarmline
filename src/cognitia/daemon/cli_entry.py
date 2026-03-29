"""CLI entry point for cognitia-daemon.

Usage::

    cognitia-daemon start [--config config.yaml] [--pid-path path] [--port 8471]
    cognitia-daemon stop [--pid-path path]
    cognitia-daemon status [--host host] [--port 8471]
    cognitia-daemon pause [--host host] [--port 8471]
    cognitia-daemon resume [--host host] [--port 8471]

Uses argparse (stdlib) — no click dependency for daemon extra.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import urllib.request
from typing import Any

from cognitia.daemon.pid import PidFile
from cognitia.daemon.types import DaemonConfig

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8471
_DEFAULT_PID = "~/.cognitia/daemon.pid"


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="cognitia-daemon",
        description="Cognitia Daemon — long-running process manager",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- start ---
    start_p = subparsers.add_parser("start", help="Start daemon (foreground)")
    start_p.add_argument("--config", type=str, help="YAML config file path")
    start_p.add_argument("--pid-path", type=str, default=None, help=f"PID file path (default: {_DEFAULT_PID})")
    start_p.add_argument("--port", type=int, default=None, help=f"Health endpoint port (default: {_DEFAULT_PORT})")
    start_p.add_argument("--host", type=str, default=None, help=f"Health endpoint host (default: {_DEFAULT_HOST})")
    start_p.add_argument("--name", type=str, default=None, help="Daemon name (default: cognitia-daemon)")

    # --- stop ---
    stop_p = subparsers.add_parser("stop", help="Stop running daemon")
    stop_p.add_argument("--pid-path", type=str, default=_DEFAULT_PID, help="PID file path")

    # --- status ---
    status_p = subparsers.add_parser("status", help="Query daemon status")
    status_p.add_argument("--host", type=str, default=_DEFAULT_HOST)
    status_p.add_argument("--port", type=int, default=_DEFAULT_PORT)
    status_p.add_argument("--pid-path", type=str, default=_DEFAULT_PID)

    # --- pause ---
    pause_p = subparsers.add_parser("pause", help="Pause daemon scheduler")
    pause_p.add_argument("--host", type=str, default=_DEFAULT_HOST)
    pause_p.add_argument("--port", type=int, default=_DEFAULT_PORT)
    pause_p.add_argument("--token", type=str, default=None, help="Auth token for daemon")

    # --- resume ---
    resume_p = subparsers.add_parser("resume", help="Resume daemon scheduler")
    resume_p.add_argument("--host", type=str, default=_DEFAULT_HOST)
    resume_p.add_argument("--port", type=int, default=_DEFAULT_PORT)
    resume_p.add_argument("--token", type=str, default=None, help="Auth token for daemon")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    handlers = {
        "start": _cmd_start,
        "stop": _cmd_stop,
        "status": _cmd_status,
        "pause": _cmd_pause,
        "resume": _cmd_resume,
    }
    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    handler(args)


def _cmd_start(args: argparse.Namespace) -> None:
    """Start daemon in foreground."""
    import asyncio

    from cognitia.daemon.runner import DaemonRunner

    config = _load_config(args)

    runner = DaemonRunner(config=config)

    print(f"Starting {config.name} (PID {os.getpid()})...")  # noqa: T201
    print(f"Health endpoint: http://{config.health_host}:{config.health_port}/health")  # noqa: T201

    try:
        asyncio.run(runner.run())
    except KeyboardInterrupt:
        pass

    print("Daemon stopped.")  # noqa: T201


def _cmd_stop(args: argparse.Namespace) -> None:
    """Send SIGTERM to running daemon."""
    pid_path = os.path.expanduser(args.pid_path)
    pf = PidFile(pid_path)

    pid = pf.read_pid()
    if pid is None:
        print(f"No PID file found at {pid_path}")  # noqa: T201
        sys.exit(1)

    if not pf.is_running():
        print(f"Daemon not running (stale PID {pid}). Cleaning up.")  # noqa: T201
        pf.release()
        return

    print(f"Sending SIGTERM to PID {pid}...")  # noqa: T201
    os.kill(pid, signal.SIGTERM)
    print("Stop signal sent.")  # noqa: T201


def _cmd_status(args: argparse.Namespace) -> None:
    """Query daemon status via health endpoint or PID file."""
    # Try health endpoint first
    try:
        data = _http_get(args.host, args.port, "/status")
        print(json.dumps(data, indent=2))  # noqa: T201
        return
    except Exception:
        pass

    # Fallback to PID file
    pid_path = os.path.expanduser(args.pid_path)
    pf = PidFile(pid_path)
    if pf.is_running():
        pid = pf.read_pid()
        print(json.dumps({"status": "running", "pid": pid, "note": "health endpoint unreachable"}, indent=2))  # noqa: T201
    else:
        print(json.dumps({"status": "stopped"}, indent=2))  # noqa: T201


def _cmd_pause(args: argparse.Namespace) -> None:
    """Pause daemon scheduler."""
    data = _http_post(args.host, args.port, "/pause", token=args.token)
    print(json.dumps(data, indent=2))  # noqa: T201


def _cmd_resume(args: argparse.Namespace) -> None:
    """Resume daemon scheduler."""
    data = _http_post(args.host, args.port, "/resume", token=args.token)
    print(json.dumps(data, indent=2))  # noqa: T201


def _load_config(args: argparse.Namespace) -> DaemonConfig:
    """Build DaemonConfig from args and optional YAML file.

    Priority: explicit CLI args > YAML file > DaemonConfig defaults.
    Only CLI args that were explicitly provided override YAML values.
    """
    base: dict[str, Any] = {}

    if args.config:
        import yaml

        config_path = os.path.expanduser(args.config)
        with open(config_path) as f:
            base = yaml.safe_load(f) or {}

    # Only override YAML with explicitly provided CLI args (non-None)
    _cli_overrides = {
        "pid_path": args.pid_path,
        "health_port": args.port,
        "health_host": args.host,
        "name": args.name,
    }
    for key, value in _cli_overrides.items():
        if value is not None:
            base[key] = value

    return DaemonConfig(**base)


def _http_get(host: str, port: int, path: str) -> dict[str, Any]:
    """HTTP GET to daemon health endpoint."""
    url = f"http://{host}:{port}{path}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def _http_post(
    host: str, port: int, path: str, *, token: str | None = None,
) -> dict[str, Any]:
    """HTTP POST to daemon health endpoint."""
    url = f"http://{host}:{port}{path}"
    req = urllib.request.Request(url, method="POST", data=b"")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


if __name__ == "__main__":
    main()
