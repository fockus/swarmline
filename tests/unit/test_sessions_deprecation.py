"""Tests: swarmline.sessions udalen, kanonichnyy modul - swarmline.session. Garantiruem, chto:
- swarmline.session eksportiruet vse nuzhnye klassy
- swarmline.sessions bolshe not sushchestvuet (udalen in v0.2.x)
"""

from __future__ import annotations

import pytest


class TestSessionsRemoved:
    """swarmline.sessions udalen, swarmline.session - edinstvennyy modul."""

    def test_sessions_package_not_importable(self) -> None:
        """import swarmline.sessions → ModuleNotFoundError."""
        with pytest.raises(ModuleNotFoundError):
            import swarmline.sessions  # type: ignore[import-not-found]  # noqa: F401

    def test_canonical_session_importable(self) -> None:
        """import swarmline.session works without oshibok."""
        from swarmline.session import (
            DefaultSessionRehydrator,
            InMemorySessionManager,
            SessionKey,
            SessionState,
        )

        assert DefaultSessionRehydrator is not None
        assert InMemorySessionManager is not None
        assert SessionKey is not None
        assert SessionState is not None
