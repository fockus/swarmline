"""Unit tests -- `code_agent._session` (Stage 5).

Covers the `SWARMLINE_SESSIONS_DIR`-unset default-path edge case directly
(as a pure function), without touching the real filesystem -- the
integration tests in `tests/integration/code_agent/test_session_lifecycle.py`
always set the env var (or rely on the root `conftest.py` autouse override).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swarmline.code_agent._session import FacadeSessionStore, _default_sessions_root


class TestDefaultSessionsRoot:
    def test_default_sessions_root_falls_back_to_home_dot_swarmline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SWARMLINE_SESSIONS_DIR", raising=False)

        root = _default_sessions_root()

        assert root == Path.home() / ".swarmline" / "code-sessions"

    def test_default_sessions_root_honors_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SWARMLINE_SESSIONS_DIR", str(tmp_path))

        root = _default_sessions_root()

        assert root == tmp_path


class TestFacadeSessionStoreConstruction:
    def test_construction_does_not_touch_filesystem(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Constructing a store (even with no explicit `base_dir`) must not
        create any directory -- only `save()` does, lazily."""
        target = tmp_path / "never-created-until-save"
        monkeypatch.setenv("SWARMLINE_SESSIONS_DIR", str(target))

        FacadeSessionStore()

        assert not target.exists()
