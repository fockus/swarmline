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


def test_unauthenticated_query_no_host_raises_in_v151() -> None:
    """v1.5.1 closes audit P2 #5 — host=None + allow_unauthenticated_query=True
    now raises ValueError. The v1.5.0 deprecation warning has graduated to a
    hard error so the legacy combination cannot accidentally combine with
    ``uvicorn --host 0.0.0.0`` to expose unauthenticated /v1/query publicly.
    """
    with pytest.raises(ValueError, match="explicit host="):
        create_app(_DummyAgent(), allow_unauthenticated_query=True)


def test_unauthenticated_query_empty_string_host_raises() -> None:
    """Empty host string is treated like None — must raise."""
    with pytest.raises(ValueError, match="explicit host="):
        create_app(_DummyAgent(), allow_unauthenticated_query=True, host="")


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
