"""Tests for the ``available_files`` layer (P4.5) of DefaultContextBuilder.

Split out of ``test_context.py`` to respect the file-size ceiling (Stage P1
fix cycle 1, MAJOR 2) -- the ``available_files`` param injects the
FileRegistry's ``.registry.md`` markdown ("## Available Files") into the
assembled system prompt.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from swarmline.context import ContextBudget, ContextInput, DefaultContextBuilder


@pytest.fixture
def prompts_dir(tmp_path: Path) -> Path:
    (tmp_path / "identity.md").write_text("Ты — Freedom AI, финансовый ментор.")
    (tmp_path / "guardrails.md").write_text("Не давай инвестрекомендаций.")
    return tmp_path


@pytest.fixture
def builder(prompts_dir: Path) -> DefaultContextBuilder:
    return DefaultContextBuilder(prompts_dir)


def _make_inp(budget: ContextBudget | None = None) -> ContextInput:
    return ContextInput(
        user_id="u1",
        topic_id="t1",
        role_id="coach",
        user_text="тест",
        active_skill_ids=[],
        budget=budget or ContextBudget(),
    )


class TestAvailableFilesLayer:
    """Tests for pack P4.5 - available_files (FileRegistry injection)."""

    @pytest.mark.asyncio
    async def test_available_files_included_in_prompt(
        self,
        builder: DefaultContextBuilder,
    ) -> None:
        """FileRegistry markdown passed as available_files appears in the prompt."""
        result = await builder.build(
            _make_inp(),
            available_files="- `notes/step_1.md`: analysis of X",
        )
        assert "## Available Files" in result.system_prompt
        assert "notes/step_1.md" in result.system_prompt

    @pytest.mark.asyncio
    async def test_available_files_none_no_pack(
        self,
        builder: DefaultContextBuilder,
    ) -> None:
        """available_files=None (default) - no pack added, byte-identical to before."""
        result = await builder.build(_make_inp())
        assert "## Available Files" not in result.system_prompt

    @pytest.mark.asyncio
    async def test_available_files_truncated_by_budget(
        self,
        builder: DefaultContextBuilder,
    ) -> None:
        """A large registry is truncated to budget.artifacts_max."""
        inp = _make_inp(budget=ContextBudget(artifacts_max=10))
        result = await builder.build(inp, available_files="x" * 2000)
        assert "available_files" in result.truncated_packs

    @pytest.mark.asyncio
    async def test_default_artifacts_max(self) -> None:
        """Po umolchaniyu artifacts_max = 1500."""
        assert ContextBudget().artifacts_max == 1500
