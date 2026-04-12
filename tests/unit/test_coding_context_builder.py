"""Tests for CodingContextAssembler — CCTX-01, CCTX-02.

RED phase: tests define the contract for coding context assembly.

CCTX-01: Coding mode assembles 6 slices (task, board, workspace, search, session, skill_profile);
          non-coding mode excludes those slices.
CCTX-02: Budget discipline — deterministic truncation/omission under pressure.
"""

from __future__ import annotations

import pytest

from swarmline.context.budget import ContextBudget, estimate_tokens
from swarmline.context.coding_context_builder import (
    CodingContextAssembler,
    CodingContextResult,
    CodingSliceInput,
)


# ---------------------------------------------------------------------------
# Helpers — minimal frozen slice data
# ---------------------------------------------------------------------------


def _make_slice_input(
    *,
    coding_mode: bool = True,
    task_text: str = "Fix auth bug in login flow",
    board_text: str = "Sprint 42: 3 tasks remaining",
    workspace_text: str = "cwd=/app, branch=feat/auth",
    search_text: str = "grep: auth_handler.py:42",
    session_text: str = "session=s-123, turns=5",
    skill_profile_text: str = "Python senior, TDD, async-first",
    budget: ContextBudget | None = None,
) -> CodingSliceInput:
    """Build a CodingSliceInput with all 6 slices populated."""
    return CodingSliceInput(
        coding_mode=coding_mode,
        task=task_text,
        board=board_text,
        workspace=workspace_text,
        search=search_text,
        session=session_text,
        skill_profile=skill_profile_text,
        budget=budget or ContextBudget(),
    )


# ---------------------------------------------------------------------------
# CCTX-01: Coding mode includes 6 slices; non-coding excludes them
# ---------------------------------------------------------------------------


class TestCodingContextSliceAssembly:
    """CodingContextAssembler includes/excludes slices based on coding_mode."""

    def test_coding_mode_includes_task_slice(self) -> None:
        """Coding mode output contains the task slice text."""
        assembler = CodingContextAssembler()
        inp = _make_slice_input(coding_mode=True)
        result = assembler.assemble(inp)

        assert "Fix auth bug" in result.context_text

    def test_coding_mode_includes_board_slice(self) -> None:
        """Coding mode output contains the board slice text."""
        assembler = CodingContextAssembler()
        inp = _make_slice_input(coding_mode=True)
        result = assembler.assemble(inp)

        assert "Sprint 42" in result.context_text

    def test_coding_mode_includes_workspace_slice(self) -> None:
        """Coding mode output contains the workspace slice text."""
        assembler = CodingContextAssembler()
        inp = _make_slice_input(coding_mode=True)
        result = assembler.assemble(inp)

        assert "cwd=/app" in result.context_text

    def test_coding_mode_includes_search_slice(self) -> None:
        """Coding mode output contains the search slice text."""
        assembler = CodingContextAssembler()
        inp = _make_slice_input(coding_mode=True)
        result = assembler.assemble(inp)

        assert "auth_handler.py" in result.context_text

    def test_coding_mode_includes_session_slice(self) -> None:
        """Coding mode output contains the session slice text."""
        assembler = CodingContextAssembler()
        inp = _make_slice_input(coding_mode=True)
        result = assembler.assemble(inp)

        assert "session=s-123" in result.context_text

    def test_coding_mode_includes_skill_profile_slice(self) -> None:
        """Coding mode output contains the skill_profile slice text."""
        assembler = CodingContextAssembler()
        inp = _make_slice_input(coding_mode=True)
        result = assembler.assemble(inp)

        assert "Python senior" in result.context_text

    @pytest.mark.parametrize(
        "slice_field",
        ["task", "board", "workspace", "search", "session", "skill_profile"],
    )
    def test_non_coding_mode_excludes_all_slices(self, slice_field: str) -> None:
        """Non-coding mode output does NOT contain any of the 6 slice texts."""
        texts = {
            "task": "FIX_AUTH_UNIQUE",
            "board": "SPRINT42_UNIQUE",
            "workspace": "CWD_APP_UNIQUE",
            "search": "GREP_HANDLER_UNIQUE",
            "session": "SESSION_123_UNIQUE",
            "skill_profile": "PYTHON_SENIOR_UNIQUE",
        }
        inp = _make_slice_input(
            coding_mode=False,
            task_text=texts["task"],
            board_text=texts["board"],
            workspace_text=texts["workspace"],
            search_text=texts["search"],
            session_text=texts["session"],
            skill_profile_text=texts["skill_profile"],
        )
        assembler = CodingContextAssembler()
        result = assembler.assemble(inp)

        assert texts[slice_field] not in result.context_text, (
            f"Non-coding mode must exclude {slice_field} slice"
        )

    def test_coding_mode_result_has_all_6_included_slices(self) -> None:
        """Result.included_slices lists all 6 slice names in coding mode."""
        assembler = CodingContextAssembler()
        inp = _make_slice_input(coding_mode=True)
        result = assembler.assemble(inp)

        expected = {"task", "board", "workspace", "search", "session", "skill_profile"}
        assert set(result.included_slices) == expected

    def test_non_coding_mode_result_has_empty_included_slices(self) -> None:
        """Result.included_slices is empty in non-coding mode."""
        assembler = CodingContextAssembler()
        inp = _make_slice_input(coding_mode=False)
        result = assembler.assemble(inp)

        assert result.included_slices == ()


