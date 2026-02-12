"""Тесты для cognitia.config — загрузчики конфигурации.

Iteration 2: TDD тесты для перенесённых loaders.
Testing Trophy: unit + integration (fixture YAML).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cognitia.config.role_router import RoleRouterConfig, load_role_router_config
from cognitia.config.role_skills import YamlRoleSkillsLoader

# ---------------------------------------------------------------------------
# YamlRoleSkillsLoader tests
# ---------------------------------------------------------------------------


class TestYamlRoleSkillsLoader:
    """Тесты YamlRoleSkillsLoader — реализация RoleSkillsProvider Protocol."""

    def test_load_skills_for_role(self, tmp_path: Path) -> None:
        """get_skills возвращает список skill_id для роли."""
        yaml_file = tmp_path / "role_skills.yaml"
        yaml_file.write_text(
            "coach:\n  skills: [iss, finuslugi]\n  local_tools: [calculate_goal_plan]\n",
            encoding="utf-8",
        )
        loader = YamlRoleSkillsLoader(yaml_file)
        assert loader.get_skills("coach") == ["iss", "finuslugi"]

    def test_load_local_tools_for_role(self, tmp_path: Path) -> None:
        """get_local_tools возвращает список local tools для роли."""
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
        """Для несуществующей роли возвращает пустые списки."""
        yaml_file = tmp_path / "role_skills.yaml"
        yaml_file.write_text("coach:\n  skills: []\n", encoding="utf-8")
        loader = YamlRoleSkillsLoader(yaml_file)
        assert loader.get_skills("nonexistent") == []
        assert loader.get_local_tools("nonexistent") == []

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """Отсутствующий файл → пустые списки для любой роли."""
        yaml_file = tmp_path / "nonexistent.yaml"
        loader = YamlRoleSkillsLoader(yaml_file)
        assert loader.get_skills("coach") == []
        assert loader.get_local_tools("coach") == []

    def test_list_roles(self, tmp_path: Path) -> None:
        """list_roles возвращает все ключи верхнего уровня."""
        yaml_file = tmp_path / "role_skills.yaml"
        yaml_file.write_text(
            "coach:\n  skills: []\ndiagnostician:\n  skills: []\ndeposit_advisor:\n  skills: []\n",
            encoding="utf-8",
        )
        loader = YamlRoleSkillsLoader(yaml_file)
        assert set(loader.list_roles()) == {"coach", "diagnostician", "deposit_advisor"}

    def test_satisfies_role_skills_provider_protocol(self, tmp_path: Path) -> None:
        """YamlRoleSkillsLoader удовлетворяет RoleSkillsProvider Protocol."""
        yaml_file = tmp_path / "role_skills.yaml"
        yaml_file.write_text("coach:\n  skills: []\n", encoding="utf-8")
        loader = YamlRoleSkillsLoader(yaml_file)
        # Структурная проверка наличия методов Protocol
        assert hasattr(loader, "get_skills")
        assert hasattr(loader, "get_local_tools")
        # Вызов не бросает исключений
        assert isinstance(loader.get_skills("coach"), list)
        assert isinstance(loader.get_local_tools("coach"), list)


# ---------------------------------------------------------------------------
# RoleRouterConfig + load_role_router_config tests
# ---------------------------------------------------------------------------


class TestRoleRouterConfig:
    """Тесты typed RoleRouterConfig dataclass."""

    def test_default_values(self) -> None:
        """Дефолтные значения: default_role='default', keywords={}."""
        config = RoleRouterConfig()
        assert config.default_role == "default"
        assert config.keywords == {}

    def test_frozen_dataclass(self) -> None:
        """RoleRouterConfig — frozen (immutable)."""
        config = RoleRouterConfig(default_role="coach")
        with pytest.raises(AttributeError):
            config.default_role = "other"  # type: ignore[misc]

    def test_custom_values(self) -> None:
        """Можно задать custom default_role и keywords."""
        config = RoleRouterConfig(
            default_role="coach",
            keywords={"deposit_advisor": ["вклад", "депозит"]},
        )
        assert config.default_role == "coach"
        assert config.keywords["deposit_advisor"] == ["вклад", "депозит"]


class TestLoadRoleRouterConfig:
    """Тесты load_role_router_config (YAML → RoleRouterConfig)."""

    def test_load_from_yaml(self, tmp_path: Path) -> None:
        """Загрузка из существующего YAML-файла."""
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
        """Отсутствующий файл → дефолтный config."""
        yaml_file = tmp_path / "nonexistent.yaml"
        config = load_role_router_config(yaml_file)
        assert config.default_role == "default"
        assert config.keywords == {}

    def test_empty_file_returns_defaults(self, tmp_path: Path) -> None:
        """Пустой YAML → дефолтный config."""
        yaml_file = tmp_path / "role_router.yaml"
        yaml_file.write_text("", encoding="utf-8")
        config = load_role_router_config(yaml_file)
        assert config.default_role == "default"
        assert config.keywords == {}

    def test_partial_yaml(self, tmp_path: Path) -> None:
        """YAML только с keywords (без default_role) → default_role='default'."""
        yaml_file = tmp_path / "role_router.yaml"
        yaml_file.write_text(
            "keywords:\n  credit_advisor:\n    - кредит\n",
            encoding="utf-8",
        )
        config = load_role_router_config(yaml_file)
        assert config.default_role == "default"
        assert "credit_advisor" in config.keywords
