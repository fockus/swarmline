"""Tests: cognitia.sessions udalen, kanonichnyy modul - cognitia.session. Garantiruem, chto:
- cognitia.session eksportiruet vse nuzhnye klassy
- cognitia.sessions bolshe not sushchestvuet (udalen in v0.2.x)
"""

from __future__ import annotations

import pytest


class TestSessionsRemoved:
    """cognitia.sessions udalen, cognitia.session - edinstvennyy modul."""

    def test_sessions_package_not_importable(self) -> None:
        """import cognitia.sessions → ModuleNotFoundError."""
        with pytest.raises(ModuleNotFoundError):
            import cognitia.sessions  # type: ignore[import-not-found]  # noqa: F401

    def test_canonical_session_importable(self) -> None:
        """import cognitia.session works without oshibok."""
        from cognitia.session import (
            DefaultSessionRehydrator,
            InMemorySessionManager,
            SessionKey,
            SessionState,
        )

        assert DefaultSessionRehydrator is not None
        assert InMemorySessionManager is not None
        assert SessionKey is not None
        assert SessionState is not None
