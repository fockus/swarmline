"""Unit tests for ProjectInstructionFilter — auto-discovers and injects
project instruction files (CLAUDE.md, RULES.md, AGENTS.md, GEMINI.md)
into the system prompt via InputFilter protocol.

Requirements covered:
- INST-01: Auto-load from cwd → parent dirs → home
- INST-02: Supported formats (CLAUDE.md, AGENTS.md, GEMINI.md, RULES.md)
- INST-03: Priority: RULES.md > CLAUDE.md > AGENTS.md > GEMINI.md
- INST-04: Merge: home (lowest) → parent dirs → project root (highest)
- INST-05: Inject via InputFilter (no ThinRuntime.run() modification)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swarmline.runtime.types import Message
from swarmline.input_filters import InputFilter
from swarmline.project_instruction_filter import ProjectInstructionFilter


def _msg(role: str, content: str) -> Message:
    return Message(role=role, content=content)


# ---------------------------------------------------------------------------
# INST-05: Protocol compliance
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    def test_filter_implements_input_filter_protocol(self) -> None:
        f = ProjectInstructionFilter(cwd="/tmp")
        assert isinstance(f, InputFilter)


# ---------------------------------------------------------------------------
# INST-01 / INST-02: File discovery
# ---------------------------------------------------------------------------


class TestFileDiscovery:
    @pytest.mark.asyncio
    async def test_filter_discovers_claude_md_in_cwd(self, tmp_path: Path) -> None:
        """INST-01 + INST-02: discovers CLAUDE.md in current working dir."""
        (tmp_path / "CLAUDE.md").write_text("Project instructions here")
        f = ProjectInstructionFilter(cwd=tmp_path, home=tmp_path / "fakehome")

        msgs = [_msg("user", "hello")]
        result_msgs, result_prompt = await f.filter(msgs, "base prompt")

        assert "Project instructions here" in result_prompt
        assert result_msgs == msgs

    @pytest.mark.asyncio
    async def test_filter_discovers_rules_md_priority_over_claude_md(
        self, tmp_path: Path
    ) -> None:
        """INST-03: RULES.md has higher priority than CLAUDE.md at same level."""
        (tmp_path / "RULES.md").write_text("Rules content")
        (tmp_path / "CLAUDE.md").write_text("Claude content")
        f = ProjectInstructionFilter(cwd=tmp_path, home=tmp_path / "fakehome")

        _, result_prompt = await f.filter([], "base")

        # Only first-found-by-priority should be included at this level
        assert "Rules content" in result_prompt
        assert "Claude content" not in result_prompt

    @pytest.mark.asyncio
    async def test_filter_walks_up_to_parent_dirs(self, tmp_path: Path) -> None:
        """INST-01: walks from cwd up through parent directories."""
        parent = tmp_path / "a"
        child = parent / "b"
        child.mkdir(parents=True)
        (parent / "CLAUDE.md").write_text("Parent instructions")
        f = ProjectInstructionFilter(cwd=child, home=tmp_path / "fakehome")

        _, result_prompt = await f.filter([], "base")

        assert "Parent instructions" in result_prompt

    @pytest.mark.asyncio
    async def test_filter_walks_up_to_home_dir(self, tmp_path: Path) -> None:
        """INST-01: also checks home directory for instruction files."""
        home = tmp_path / "home"
        home.mkdir()
        project = tmp_path / "project"
        project.mkdir()
        (home / "CLAUDE.md").write_text("Home instructions")
        f = ProjectInstructionFilter(cwd=project, home=home)

        _, result_prompt = await f.filter([], "base")

        assert "Home instructions" in result_prompt


# ---------------------------------------------------------------------------
# INST-03: Priority order at same directory level
# ---------------------------------------------------------------------------


class TestFormatPriority:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("higher_file", "lower_file", "higher_content", "lower_content"),
        [
            ("RULES.md", "CLAUDE.md", "rules-wins", "claude-loses"),
            ("CLAUDE.md", "AGENTS.md", "claude-wins", "agents-loses"),
            ("AGENTS.md", "GEMINI.md", "agents-wins", "gemini-loses"),
            ("RULES.md", "GEMINI.md", "rules-wins", "gemini-loses"),
        ],
        ids=[
            "rules_over_claude",
            "claude_over_agents",
            "agents_over_gemini",
            "rules_over_gemini",
        ],
    )
    async def test_filter_format_priority_order(
        self,
        tmp_path: Path,
        higher_file: str,
        lower_file: str,
        higher_content: str,
        lower_content: str,
    ) -> None:
        """INST-03: first found by priority order wins at each directory level."""
        (tmp_path / higher_file).write_text(higher_content)
        (tmp_path / lower_file).write_text(lower_content)
        f = ProjectInstructionFilter(cwd=tmp_path, home=tmp_path / "fakehome")

        _, result_prompt = await f.filter([], "base")

        assert higher_content in result_prompt
        assert lower_content not in result_prompt


# ---------------------------------------------------------------------------
# INST-04: Merge strategy across directory levels
# ---------------------------------------------------------------------------


class TestMergeStrategy:
    @pytest.mark.asyncio
    async def test_filter_merge_strategy_project_root_highest(
        self, tmp_path: Path
    ) -> None:
        """INST-04: project root content appears LAST (highest priority)."""
        home = tmp_path / "home"
        home.mkdir()
        project = tmp_path / "project"
        project.mkdir()
        (home / "CLAUDE.md").write_text("HOME_INSTRUCTIONS")
        (project / "CLAUDE.md").write_text("PROJECT_INSTRUCTIONS")
        f = ProjectInstructionFilter(cwd=project, home=home)

        _, result_prompt = await f.filter([], "base")

        home_pos = result_prompt.index("HOME_INSTRUCTIONS")
        project_pos = result_prompt.index("PROJECT_INSTRUCTIONS")
        assert home_pos < project_pos

    @pytest.mark.asyncio
    async def test_filter_merge_strategy_home_lowest(self, tmp_path: Path) -> None:
        """INST-04: home content appears FIRST (lowest priority)."""
        home = tmp_path / "home"
        home.mkdir()
        parent = tmp_path / "project"
        child = parent / "sub"
        child.mkdir(parents=True)
        (home / "CLAUDE.md").write_text("HOME")
        (parent / "CLAUDE.md").write_text("PARENT")
        (child / "RULES.md").write_text("CHILD")
        f = ProjectInstructionFilter(cwd=child, home=home)

        _, result_prompt = await f.filter([], "base")

        # Order: home first, then parent, then child (cwd) last
        home_pos = result_prompt.index("HOME")
        parent_pos = result_prompt.index("PARENT")
        child_pos = result_prompt.index("CHILD")
        assert home_pos < parent_pos < child_pos

    @pytest.mark.asyncio
    async def test_filter_multiple_levels_merge(self, tmp_path: Path) -> None:
        """INST-04: content from all levels is concatenated."""
        home = tmp_path / "home"
        home.mkdir()
        level1 = tmp_path / "a"
        level2 = level1 / "b"
        level3 = level2 / "c"
        level3.mkdir(parents=True)
        (home / "GEMINI.md").write_text("HOME_CONTENT")
        (level1 / "CLAUDE.md").write_text("L1_CONTENT")
        (level2 / "AGENTS.md").write_text("L2_CONTENT")
        (level3 / "RULES.md").write_text("L3_CONTENT")
        f = ProjectInstructionFilter(cwd=level3, home=home)

        _, result_prompt = await f.filter([], "base")

        assert "HOME_CONTENT" in result_prompt
        assert "L1_CONTENT" in result_prompt
        assert "L2_CONTENT" in result_prompt
        assert "L3_CONTENT" in result_prompt


# ---------------------------------------------------------------------------
# INST-05: Injection into system prompt
# ---------------------------------------------------------------------------


class TestInjection:
    @pytest.mark.asyncio
    async def test_filter_injects_into_system_prompt_prepend(
        self, tmp_path: Path
    ) -> None:
        """INST-05: discovered content is prepended to system prompt."""
        (tmp_path / "CLAUDE.md").write_text("INJECTED")
        f = ProjectInstructionFilter(cwd=tmp_path, home=tmp_path / "fakehome")

        _, result_prompt = await f.filter([], "original system prompt")

        assert result_prompt.startswith("INJECTED")
        assert "original system prompt" in result_prompt

    @pytest.mark.asyncio
    async def test_filter_no_files_found_passthrough(self, tmp_path: Path) -> None:
        """INST-05: no instruction files → system prompt unchanged."""
        f = ProjectInstructionFilter(cwd=tmp_path, home=tmp_path / "fakehome")

        msgs = [_msg("user", "hi")]
        result_msgs, result_prompt = await f.filter(msgs, "original")

        assert result_prompt == "original"
        assert result_msgs == msgs


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_filter_empty_file_skipped(self, tmp_path: Path) -> None:
        """Empty instruction files are skipped."""
        (tmp_path / "CLAUDE.md").write_text("")
        (tmp_path / "AGENTS.md").write_text("real content")
        f = ProjectInstructionFilter(cwd=tmp_path, home=tmp_path / "fakehome")

        _, result_prompt = await f.filter([], "base")

        # CLAUDE.md is higher priority but empty — falls through to AGENTS.md
        assert "real content" in result_prompt


# ---------------------------------------------------------------------------
# Caching by mtime
# ---------------------------------------------------------------------------


class TestCaching:
    @pytest.mark.asyncio
    async def test_filter_caches_by_mtime(self, tmp_path: Path) -> None:
        """Repeated calls use cached content if mtime unchanged."""
        p = tmp_path / "CLAUDE.md"
        p.write_text("v1")
        f = ProjectInstructionFilter(cwd=tmp_path, home=tmp_path / "fakehome")

        _, prompt1 = await f.filter([], "base")
        # Overwrite with same mtime (no actual FS change detected)
        _, prompt2 = await f.filter([], "base")

        assert prompt1 == prompt2

    @pytest.mark.asyncio
    async def test_filter_skips_non_utf8_file(self, tmp_path: Path) -> None:
        """Non-UTF-8 files are gracefully skipped (no crash)."""
        p = tmp_path / "CLAUDE.md"
        p.write_bytes(b"\xff\xfe invalid utf-8 \x80\x81")
        f = ProjectInstructionFilter(cwd=tmp_path, home=tmp_path / "fakehome")

        msgs, result_prompt = await f.filter([], "base")

        assert result_prompt == "base"
        assert msgs == []

    @pytest.mark.asyncio
    async def test_filter_skips_symlinks(self, tmp_path: Path) -> None:
        """Symlinks to instruction files are skipped for security."""
        real_file = tmp_path / "real" / "CLAUDE.md"
        real_file.parent.mkdir()
        real_file.write_text("real content")
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "CLAUDE.md").symlink_to(real_file)
        f = ProjectInstructionFilter(cwd=project_dir, home=tmp_path / "fakehome")

        _, result_prompt = await f.filter([], "base")

        assert result_prompt == "base"

    @pytest.mark.asyncio
    async def test_filter_reloads_on_mtime_change(self, tmp_path: Path) -> None:
        """Content is re-read when file mtime changes."""
        import os
        import time

        p = tmp_path / "CLAUDE.md"
        p.write_text("v1")
        f = ProjectInstructionFilter(cwd=tmp_path, home=tmp_path / "fakehome")

        _, prompt1 = await f.filter([], "base")
        assert "v1" in prompt1

        # Force mtime change
        time.sleep(0.05)
        p.write_text("v2")
        # Ensure mtime is different
        new_mtime = os.path.getmtime(p) + 1
        os.utime(p, (new_mtime, new_mtime))

        _, prompt2 = await f.filter([], "base")
        assert "v2" in prompt2
        assert "v1" not in prompt2
