"""Integration: `swarmline --format json` stdout is parseable JSON.

Stage 5 release blocker: when `configure_logging()` routed log output to
stdout, any incidental log line emitted during command execution corrupted
the JSON document users (and downstream tooling) consume.

This test runs the lightweight `swarmline status --format json` command via
subprocess and asserts the stdout is a single valid JSON document. Logs may
freely appear on stderr.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
import pytest

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_cli_format_json_no_log_pollution() -> None:
    """`swarmline status --format json` must emit valid JSON to stdout.

    `status` is chosen because it is offline, deterministic, and exercises the
    same `_print_result` code path as every other CLI command.
    """
    cmd = [sys.executable, "-m", "swarmline.cli", "--format", "json", "status"]
    result = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, (
        f"swarmline status exited {result.returncode}\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )

    # stdout must be parseable JSON; no log lines mixed in.
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"stdout is not valid JSON; log pollution suspected.\n"
            f"--- stdout ---\n{result.stdout!r}\n"
            f"--- stderr ---\n{result.stderr!r}\n"
            f"json error: {exc}"
        ) from exc

    assert isinstance(parsed, dict), (
        f"expected JSON object on stdout; got {type(parsed).__name__}: {parsed!r}"
    )
    assert parsed.get("ok") is True, (
        f"expected ok=True in status output; got {parsed!r}"
    )
