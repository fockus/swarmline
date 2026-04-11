"""Modes module."""

from __future__ import annotations

import re
from collections.abc import Sequence


_PLANNER_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bплан\b", re.IGNORECASE),
    re.compile(r"\bстратеги", re.IGNORECASE),
    re.compile(r"\bпошагов", re.IGNORECASE),
    re.compile(r"\bдорожн", re.IGNORECASE),
    re.compile(r"\bplan\b", re.IGNORECASE),
    re.compile(r"\bstrategy\b", re.IGNORECASE),
    re.compile(r"\bstep[- ]by[- ]step\b", re.IGNORECASE),
    re.compile(r"\broadmap\b", re.IGNORECASE),
]


_REACT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bподбер", re.IGNORECASE),
    re.compile(r"\bнайд", re.IGNORECASE),
    re.compile(r"\bсравни", re.IGNORECASE),
    re.compile(r"\bfind\b", re.IGNORECASE),
    re.compile(r"\bsearch\b", re.IGNORECASE),
    re.compile(r"\bcompare\b", re.IGNORECASE),
    re.compile(r"\blist\b", re.IGNORECASE),
    re.compile(r"\bread\b", re.IGNORECASE),
    re.compile(r"\bwrite\b", re.IGNORECASE),
    re.compile(r"\bexecute\b", re.IGNORECASE),
    re.compile(r"\brun\b", re.IGNORECASE),
]

VALID_MODES = frozenset({"conversational", "react", "planner"})


def detect_mode(
    text: str,
    mode_hint: str | None = None,
    react_patterns: Sequence[re.Pattern[str]] | None = None,
    planner_patterns: Sequence[re.Pattern[str]] | None = None,
) -> str:
    """Detect mode."""

    if mode_hint and mode_hint in VALID_MODES:
        return mode_hint


    effective_planner_patterns = planner_patterns or _PLANNER_PATTERNS
    for pattern in effective_planner_patterns:
        if pattern.search(text):
            return "planner"


    effective_react_patterns = react_patterns or _REACT_PATTERNS
    for pattern in effective_react_patterns:
        if pattern.search(text):
            return "react"

    # Default
    return "conversational"
