"""CodingContextAssembler — build coding-mode context from 6 slices.

Assembles task/board/workspace/search/session/skill_profile slices
when coding_mode is active. Budget-aware: deterministic truncation
and omission under token pressure.

CCTX-01: coding mode includes 6 slices; non-coding mode excludes them.
CCTX-02: budget discipline with documented priority order.
"""

from __future__ import annotations

from dataclasses import dataclass

from swarmline.context.budget import ContextBudget, estimate_tokens, truncate_to_budget

# Slice priority order (highest first). Under budget pressure,
# slices are omitted from the END of this list first.
_SLICE_PRIORITY: tuple[str, ...] = (
    "task",           # P0 — always kept if possible
    "workspace",      # P1 — essential for tool execution context
    "board",          # P2 — sprint/task board state
    "session",        # P3 — session continuity
    "skill_profile",  # P4 — coding style preferences
    "search",         # P5 — recent search results (most ephemeral)
)

# Minimum tokens of actual content to justify including a truncated slice.
# Below this threshold, the slice is omitted entirely.
_MIN_CONTENT_TOKENS: int = 10

# Overhead tokens reserved for truncation suffix added by truncate_to_budget.
_TRUNCATION_SUFFIX_TOKENS: int = 5

_SLICE_HEADERS: dict[str, str] = {
    "task": "## Current Task",
    "board": "## Task Board",
    "workspace": "## Workspace",
    "search": "## Recent Search",
    "session": "## Session",
    "skill_profile": "## Skill Profile",
}


@dataclass(frozen=True)
class CodingSliceInput:
    """Input data for coding context assembly.

    All 6 text fields default to empty string (slice is skipped when empty).
    """

    coding_mode: bool
    budget: ContextBudget
    task: str = ""
    board: str = ""
    workspace: str = ""
    search: str = ""
    session: str = ""
    skill_profile: str = ""


@dataclass(frozen=True)
class CodingContextResult:
    """Result of coding context assembly.

    context_text: assembled text to inject into system prompt.
    included_slices: names of slices that made it into context_text.
    omitted_slices: names of slices dropped entirely due to budget.
    truncated_slices: names of slices that were truncated (partially included).
    continuity_summary: brief summary for agent resume when slices are omitted.
    """

    context_text: str
    included_slices: tuple[str, ...]
    omitted_slices: tuple[str, ...]
    truncated_slices: tuple[str, ...]
    continuity_summary: str = ""


class CodingContextAssembler:
    """Assemble coding-mode context from 6 slices with budget awareness.

    Public API (ISP: 2 methods):
        assemble(inp) -> CodingContextResult
    """

    def assemble(self, inp: CodingSliceInput) -> CodingContextResult:
        """Assemble coding context from slice input.

        In non-coding mode, returns empty context with no slices.
        In coding mode, includes slices in priority order, respecting budget.
        """
        if not inp.coding_mode:
            return CodingContextResult(
                context_text="",
                included_slices=(),
                omitted_slices=(),
                truncated_slices=(),
                continuity_summary="",
            )

        return self._assemble_coding(inp)

    def _assemble_coding(self, inp: CodingSliceInput) -> CodingContextResult:
        """Internal: assemble slices in priority order with budget control."""
        remaining = inp.budget.total_tokens
        included: list[str] = []
        omitted: list[str] = []
        truncated: list[str] = []
        parts: list[str] = []

        slice_texts = {
            "task": inp.task,
            "board": inp.board,
            "workspace": inp.workspace,
            "search": inp.search,
            "session": inp.session,
            "skill_profile": inp.skill_profile,
        }

        for name in _SLICE_PRIORITY:
            text = slice_texts[name]
            if not text:
                continue

            header = _SLICE_HEADERS[name]
            pack = f"{header}\n{text}"
            tokens = estimate_tokens(pack)

            if remaining <= 0:
                omitted.append(name)
                continue

            if tokens > remaining:
                if remaining > estimate_tokens(header) + _MIN_CONTENT_TOKENS:
                    pack = truncate_to_budget(
                        pack, remaining - _TRUNCATION_SUFFIX_TOKENS,
                    )
                    truncated.append(name)
                    included.append(name)
                    parts.append(pack)
                    remaining -= estimate_tokens(pack)
                else:
                    omitted.append(name)
                continue

            included.append(name)
            parts.append(pack)
            remaining -= tokens

        context_text = "\n\n".join(parts) if parts else ""

        continuity_summary = ""
        if omitted or truncated:
            summary_parts = []
            if omitted:
                summary_parts.append(f"Omitted slices: {', '.join(omitted)}")
            if truncated:
                summary_parts.append(f"Truncated slices: {', '.join(truncated)}")
            continuity_summary = "; ".join(summary_parts)

        return CodingContextResult(
            context_text=context_text,
            included_slices=tuple(included),
            omitted_slices=tuple(omitted),
            truncated_slices=tuple(truncated),
            continuity_summary=continuity_summary,
        )
