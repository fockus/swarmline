"""Tolerant edit-format engine (Task 1, swarmline-code-agent-uplift).

Public surface:
- Value objects: ``Hunk``, ``HunkResult``, ``EditOutcome``.
- Enums (Literal aliases): ``HunkStatus``, ``EditFailureKind``.
- Protocols: ``FuzzyMatcher``, ``EditStrategy``, ``PathLock``.
- Concrete strategies: ``SearchReplaceStrategy`` (tolerant single-file cascade),
  ``V4APatchStrategy`` (transactional multi-file all-or-nothing), and
  ``AnchorEditStrategy`` (hash-anchored transactional, opt-in via REQ-RCA-070).
- ``AsyncPathLock``: per-realpath async lock registry for safe concurrent multi-file writes.
- ``AnchoredHunk``: Hunk subtype carrying a sha256 anchor for the target slice.
"""

from __future__ import annotations

from swarmline.tools.edit.anchor import AnchoredHunk, AnchorEditStrategy
from swarmline.tools.edit.strategy import (
    AsyncPathLock,
    CascadeFuzzyMatcher,
    EditFailureKind,
    EditOutcome,
    EditStrategy,
    FuzzyMatcher,
    Hunk,
    HunkResult,
    HunkStatus,
    PathLock,
    SearchReplaceStrategy,
    V4APatchStrategy,
)

__all__ = [
    "AnchoredHunk",
    "AnchorEditStrategy",
    "AsyncPathLock",
    "CascadeFuzzyMatcher",
    "EditFailureKind",
    "EditOutcome",
    "EditStrategy",
    "FuzzyMatcher",
    "Hunk",
    "HunkResult",
    "HunkStatus",
    "PathLock",
    "SearchReplaceStrategy",
    "V4APatchStrategy",
]
