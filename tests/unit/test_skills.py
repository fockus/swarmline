"""Tests for YamlSkillLoader and SkillRegistry."""

from pathlib import Path

import pytest
from swarmline.skills import LoadedSkill, SkillRegistry, YamlSkillLoader
from swarmline.skills.types import McpServerSpec, SkillSpec


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    """Create vremennuyu directory so skilami."""
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

    # Eshche odin skill
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
    """Tests zagruzki skilov from YAML."""

    def test_load_all_skills(self, skills_dir: Path) -> None:
        """Loads vse skily from direktorii."""
        loader = YamlSkillLoader(skills_dir)
        skills = loader.load_all()
        assert len(skills) == 2

    def test_skill_spec_parsed(self, skills_dir: Path) -> None:
        """YAML parsitsya in SkillSpec correctly."""
        loader = YamlSkillLoader(skills_dir)
        skills = loader.load_all()
        # Naydem iss
        iss = next(s for s in skills if s.spec.skill_id == "iss")
        assert iss.spec.title == "MOEX ISS"
        assert len(iss.spec.mcp_servers) == 1
        assert iss.spec.mcp_servers[0].name == "iss"
        assert iss.spec.mcp_servers[0].url == "https://calculado.ru/iss/mcp"
        assert iss.spec.mcp_servers[0].allow_private_network is False
        assert "mcp__iss__search_bonds" in iss.spec.tool_include

    def test_instruction_loaded(self, skills_dir: Path) -> None:
        """INSTRUCTION.md loadssya."""
        loader = YamlSkillLoader(skills_dir)
        skills = loader.load_all()
        iss = next(s for s in skills if s.spec.skill_id == "iss")
        assert "Skill ISS" in iss.instruction_md

    def test_intents_parsed(self, skills_dir: Path) -> None:
        """Intents from when.intents parsyatsya."""
        loader = YamlSkillLoader(skills_dir)
        skills = loader.load_all()
        iss = next(s for s in skills if s.spec.skill_id == "iss")
        assert "bonds" in iss.spec.intents

    def test_description_parsed_from_yaml(self, skills_dir: Path) -> None:
        """Description from skill.yaml is parsed into SkillSpec."""
        # Add description to iss skill.yaml
        iss_yaml = skills_dir / "iss" / "skill.yaml"
        iss_yaml.write_text(
            """
id: iss
title: "MOEX ISS"
description: "Search bonds and stocks on Moscow Exchange"
mcp:
  servers:
    - id: iss
      transport: url
      url: "https://calculado.ru/iss/mcp"
tools:
  include:
    - "mcp__iss__search_bonds"
""",
            encoding="utf-8",
        )
        loader = YamlSkillLoader(skills_dir)
        skills = loader.load_all()
        iss = next(s for s in skills if s.spec.skill_id == "iss")
        assert iss.spec.description == "Search bonds and stocks on Moscow Exchange"

    def test_description_defaults_to_empty(self, skills_dir: Path) -> None:
        """Description defaults to empty string when not specified."""
        loader = YamlSkillLoader(skills_dir)
        skills = loader.load_all()
        funds = next(s for s in skills if s.spec.skill_id == "funds")
        assert funds.spec.description == ""

    def test_path_traversal_blocked(self, tmp_path: Path) -> None:
        """instruction path outside project_root is rejected (security)."""
        skill_dir = tmp_path / "evil"
        skill_dir.mkdir()
        (skill_dir / "skill.yaml").write_text(
            'id: evil\ntitle: Evil\ninstruction: "/etc/passwd"',
            encoding="utf-8",
        )
        (skill_dir / "INSTRUCTION.md").write_text("Safe fallback", encoding="utf-8")

        loader = YamlSkillLoader(tmp_path)
        skills = loader.load_all()
        assert len(skills) == 1
        # Should fall back to INSTRUCTION.md, not /etc/passwd
        assert "Safe fallback" in skills[0].instruction_md

    def test_empty_dir(self, tmp_path: Path) -> None:
        """Empty directory returns empty list."""
        loader = YamlSkillLoader(tmp_path)
        assert loader.load_all() == []

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        """Notsushchestvuyushchaya directory returns empty list."""
        loader = YamlSkillLoader(tmp_path / "nonexistent")
        assert loader.load_all() == []

    def test_symlinked_skill_yaml_is_rejected(self, tmp_path: Path) -> None:
        """skill.yaml symlink must not be read even inside project_root."""
        target = tmp_path / "outside.yaml"
        target.write_text("id: outside\ntitle: Outside", encoding="utf-8")

        skill_dir = tmp_path / "evil"
        skill_dir.mkdir()
        (skill_dir / "skill.yaml").symlink_to(target)
        (skill_dir / "INSTRUCTION.md").write_text("ignored", encoding="utf-8")

        loader = YamlSkillLoader(tmp_path)
        assert loader.load_all() == []

    def test_symlinked_skill_md_is_rejected(self, tmp_path: Path) -> None:
        """SKILL.md symlink must not be read even inside project_root."""
        target = tmp_path / "outside.md"
        target.write_text(
            "---\nname: outside\ndescription: bad\n---\n# outside",
            encoding="utf-8",
        )

        skill_dir = tmp_path / "evil"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").symlink_to(target)

        loader = YamlSkillLoader(tmp_path)
        assert loader.load_all() == []


