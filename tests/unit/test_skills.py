"""Тесты для YamlSkillLoader и SkillRegistry."""

from pathlib import Path

import pytest

from cognitia.skills import LoadedSkill, SkillRegistry, YamlSkillLoader
from cognitia.skills.types import McpServerSpec, SkillSpec


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    """Создать временную директорию со скилами."""
    iss_dir = tmp_path / "iss"
    iss_dir.mkdir()

    # skill.yaml
    (iss_dir / "skill.yaml").write_text(
        """
id: iss
title: "MOEX ISS"
mcp:
  servers:
    - id: iss
      transport: url
      url: "https://calculado.ru/iss/mcp"
tools:
  include:
    - "mcp__iss__search_bonds"
    - "mcp__iss__get_emitter"
when:
  intents: ["bonds", "stocks"]
""",
        encoding="utf-8",
    )

    # INSTRUCTION.md
    (iss_dir / "INSTRUCTION.md").write_text(
        "# Skill ISS\nИспользуй для поиска ценных бумаг.",
        encoding="utf-8",
    )

    # Ещё один скилл
    funds_dir = tmp_path / "funds"
    funds_dir.mkdir()
    (funds_dir / "skill.yaml").write_text(
        """
id: funds
title: "ПИФы"
mcp:
  servers:
    - id: funds
      transport: url
      url: "https://calculado.ru/funds/mcp"
tools:
  include:
    - "mcp__funds__search"
""",
        encoding="utf-8",
    )
    (funds_dir / "INSTRUCTION.md").write_text(
        "# Skill Funds\nПоиск ПИФов.", encoding="utf-8"
    )

    return tmp_path


class TestYamlSkillLoader:
    """Тесты загрузки скилов из YAML."""

    def test_load_all_skills(self, skills_dir: Path) -> None:
        """Загружает все скилы из директории."""
        loader = YamlSkillLoader(skills_dir)
        skills = loader.load_all()
        assert len(skills) == 2

    def test_skill_spec_parsed(self, skills_dir: Path) -> None:
        """YAML парсится в SkillSpec корректно."""
        loader = YamlSkillLoader(skills_dir)
        skills = loader.load_all()
        # Найдём iss
        iss = next(s for s in skills if s.spec.skill_id == "iss")
        assert iss.spec.title == "MOEX ISS"
        assert len(iss.spec.mcp_servers) == 1
        assert iss.spec.mcp_servers[0].name == "iss"
        assert iss.spec.mcp_servers[0].url == "https://calculado.ru/iss/mcp"
        assert "mcp__iss__search_bonds" in iss.spec.tool_include

    def test_instruction_loaded(self, skills_dir: Path) -> None:
        """INSTRUCTION.md загружается."""
        loader = YamlSkillLoader(skills_dir)
        skills = loader.load_all()
        iss = next(s for s in skills if s.spec.skill_id == "iss")
        assert "Skill ISS" in iss.instruction_md

    def test_intents_parsed(self, skills_dir: Path) -> None:
        """Intents из when.intents парсятся."""
        loader = YamlSkillLoader(skills_dir)
        skills = loader.load_all()
        iss = next(s for s in skills if s.spec.skill_id == "iss")
        assert "bonds" in iss.spec.intents

    def test_empty_dir(self, tmp_path: Path) -> None:
        """Пустая директория возвращает пустой список."""
        loader = YamlSkillLoader(tmp_path)
        assert loader.load_all() == []

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        """Несуществующая директория возвращает пустой список."""
        loader = YamlSkillLoader(tmp_path / "nonexistent")
        assert loader.load_all() == []


class TestSkillRegistry:
    """Тесты реестра скилов."""

    def test_register_and_get(self, skills_dir: Path) -> None:
        """Регистрация и получение скилла."""
        loader = YamlSkillLoader(skills_dir)
        skills = loader.load_all()
        registry = SkillRegistry(skills)

        iss = registry.get("iss")
        assert iss is not None
        assert iss.spec.skill_id == "iss"

    def test_list_ids(self, skills_dir: Path) -> None:
        """Список id всех скилов."""
        loader = YamlSkillLoader(skills_dir)
        registry = SkillRegistry(loader.load_all())
        ids = registry.list_ids()
        assert "iss" in ids
        assert "funds" in ids

    def test_get_mcp_servers_for_skills(self, skills_dir: Path) -> None:
        """Получение MCP серверов для набора скилов."""
        loader = YamlSkillLoader(skills_dir)
        registry = SkillRegistry(loader.load_all())
        servers = registry.get_mcp_servers_for_skills(["iss", "funds"])
        assert "iss" in servers
        assert "funds" in servers

    def test_get_mcp_servers_filters_by_skill(self, skills_dir: Path) -> None:
        """Только серверы запрошенных скилов."""
        loader = YamlSkillLoader(skills_dir)
        registry = SkillRegistry(loader.load_all())
        servers = registry.get_mcp_servers_for_skills(["iss"])
        assert "iss" in servers
        assert "funds" not in servers

    def test_get_tool_allowlist(self, skills_dir: Path) -> None:
        """Allowlist tools для набора скилов."""
        loader = YamlSkillLoader(skills_dir)
        registry = SkillRegistry(loader.load_all())
        tools = registry.get_tool_allowlist(["iss"])
        assert "mcp__iss__search_bonds" in tools
        assert "mcp__iss__get_emitter" in tools

    def test_get_nonexistent(self, skills_dir: Path) -> None:
        """Несуществующий скилл возвращает None."""
        registry = SkillRegistry()
        assert registry.get("nonexistent") is None

    def test_settings_mcp_merged(self) -> None:
        """settings.json MCP мержатся с skill.yaml MCP (R-401, R-402)."""
        settings_mcp = {
            "extra_server": McpServerSpec(name="extra_server", url="http://extra"),
        }
        skill = LoadedSkill(
            spec=SkillSpec(
                skill_id="s1",
                title="S1",
                instruction_file="",
                mcp_servers=[McpServerSpec(name="s1_srv", url="http://s1")],
            ),
            instruction_md="",
        )
        registry = SkillRegistry([skill], settings_mcp=settings_mcp)
        servers = registry.get_mcp_servers_for_skills(["s1"])

        # skill.yaml MCP присутствует
        assert "s1_srv" in servers
        # settings.json MCP тоже присутствует
        assert "extra_server" in servers

    def test_skill_yaml_overrides_settings(self) -> None:
        """skill.yaml перезаписывает settings.json при конфликте имён (§2.1)."""
        settings_mcp = {
            "iss": McpServerSpec(name="iss", url="http://old-settings"),
        }
        skill = LoadedSkill(
            spec=SkillSpec(
                skill_id="iss",
                title="ISS",
                instruction_file="",
                mcp_servers=[McpServerSpec(name="iss", url="http://new-yaml")],
            ),
            instruction_md="",
        )
        registry = SkillRegistry([skill], settings_mcp=settings_mcp)
        servers = registry.get_mcp_servers_for_skills(["iss"])

        # skill.yaml имеет приоритет
        assert servers["iss"].url == "http://new-yaml"

    def test_settings_mcp_without_skills(self) -> None:
        """settings.json MCP доступны даже без skill.yaml MCP."""
        settings_mcp = {
            "standalone": McpServerSpec(name="standalone", url="http://standalone"),
        }
        registry = SkillRegistry(settings_mcp=settings_mcp)
        servers = registry.get_mcp_servers_for_skills([])

        assert "standalone" in servers
