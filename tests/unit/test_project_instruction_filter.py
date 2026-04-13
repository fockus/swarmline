"""Unit tests for ProjectInstructionFilter.

Behavior:
- Merge all instruction files found at each level
- Per-level order: AGENTS.md -> RULES.md -> CLAUDE.md -> GEMINI.md
- Level order: home (if outside walk-up path) -> outer parents -> cwd
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swarmline.input_filters import InputFilter
from swarmline.project_instruction_filter import ProjectInstructionFilter
from swarmline.runtime.types import Message


def _msg(role: str, content: str) -> Message:
    return Message(role=role, content=content)


class TestProtocol:
    def test_implements_input_filter(self) -> None:
        f = ProjectInstructionFilter(cwd="/tmp")
        assert isinstance(f, InputFilter)


class TestMergeBehavior:
    @pytest.mark.asyncio
    async def test_merges_all_files_on_same_level_in_repo_order(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "GEMINI.md").write_text("G")
        (tmp_path / "CLAUDE.md").write_text("C")
        (tmp_path / "RULES.md").write_text("R")
        (tmp_path / "AGENTS.md").write_text("A")

        f = ProjectInstructionFilter(cwd=tmp_path, home=tmp_path / "fakehome")
        _, prompt = await f.filter([_msg("user", "hi")], "BASE")

        a_pos = prompt.index("A")
        r_pos = prompt.index("R")
        c_pos = prompt.index("C")
        g_pos = prompt.index("G")
        base_pos = prompt.index("BASE")

        assert a_pos < r_pos < c_pos < g_pos < base_pos

    @pytest.mark.asyncio
    async def test_home_then_parents_then_cwd(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        root = tmp_path / "project"
        child = root / "child"
        home.mkdir()
        child.mkdir(parents=True)

        (home / "AGENTS.md").write_text("HOME")
        (root / "RULES.md").write_text("ROOT")
        (child / "CLAUDE.md").write_text("CHILD")

        f = ProjectInstructionFilter(cwd=child, home=home)
        _, prompt = await f.filter([], "BASE")

        assert prompt.index("HOME") < prompt.index("ROOT") < prompt.index("CHILD")

    @pytest.mark.asyncio
    async def test_home_skipped_when_home_is_ancestor_of_cwd(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / "home"
        project = home / "project"
        project.mkdir(parents=True)
        (home / "AGENTS.md").write_text("HOME_AGENTS")
        (project / "RULES.md").write_text("PROJECT_RULES")

        f = ProjectInstructionFilter(cwd=project, home=home)
        _, prompt = await f.filter([], "BASE")

        assert "HOME_AGENTS" in prompt
        assert "PROJECT_RULES" in prompt
        assert prompt.index("HOME_AGENTS") < prompt.index("PROJECT_RULES")

    @pytest.mark.asyncio
    async def test_empty_or_non_utf8_or_symlink_files_are_skipped(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "AGENTS.md").write_text("")
        (tmp_path / "RULES.md").write_bytes(b"\xff\xfebad")
        real = tmp_path / "real.md"
        real.write_text("real")
        (tmp_path / "CLAUDE.md").symlink_to(real)
        (tmp_path / "GEMINI.md").write_text("OK")

        f = ProjectInstructionFilter(cwd=tmp_path, home=tmp_path / "fakehome")
        _, prompt = await f.filter([], "BASE")

        assert "OK" in prompt
        assert "real" not in prompt
        assert prompt.endswith("BASE")

    @pytest.mark.asyncio
    async def test_no_instruction_files_passthrough(
        self, tmp_path: Path
    ) -> None:
        f = ProjectInstructionFilter(cwd=tmp_path, home=tmp_path / "fakehome")
        msgs = [_msg("user", "hello")]
        out_msgs, out_prompt = await f.filter(msgs, "base")
        assert out_msgs == msgs
        assert out_prompt == "base"

