"""Test isolation regression — combined runs must not corrupt each other.

Stage 5 release blocker: `configure_logging()` previously used
`logging.basicConfig(force=True, stream=sys.stdout)` which mutated process-wide
logging state. When two test files ran together, log output from the first
contaminated `capsys.readouterr().out` assertions in the second, producing
~141 spurious failures across the suite.

This integration test re-runs two representative test files via subprocess so
that they share a fresh process-level logging state (the real failure surface).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_two_test_files_share_no_logger_state() -> None:
    """Combined run of two unrelated unit-test files must succeed.

    Reproduces (and now guards against) the contamination scenario where
    `configure_logging()` in test A injects a stdout handler that leaks
    captured output for test B.
    """
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/unit/test_event_bus.py",
        "tests/unit/test_cli_commands.py",
        "-q",
        "--no-header",
        "-p",
        "no:cacheprovider",
    ]
    result = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert result.returncode == 0, (
        f"Combined run failed (exit {result.returncode}). "
        f"This indicates test isolation regression.\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