class TestSkillRegistry:
    """Tests reestra skilov."""

    def test_register_and_get(self, skills_dir: Path) -> None:
        """Registratsiya and receiving skilla."""
        loader = YamlSkillLoader(skills_dir)
        skills = loader.load_all()
        registry = SkillRegistry(skills)

        iss = registry.get("iss")
        assert iss is not None
        assert iss.spec.skill_id == "iss"

    def test_list_ids(self, skills_dir: Path) -> None:
        """List id vseh skilov."""
        loader = YamlSkillLoader(skills_dir)
        registry = SkillRegistry(loader.load_all())
        ids = registry.list_ids()
        assert "iss" in ids
        assert "funds" in ids

    def test_get_mcp_servers_for_skills(self, skills_dir: Path) -> None:
        """Receiving MCP serverov for seta skilov."""
        loader = YamlSkillLoader(skills_dir)
        registry = SkillRegistry(loader.load_all())
        servers = registry.get_mcp_servers_for_skills(["iss", "funds"])
        assert "iss" in servers
        assert "funds" in servers

    def test_get_mcp_servers_filters_by_skill(self, skills_dir: Path) -> None:
        """Tolko servery zaproshennyh skilov."""
        loader = YamlSkillLoader(skills_dir)
        registry = SkillRegistry(loader.load_all())
        servers = registry.get_mcp_servers_for_skills(["iss"])
        assert "iss" in servers
        assert "funds" not in servers

    def test_get_tool_allowlist(self, skills_dir: Path) -> None:
        """Allowlist tools for seta skilov."""
        loader = YamlSkillLoader(skills_dir)
        registry = SkillRegistry(loader.load_all())
        tools = registry.get_tool_allowlist(["iss"])
        assert "mcp__iss__search_bonds" in tools
        assert "mcp__iss__get_emitter" in tools

    def test_get_nonexistent(self, skills_dir: Path) -> None:
        """Notsushchestvuyushchiy skill returns None."""
        registry = SkillRegistry()
        assert registry.get("nonexistent") is None

    def test_settings_mcp_merged(self) -> None:
        """settings.json MCP merzhatsya with skill.yaml MCP (R-401, R-402)."""
        settings_mcp = {
            "extra_server": McpServerSpec(
                name="extra_server", url="https://extra.example"
            ),
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

        # skill.yaml MCP prisutstvuet
        assert "s1_srv" in servers
        # settings.json MCP tozhe prisutstvuet
        assert "extra_server" in servers

    def test_skill_yaml_overrides_settings(self) -> None:
        """skill.yaml overwrites settings.json pri konflikte imen (§2.1)."""
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

        # skill.yaml imeet prioritet
        assert servers["iss"].url == "http://new-yaml"

    def test_settings_mcp_without_skills(self) -> None:
        """settings.json MCP available dazhe without skill.yaml MCP."""
        settings_mcp = {
            "standalone": McpServerSpec(name="standalone", url="http://standalone"),
        }
        registry = SkillRegistry(settings_mcp=settings_mcp)
        servers = registry.get_mcp_servers_for_skills([])

        assert "standalone" in servers


class TestSkillMdFormat:
    """Tests for SKILL.md (Claude Code compatible) format."""

    def test_load_skill_md_format(self, tmp_path: Path) -> None:
        """SKILL.md with frontmatter is loaded as a skill."""
        skill_dir = tmp_path / "demo"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            """---
name: demo
description: "Demo skill for testing"
---

# Demo Skill

Use this tool for demo purposes.
""",
            encoding="utf-8",
        )
        loader = YamlSkillLoader(tmp_path)
        skills = loader.load_all()
        assert len(skills) == 1
        demo = skills[0]
        assert demo.spec.skill_id == "demo"
        assert demo.spec.description == "Demo skill for testing"
        assert "# Demo Skill" in demo.instruction_md
        assert "Use this tool for demo purposes." in demo.instruction_md

    def test_skill_md_allowed_tools_mapped(self, tmp_path: Path) -> None:
        """allowed-tools from SKILL.md frontmatter maps to tool_include."""
        skill_dir = tmp_path / "writer"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            """---
name: writer
description: "File writer skill"
allowed-tools:
  - Bash
  - Write
  - Read
---

Write files as needed.
""",
            encoding="utf-8",
        )
        loader = YamlSkillLoader(tmp_path)
        skills = loader.load_all()
        writer = skills[0]
        assert "Bash" in writer.spec.tool_include
        assert "Write" in writer.spec.tool_include
        assert "Read" in writer.spec.tool_include

    def test_skill_yaml_priority_over_skill_md(self, tmp_path: Path) -> None:
        """skill.yaml takes priority when both skill.yaml and SKILL.md exist."""
        skill_dir = tmp_path / "dual"
        skill_dir.mkdir()
        (skill_dir / "skill.yaml").write_text(
            """
id: dual
title: "From YAML"
""",
            encoding="utf-8",
        )
        (skill_dir / "INSTRUCTION.md").write_text("YAML instruction", encoding="utf-8")
        (skill_dir / "SKILL.md").write_text(
            """---
name: dual
description: "From SKILL.md"
---

SKILL.md instruction
""",
            encoding="utf-8",
        )
        loader = YamlSkillLoader(tmp_path)
        skills = loader.load_all()
        assert len(skills) == 1
        assert skills[0].spec.title == "From YAML"
        assert "YAML instruction" in skills[0].instruction_md

    def test_skill_md_name_defaults_to_dirname(self, tmp_path: Path) -> None:
        """When name is missing in SKILL.md frontmatter, use directory name."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            """---