# ---------------------------------------------------------------------------
# CCTX-02: Budget discipline — deterministic truncation/omission
# ---------------------------------------------------------------------------


class TestCodingContextBudgetDiscipline:
    """Budget pressure causes deterministic, documented truncation/omission."""

    @pytest.mark.parametrize(
        ("total_tokens", "expected_omitted_count_gte"),
        [
            (8000, 0),    # generous budget: nothing omitted
            (40, 1),      # tight budget: some slices omitted
            (15, 3),      # extreme pressure: most slices omitted
        ],
        ids=["generous", "tight", "extreme"],
    )
    def test_budget_pressure_causes_deterministic_omission(
        self,
        total_tokens: int,
        expected_omitted_count_gte: int,
    ) -> None:
        """Under budget pressure, slices are omitted deterministically."""
        budget = ContextBudget(total_tokens=total_tokens)
        inp = _make_slice_input(coding_mode=True, budget=budget)
        assembler = CodingContextAssembler()
        result = assembler.assemble(inp)

        assert len(result.omitted_slices) >= expected_omitted_count_gte

    def test_omission_order_is_deterministic(self) -> None:
        """Same budget = same omission order (no randomness)."""
        budget = ContextBudget(total_tokens=100)
        inp = _make_slice_input(coding_mode=True, budget=budget)
        assembler = CodingContextAssembler()

        result_a = assembler.assemble(inp)
        result_b = assembler.assemble(inp)

        assert result_a.omitted_slices == result_b.omitted_slices
        assert result_a.included_slices == result_b.included_slices

    def test_task_slice_never_omitted_first(self) -> None:
        """Task slice has highest priority — omitted only when all others also omitted."""
        budget = ContextBudget(total_tokens=150)
        inp = _make_slice_input(coding_mode=True, budget=budget)
        assembler = CodingContextAssembler()
        result = assembler.assemble(inp)

        if "task" in result.omitted_slices:
            # If task is omitted, every other non-empty slice must also be omitted
            all_non_empty = {"task", "board", "workspace", "search", "session", "skill_profile"}
            assert all_non_empty.issubset(set(result.omitted_slices))

    def test_result_token_count_within_budget(self) -> None:
        """Result context_text token count does not exceed budget."""
        budget = ContextBudget(total_tokens=300)
        inp = _make_slice_input(coding_mode=True, budget=budget)
        assembler = CodingContextAssembler()
        result = assembler.assemble(inp)

        actual_tokens = estimate_tokens(result.context_text)
        assert actual_tokens <= budget.total_tokens

    def test_budget_overshoot_prevented_with_truncation_suffix(self) -> None:
        """Truncated context_text does not exceed budget even with suffix overhead."""
        budget = ContextBudget(total_tokens=50)
        inp = _make_slice_input(
            coding_mode=True,
            budget=budget,
            task_text="x" * 500,
        )
        assembler = CodingContextAssembler()
        result = assembler.assemble(inp)

        actual_tokens = estimate_tokens(result.context_text)
        assert actual_tokens <= budget.total_tokens, (
            f"Context ({actual_tokens} tokens) must not exceed budget ({budget.total_tokens})"
        )

    def test_truncated_slices_tracked_in_result(self) -> None:
        """Slices that are truncated (not fully omitted) appear in truncated_slices."""
        budget = ContextBudget(total_tokens=300)
        inp = _make_slice_input(
            coding_mode=True,
            budget=budget,
            workspace_text="x" * 2000,  # force truncation
        )
        assembler = CodingContextAssembler()
        result = assembler.assemble(inp)

        has_truncation = len(result.truncated_slices) > 0 or len(result.omitted_slices) > 0
        assert has_truncation, "Large slice under tight budget must cause truncation or omission"


