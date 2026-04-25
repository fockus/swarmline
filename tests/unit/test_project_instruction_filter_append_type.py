"""Stage 3 (Sprint 1A): lock the segments-list type contract in
ProjectInstructionFilter._collect_walk_up.

Background: type annotation `segments: list[tuple[int, str]]` was wrong — each
level produces `list[str]` (multiple instruction files merged later), not a
single string. ty correctly flagged `segments.append((depth, contents))` as
appending `tuple[int, list[str]]` to `list[tuple[int, str]]`.

Behaviour was already correct (downstream `extend(level_contents)` iterates the
list); only the annotation was lying. These tests:
1. Verify multi-level merge still produces correct output (regression guard)
2. Lock the corrected annotation via the source-text invariant
"""

from __future__ import annotations

import inspect
import textwrap
from pathlib import Path

import pytest

from swarmline.project_instruction_filter import ProjectInstructionFilter


@pytest.fixture
def project_tree(tmp_path: Path) -> Path:
    """Create 3-level CLAUDE.md tree: tmp_path / sub / leaf."""
    sub = tmp_path / "sub"
    leaf = sub / "leaf"
    leaf.mkdir(parents=True)
    (tmp_path / "CLAUDE.md").write_text("ROOT_INSTRUCTIONS\n", encoding="utf-8")
    (sub / "CLAUDE.md").write_text("SUB_INSTRUCTIONS\n", encoding="utf-8")
    (leaf / "CLAUDE.md").write_text("LEAF_INSTRUCTIONS\n", encoding="utf-8")
    return leaf


def test_collect_walk_up_merges_multi_level_correctly(project_tree: Path) -> None:
    """Walk from leaf → root, merge with outermost first → leaf last."""
    flt = ProjectInstructionFilter(cwd=project_tree, home=Path("/nonexistent"))
    merged = flt._collect_walk_up()
    assert merged == [
        "ROOT_INSTRUCTIONS",
        "SUB_INSTRUCTIONS",
        "LEAF_INSTRUCTIONS",
    ]


def test_collect_walk_up_handles_multiple_files_per_level(tmp_path: Path) -> None:
    """A single directory can produce multiple instruction files (CLAUDE.md +
    other INSTRUCTION_FILES) — segments must hold list[str], not str."""
    (tmp_path / "CLAUDE.md").write_text("CLAUDE_CONTENT\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("AGENTS_CONTENT\n", encoding="utf-8")
    flt = ProjectInstructionFilter(cwd=tmp_path, home=Path("/nonexistent"))
    merged = flt._collect_walk_up()
    # Both files at the same level — merged in INSTRUCTION_FILES order
    assert "CLAUDE_CONTENT" in merged
    assert "AGENTS_CONTENT" in merged


def test_segments_annotation_is_list_of_str_not_single_str() -> None:
    """Source-level invariant: `segments` declared as list[tuple[int, list[str]]].

    This locks the type-annotation fix from Stage 3 — without it `ty` would
    re-flag line 90 as soon as someone reverts the annotation.
    """
    source = inspect.getsource(ProjectInstructionFilter._collect_walk_up)
    source = textwrap.dedent(source)
    # Must annotate segments as list of (int, list[str]) — not (int, str)
    assert "segments: list[tuple[int, list[str]]]" in source, (
        "Expected annotation `segments: list[tuple[int, list[str]]]` "
        "in _collect_walk_up. Did the fix regress to `list[tuple[int, str]]`?"
    )
    # Negative: old wrong annotation must not reappear
    assert "segments: list[tuple[int, str]]" not in source
