"""Regression: structlog stream-freeze isolation (OSS-BL-03 Cause 1).

Proves that ``_LazyStderrLoggerFactory`` + ``cache_logger_on_first_use=False``
prevents ``ValueError: I/O operation on closed file`` when ``sys.stderr`` is
replaced between log calls — the failure mode that occurred when
``click.testing.CliRunner`` ran a command, freezing the transient buffer onto
all module-level structlog proxies via ``cache_logger_on_first_use=True``.

This test is:
  RED  — against the old config (``PrintLoggerFactory(file=sys.stderr)`` +
          ``cache_logger_on_first_use=True``): the second ``log.info`` call
          raises ``ValueError`` because ``first_buf`` is closed.
  GREEN — after the fix (``_LazyStderrLoggerFactory()`` +
          ``cache_logger_on_first_use=False``): ``sys.stderr`` is re-read on
          each write, so the second call goes to ``second_buf`` without error.
"""

from __future__ import annotations

import io
import sys
from typing import Generator

import pytest
import structlog

from swarmline.observability.logger import (
    _LazyStderrLoggerFactory,
    _LazySysStderrLogger,
)


@pytest.fixture(autouse=True)
def _restore_structlog() -> Generator[None, None, None]:
    """Reset structlog global config after each test in this module."""
    yield
    structlog.reset_defaults()


class TestLazyStderrLoggerFactory:
    def test_log_after_stream_close_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Writing through a closed stream then a fresh stream must not raise.

        Arrange: configure structlog with the lazy factory + cache=False.
        Act:     log once, close the captured buffer, swap sys.stderr, log again.
        Assert:  no exception; second message appears in the new buffer.
        """
        structlog.configure(
            processors=[
                structlog.processors.add_log_level,
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
            context_class=dict,
            logger_factory=_LazyStderrLoggerFactory(),
            cache_logger_on_first_use=False,
        )

        log = structlog.get_logger("test.isolation")

        # Step 1: redirect sys.stderr to a controlled buffer and write one event.
        first_buf: io.StringIO = io.StringIO()
        monkeypatch.setattr(sys, "stderr", first_buf)
        log.info("first_message", step=1)

        # Step 2: close the buffer — simulates CliRunner teardown closing its
        # transient stderr capture after invoke() returns.
        first_buf.close()

        # Step 3: replace sys.stderr with a fresh buffer (simulates test cleanup
        # restoring the real stderr or pytest capturing it for the next test).
        second_buf: io.StringIO = io.StringIO()
        monkeypatch.setattr(sys, "stderr", second_buf)

        # Step 4: log again — must NOT raise ValueError even though first_buf
        # is closed.  The lazy factory resolves sys.stderr at write time, so it
        # picks up second_buf rather than the closed first_buf.
        log.info("second_message", step=2)  # KEY: no exception expected

        # Step 5: verify the second message reached the live buffer.
        second_buf.seek(0)
        content = second_buf.read()
        assert "second_message" in content

    def test_factory_creates_independent_instances(self) -> None:
        """Each factory call returns a distinct logger instance."""
        factory = _LazyStderrLoggerFactory()
        a = factory()
        b = factory()
        assert a is not b

    def test_logger_write_uses_current_stderr(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_LazySysStderrLogger.msg writes to whatever sys.stderr is at call time."""

        logger = _LazySysStderrLogger()
        buf: io.StringIO = io.StringIO()
        monkeypatch.setattr(sys, "stderr", buf)
        logger.msg("hello lazy")
        buf.seek(0)
        assert "hello lazy" in buf.read()

    def test_all_printlogger_methods_present(self) -> None:
        """_LazySysStderrLogger exposes the full structlog.PrintLogger method surface.

        RED before adding exception+failure aliases; GREEN after.
        structlog.PrintLogger's public methods (excluding dunder):
          critical, debug, err, error, exception, failure, fatal, info, log,
          msg, warn, warning.
        Any wrapper_class (stdlib.BoundLogger, make_filtering_bound_logger) may
        proxy any of these — missing one raises AttributeError at log-call time.
        """
        printlogger_methods = [
            "critical",
            "debug",
            "err",
            "error",
            "exception",
            "failure",
            "fatal",
            "info",
            "log",
            "msg",
            "warn",
            "warning",
        ]
        logger = _LazySysStderrLogger()
        missing = [
            m for m in printlogger_methods if not callable(getattr(logger, m, None))
        ]
        assert missing == [], f"_LazySysStderrLogger missing methods: {missing}"

    def test_exception_through_stdlib_bound_logger_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """log.exception() via stdlib.BoundLogger must not raise AttributeError.

        cli/_app.py uses wrapper_class=structlog.stdlib.BoundLogger.  BoundLogger
        proxies .exception() to the underlying logger's .exception() method.
        Before adding the alias, this raised:
            AttributeError: '_LazySysStderrLogger' object has no attribute 'exception'
        RED before the fix; GREEN after adding ``exception = _write``.
        """
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.stdlib.add_log_level,
                structlog.dev.ConsoleRenderer(),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            logger_factory=_LazyStderrLoggerFactory(),
            cache_logger_on_first_use=False,
        )

        log = structlog.get_logger("test.exception")
        buf: io.StringIO = io.StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        # Must not raise AttributeError or any other exception.
        try:
            raise ValueError("boom")
        except ValueError:
            log.exception(
                "something went wrong"
            )  # stdlib.BoundLogger proxies to .exception