description: "A skill without name field"
---

Instructions here.
""",
            encoding="utf-8",
        )
        loader = YamlSkillLoader(tmp_path)
        skills = loader.load_all()
        assert skills[0].spec.skill_id == "my-skill"

    def test_skill_md_with_mcp_servers(self, tmp_path: Path) -> None:
        """SKILL.md can declare MCP servers (Swarmline extension)."""
        skill_dir = tmp_path / "mcp-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            """---
name: mcp-skill
description: "Skill with MCP"
mcp-servers:
  - name: my-server
    transport: url
    url: "https://example.com/mcp"
---

Use my-server tools.
""",
            encoding="utf-8",
        )
        loader = YamlSkillLoader(tmp_path)
        skills = loader.load_all()
        assert len(skills[0].spec.mcp_servers) == 1
        assert skills[0].spec.mcp_servers[0].name == "my-server"

    def test_skill_md_with_intents(self, tmp_path: Path) -> None:
        """SKILL.md can declare intents (Swarmline extension)."""
        skill_dir = tmp_path / "intent-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            """---
name: intent-skill
description: "Skill with intents"
intents: [search, browse]
---

Search and browse.
""",
            encoding="utf-8",
        )
        loader = YamlSkillLoader(tmp_path)
        skills = loader.load_all()
        assert "search" in skills[0].spec.intents
        assert "browse" in skills[0].spec.intents

    def test_skill_md_no_frontmatter_skipped(self, tmp_path: Path) -> None:
        """SKILL.md without valid frontmatter is skipped."""
        skill_dir = tmp_path / "bad"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "# No frontmatter\nJust markdown.",
            encoding="utf-8",
        )
        loader = YamlSkillLoader(tmp_path)
        skills = loader.load_all()
        assert len(skills) == 0

    def test_mixed_formats_loaded(self, tmp_path: Path) -> None:
        """Both skill.yaml and SKILL.md skills load together."""
        # YAML skill
        yaml_dir = tmp_path / "yaml-skill"
        yaml_dir.mkdir()
        (yaml_dir / "skill.yaml").write_text(
            'id: yaml-skill\ntitle: "YAML Skill"',
            encoding="utf-8",
        )
        (yaml_dir / "INSTRUCTION.md").write_text("YAML instructions", encoding="utf-8")

        # SKILL.md skill
        md_dir = tmp_path / "md-skill"
        md_dir.mkdir()
        (md_dir / "SKILL.md").write_text(
            '---\nname: md-skill\ndescription: "MD Skill"\n---\n\nMD instructions',
            encoding="utf-8",
        )

        loader = YamlSkillLoader(tmp_path)
        skills = loader.load_all()
        ids = {s.spec.skill_id for s in skills}
        assert ids == {"yaml-skill", "md-skill"}
