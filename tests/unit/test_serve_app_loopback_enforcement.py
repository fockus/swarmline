"""Stage 19 (M-1) — loopback enforcement on create_app(allow_unauthenticated_query=True).

Mirrors the existing pattern from a2a/server.py and daemon/health.py:
the unauthenticated control-plane endpoint must be bound to a loopback host
(localhost / 127.0.0.1 / ::1). Any non-loopback host must be rejected at
factory time with a clear ValueError.
"""

from __future__ import annotations

import pytest

from swarmline.serve.app import create_app


class _DummyAgent:
    """Minimal agent stub — create_app does not actually call query() at construct time."""

    async def query(self, prompt: str) -> object:  # pragma: no cover
        raise NotImplementedError


@pytest.mark.parametrize(
    "host",
    ["0.0.0.0", "10.0.0.5", "192.168.1.1", "203.0.113.5", "example.com"],
)
def test_unauthenticated_query_with_non_loopback_host_raises(host: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        create_app(
            _DummyAgent(),
            allow_unauthenticated_query=True,
            host=host,
        )


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "localhost", "::1"],
)
def test_unauthenticated_query_with_loopback_host_ok(host: str) -> None:
    app = create_app(
        _DummyAgent(),
        allow_unauthenticated_query=True,
        host=host,
    )
    assert app is not None


def test_unauthenticated_query_no_host_warns_and_succeeds(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Backward-compat: legacy callers with no host param keep working but log a warning.

    structlog writes to stderr, so capsys (not caplog) is the right capture for the
    structured security_decision warning.
    """
    app = create_app(
        _DummyAgent(),
        allow_unauthenticated_query=True,
    )
    assert app is not None
    captured = capsys.readouterr()
    output = captured.err + captured.out
    assert "loopback" in output.lower() or "unauthenticated" in output.lower()


@pytest.mark.parametrize(
    "host",
    ["0.0.0.0", "127.0.0.1", "10.0.0.5", "::1"],
)
def test_authenticated_query_skips_loopback_check(host: str) -> None:
    """When auth_token is set, host is irrelevant — auth replaces the loopback gate."""
    app = create_app(
        _DummyAgent(),
        auth_token="secret-token",
        host=host,
    )
    assert app is not None


def test_no_query_no_host_check() -> None:
    """When neither auth nor allow_unauthenticated_query is set, host is irrelevant."""
    app = create_app(_DummyAgent(), host="0.0.0.0")
    assert app is not None
