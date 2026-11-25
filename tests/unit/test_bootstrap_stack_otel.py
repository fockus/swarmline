"""Unit: SwarmlineStack opt-in OTel bootstrap flag (REQ-013, REQ-014).

observability-events spec, Task 4. ``SwarmlineStack.create(otel_from_env=...)``
threads an opt-in flag through to ``configure_otlp_from_env`` (existing,
0-caller helper in ``swarmline.observability.otlp_setup``). Default ``False``
-> behavior is byte-identical to before this flag existed (REQ-014): the
helper is never called, so it can never mutate global state / attempt an
SDK import even when installed.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from swarmline.bootstrap import SwarmlineStack


def _create_fixture_dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Minimal SwarmlineStack.create() fixture (mirrors test_bootstrap_stack.py)."""
    project_root = tmp_path / "project"
    project_root.mkdir()
    prompts_dir = project_root / "prompts"
    prompts_dir.mkdir()
    skills_dir = project_root / "skills"
    skills_dir.mkdir()

    (prompts_dir / "identity.md").write_text(
        "You are a helpful assistant.", encoding="utf-8"
    )
    (prompts_dir / "role_skills.yaml").write_text(
        "default:\n  skills: []\n  local_tools: []\n", encoding="utf-8"
    )
    (prompts_dir / "role_router.yaml").write_text(
        "default_role: default\nkeywords: {}\n", encoding="utf-8"
    )
    return project_root, prompts_dir, skills_dir


class TestSwarmlineStackOtelBootstrapFlag:
    """REQ-013/014: opt-in ``otel_from_env`` flag, default off, no behavior change."""

    def test_bootstrap_otel_flag_default_off_no_call(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Default (flag omitted) -> configure_otlp_from_env is NOT called."""
        project_root, prompts_dir, skills_dir = _create_fixture_dirs(tmp_path)
        mock_configure = MagicMock(name="configure_otlp_from_env")
        monkeypatch.setattr(
            "swarmline.observability.otlp_setup.configure_otlp_from_env",
            mock_configure,
        )

        stack = SwarmlineStack.create(
            prompts_dir=prompts_dir,
            skills_dir=skills_dir,
            project_root=project_root,
        )

        mock_configure.assert_not_called()
        assert isinstance(stack, SwarmlineStack)

    def test_bootstrap_otel_flag_explicit_false_no_call(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Explicit otel_from_env=False -> configure_otlp_from_env is NOT called."""
        project_root, prompts_dir, skills_dir = _create_fixture_dirs(tmp_path)
        mock_configure = MagicMock(name="configure_otlp_from_env")
        monkeypatch.setattr(
            "swarmline.observability.otlp_setup.configure_otlp_from_env",
            mock_configure,
        )

        SwarmlineStack.create(
            prompts_dir=prompts_dir,
            skills_dir=skills_dir,
            project_root=project_root,
            otel_from_env=False,
        )

        mock_configure.assert_not_called()

    def test_bootstrap_otel_flag_invokes_configure(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """otel_from_env=True -> configure_otlp_from_env WAS called once."""
        project_root, prompts_dir, skills_dir = _create_fixture_dirs(tmp_path)
        mock_configure = MagicMock(name="configure_otlp_from_env", return_value=None)
        monkeypatch.setattr(
            "swarmline.observability.otlp_setup.configure_otlp_from_env",
            mock_configure,
        )

        SwarmlineStack.create(
            prompts_dir=prompts_dir,
            skills_dir=skills_dir,
            project_root=project_root,
            otel_from_env=True,
        )

        mock_configure.assert_called_once()