# ---------------------------------------------------------------------------
# CodingContextResult contract
# ---------------------------------------------------------------------------


class TestCodingContextResultContract:
    """CodingContextResult is a frozen dataclass with required fields."""

    def test_result_is_frozen_dataclass(self) -> None:
        """CodingContextResult is a frozen dataclass."""
        import dataclasses

        result = CodingContextResult(
            context_text="test",
            included_slices=("task",),
            omitted_slices=(),
            truncated_slices=(),
        )
        assert dataclasses.is_dataclass(result)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.context_text = "mutate"  # type: ignore[misc]

    def test_result_fields_present(self) -> None:
        """CodingContextResult has context_text, included/omitted/truncated_slices."""
        result = CodingContextResult(
            context_text="ctx",
            included_slices=("task", "board"),
            omitted_slices=("search",),
            truncated_slices=("workspace",),
        )
        assert result.context_text == "ctx"
        assert result.included_slices == ("task", "board")
        assert result.omitted_slices == ("search",)
        assert result.truncated_slices == ("workspace",)


# ---------------------------------------------------------------------------
# CodingSliceInput contract
# ---------------------------------------------------------------------------


class TestCodingSliceInputContract:
    """CodingSliceInput is a frozen dataclass with 6 text fields + mode + budget."""

    def test_slice_input_is_frozen(self) -> None:
        """CodingSliceInput is frozen."""
        import dataclasses

        inp = _make_slice_input()
        assert dataclasses.is_dataclass(inp)
        with pytest.raises(dataclasses.FrozenInstanceError):
            inp.coding_mode = False  # type: ignore[misc]

    def test_slice_input_defaults_empty_strings(self) -> None:
        """Optional slice fields default to empty string."""
        inp = CodingSliceInput(coding_mode=True, budget=ContextBudget())
        assert inp.task == ""
        assert inp.board == ""
        assert inp.workspace == ""
        assert inp.search == ""
        assert inp.session == ""
        assert inp.skill_profile == ""


# ---------------------------------------------------------------------------
# Compaction: continuity facts preserved for resume
# ---------------------------------------------------------------------------


class TestCodingContextCompaction:
    """Compaction preserves continuity facts so agent can resume after context trim."""

    def test_continuity_facts_preserved_when_slices_omitted(self) -> None:
        """When slices are omitted, continuity_summary provides enough to resume."""
        budget = ContextBudget(total_tokens=30)
        inp = _make_slice_input(coding_mode=True, budget=budget)
        assembler = CodingContextAssembler()
        result = assembler.assemble(inp)

        assert result.continuity_summary is not None
        assert len(result.continuity_summary) > 0

    def test_continuity_summary_empty_when_nothing_omitted(self) -> None:
        """When all slices fit, continuity_summary is empty (no resume needed)."""
        budget = ContextBudget(total_tokens=8000)
        inp = _make_slice_input(coding_mode=True, budget=budget)
        assembler = CodingContextAssembler()
        result = assembler.assemble(inp)

        if not result.omitted_slices and not result.truncated_slices:
            assert result.continuity_summary == ""
