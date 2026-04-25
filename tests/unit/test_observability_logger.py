"""Tests for `configure_logging` — output stream + idempotency.

These guard two release-blocker invariants (Stage 5):
1. Standard `logging` and `structlog` write to **stderr**, not stdout, so
   `swarmline --format json ...` produces clean JSON on stdout.
2. `configure_logging()` is idempotent — calling it twice does not double
   handlers (which would otherwise leak across pytest test files).

Note on isolation: pytest installs its own `LogCaptureHandler` on the root
logger before tests run, so we cannot rely on `capfd` to observe stdlib log
output during a test. Instead, we run `configure_logging()` in a clean
subprocess and assert what *actually* lands on the OS-level stdout / stderr
file descriptors. This is the same surface the CLI JSON contract depends on.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

import structlog

from swarmline.observability.logger import configure_logging

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_logging_probe() -> subprocess.CompletedProcess[str]:
    """Configure logging in a subprocess and emit one stdlib + one structlog line."""
    code = (
        "import logging, structlog\n"
        "from swarmline.observability.logger import configure_logging\n"
        "configure_logging(level='info', fmt='json')\n"
        "logging.getLogger('swarmline.test').info('test message stdlib')\n"
        "structlog.get_logger('swarmline.test').info('test message structlog')\n"
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_configure_logging_writes_to_stderr_not_stdout() -> None:
    """Both stdlib `logging` and `structlog` must emit to stderr.

    Why: `swarmline --format json ...` writes machine-readable JSON to stdout.
    Logger output on stdout would corrupt that contract for downstream consumers.
    """
    result = _run_logging_probe()

    assert result.returncode == 0, (
        f"probe exited {result.returncode}\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )

    assert "test message stdlib" in result.stderr, (
        f"stdlib log line missing from stderr; stderr={result.stderr!r}"
    )
    assert "test message structlog" in result.stderr, (
        f"structlog log line missing from stderr; stderr={result.stderr!r}"
    )
    assert "test message stdlib" not in result.stdout, (
        f"stdlib log line leaked into stdout; stdout={result.stdout!r}"
    )
    assert "test message structlog" not in result.stdout, (
        f"structlog log line leaked into stdout; stdout={result.stdout!r}"
    )


def test_configure_logging_idempotent() -> None:
    """Multiple calls must not stack root handlers.

    Why: tests that call `configure_logging()` would otherwise add a new handler
    on every invocation, eventually leaking into other tests' captured streams.

    Run in subprocess to bypass pytest's `LogCaptureHandler`, which preempts
    handler-count assertions on the root logger.
    """
    code = (
        "import logging\n"
        "from swarmline.observability.logger import configure_logging\n"
        "configure_logging(level='info', fmt='json')\n"
        "first = len(logging.getLogger().handlers)\n"
        "configure_logging(level='info', fmt='json')\n"
        "configure_logging(level='debug', fmt='console')\n"
        "thrice = len(logging.getLogger().handlers)\n"
        "print(f'{first}|{thrice}')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, (
        f"probe exited {result.returncode}\n--- stderr ---\n{result.stderr}"
    )
    first_str, thrice_str = result.stdout.strip().split("|")
    handlers_after_first = int(first_str)
    handlers_after_thrice = int(thrice_str)

    assert handlers_after_first == 1, (
        f"first configure_logging() should install exactly one handler, "
        f"got {handlers_after_first}"
    )
    assert handlers_after_thrice == handlers_after_first, (
        f"configure_logging() is not idempotent: "
        f"handlers grew {handlers_after_first} -> {handlers_after_thrice}"
    )


def test_configure_logging_handler_targets_stderr_stream() -> None:
    """The single root handler installed by configure_logging() targets sys.stderr.

    Stage 5: this is a fast in-process invariant check — independent of pytest's
    own `LogCaptureHandler` and useful for CI debugging.
    """
    # Drop any handlers pytest (or earlier tests) installed so we observe a
    # clean configure_logging() install path. The autouse fixture in this file
    # already empties the root logger between tests, but we re-assert here.
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    configure_logging(level="info", fmt="json")

    stream_handlers = [h for h in root.handlers if isinstance(h, logging.StreamHandler)]
    assert stream_handlers, "configure_logging() did not install a StreamHandler"
    streams = {getattr(h, "stream", None) for h in stream_handlers}
    assert sys.stderr in streams, (
        f"no StreamHandler targets sys.stderr; streams={streams!r}"
    )
    assert sys.stdout not in streams, (
        f"a StreamHandler targets sys.stdout, which corrupts CLI JSON output; "
        f"streams={streams!r}"
    )

    # structlog factory configured with file=sys.stderr — verify via the
    # configured logger's print target.
    logger = structlog.get_logger("swarmline.test")
    bound = logger.bind()  # materialise the underlying PrintLogger
    underlying_file = getattr(bound, "_file", None) or getattr(
        bound._logger,
        "_file",
        None,  # type: ignore[attr-defined]
    )
    assert underlying_file is sys.stderr, (
        f"structlog logger file is not sys.stderr; got {underlying_file!r}"
    )
