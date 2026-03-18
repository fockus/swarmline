"""Tests for cognitia.config - configuration loaders. Iteration 2: TDD tests for migrated loaders.
Testing Trophy: unit + integration (fixture YAML)."""

from __future__ import annotations

from pathlib import Path

import pytest
from cognitia.config.role_router import RoleRouterConfig, load_role_router_config
from cognitia.config.role_skills import YamlRoleSkillsLoader

# ---------------------------------------------------------------------------
# YamlRoleSkillsLoader tests
# ---------------------------------------------------------------------------


class TestYamlRoleSkillsLoader:
    """Tests YamlRoleSkillsLoader - implementation of the RoleSkillsProvider Protocol."""

    def test_load_skills_for_role(self, tmp_path: Path) -> None:
        """get_skills returns list skill_id for the role."""
        yaml_file = tmp_path / "role_skills.yaml"
        yaml_file.write_text(
            "coach:\n  skills: [iss, finuslugi]\n  local_tools: [calculate_goal_plan]\n",
            encoding="utf-8",
        )
        loader = YamlRoleSkillsLoader(yaml_file)
        assert loader.get_skills("coach") == ["iss", "finuslugi"]

    def test_load_local_tools_for_role(self, tmp_path: Path) -> None:
        """get_local_tools returns list local tools for the role."""
        yaml_file = tmp_path / "role_skills.yaml"
        yaml_file.write_text(
            "diagnostician:\n  skills: []\n  local_tools: [save_diagnosis, assess_health_score]\n",
            encoding="utf-8",
        )
        loader = YamlRoleSkillsLoader(yaml_file)
        assert loader.get_local_tools("diagnostician") == [
            "save_diagnosis",
            "assess_health_score",
        ]

    def test_missing_role_returns_empty(self, tmp_path: Path) -> None:
        """For a not existing role returns empty lists."""
        yaml_file = tmp_path / "role_skills.yaml"
        yaml_file.write_text("coach:\n  skills: []\n", encoding="utf-8")
        loader = YamlRoleSkillsLoader(yaml_file)
        assert loader.get_skills("nonexistent") == []
        assert loader.get_local_tools("nonexistent") == []

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """Missing file -> empty lists for any role."""
        yaml_file = tmp_path / "nonexistent.yaml"
        loader = YamlRoleSkillsLoader(yaml_file)
        assert loader.get_skills("coach") == []
        assert loader.get_local_tools("coach") == []

    def test_list_roles(self, tmp_path: Path) -> None:
        """list_roles returns all top-level keys."""
        yaml_file = tmp_path / "role_skills.yaml"
        yaml_file.write_text(
            "coach:\n  skills: []\ndiagnostician:\n  skills: []\ndeposit_advisor:\n  skills: []\n",
            encoding="utf-8",
        )
        loader = YamlRoleSkillsLoader(yaml_file)
        assert set(loader.list_roles()) == {"coach", "diagnostician", "deposit_advisor"}

    def test_satisfies_role_skills_provider_protocol(self, tmp_path: Path) -> None:
        """YamlRoleSkillsLoader satisfies RoleSkillsProvider Protocol."""
        yaml_file = tmp_path / "role_skills.yaml"
        yaml_file.write_text("coach:\n  skills: []\n", encoding="utf-8")
        loader = YamlRoleSkillsLoader(yaml_file)
        # Structural check for the presence of Protocol methods
        assert hasattr(loader, "get_skills")
        assert hasattr(loader, "get_local_tools")
        # Calling not throws exceptions
        assert isinstance(loader.get_skills("coach"), list)
        assert isinstance(loader.get_local_tools("coach"), list)


# ---------------------------------------------------------------------------
# RoleRouterConfig + load_role_router_config tests
# ---------------------------------------------------------------------------


class TestRoleRouterConfig:
    """Tests typed RoleRouterConfig dataclass."""

    def test_default_values(self) -> None:
        """Default values: default_role='default', keywords={}."""
        config = RoleRouterConfig()
        assert config.default_role == "default"
        assert config.keywords == {}

    def test_frozen_dataclass(self) -> None:
        """RoleRouterConfig — frozen (immutable)."""
        config = RoleRouterConfig(default_role="coach")
        with pytest.raises(AttributeError):
            config.default_role = "other"  # type: ignore[misc]

    def test_custom_values(self) -> None:
        """You can set custom default_role and keywords."""
        config = RoleRouterConfig(
            default_role="coach",
            keywords={"deposit_advisor": ["вклад", "депозит"]},
        )
        assert config.default_role == "coach"
        assert config.keywords["deposit_advisor"] == ["вклад", "депозит"]


class TestLoadRoleRouterConfig:
    """Tests load_role_router_config (YAML -> RoleRouterConfig)."""

    def test_load_from_yaml(self, tmp_path: Path) -> None:
        """Loading from an existing YAML file."""
        yaml_file = tmp_path / "role_router.yaml"
        yaml_file.write_text(
            "default_role: coach\nkeywords:\n  deposit_advisor:\n    - вклад\n    - депозит\n",
            encoding="utf-8",
        )
        config = load_role_router_config(yaml_file)
        assert isinstance(config, RoleRouterConfig)
        assert config.default_role == "coach"
        assert "deposit_advisor" in config.keywords
        assert "вклад" in config.keywords["deposit_advisor"]

    def test_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        """Missing file -> default config."""
        yaml_file = tmp_path / "nonexistent.yaml"
        config = load_role_router_config(yaml_file)
        assert config.default_role == "default"
        assert config.keywords == {}

    def test_empty_file_returns_defaults(self, tmp_path: Path) -> None:
        """Empty YAML -> default config."""
        yaml_file = tmp_path / "role_router.yaml"
        yaml_file.write_text("", encoding="utf-8")
        config = load_role_router_config(yaml_file)
        assert config.default_role == "default"
        assert config.keywords == {}

    def test_partial_yaml(self, tmp_path: Path) -> None:
        """YAML only with keywords (without default_role) -> default_role='default'."""
        yaml_file = tmp_path / "role_router.yaml"
        yaml_file.write_text(
            "keywords:\n  credit_advisor:\n    - кредит\n",
            encoding="utf-8",
        )
        config = load_role_router_config(yaml_file)
        assert config.default_role == "default"
        assert "credit_advisor" in config.keywords
