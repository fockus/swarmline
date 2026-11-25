"""Task complexity classification — swarmline-native primitive.

Classifies prompts into SIMPLE / MEDIUM / COMPLEX based on word count,
presence of complexity keywords, and available tool count.

REQ-OSS-060: domain-neutral (stdlib only: re, dataclasses, enum).
Zero product coupling — no tenant/workspace/FastAPI/SQLAlchemy references.

This is a parallel copy of the taskloom domain primitive kept in sync
by convention; the taskloom domain layer MUST NOT import from swarmline
(Clean Architecture: domain has zero framework dependencies).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class TaskComplexity(StrEnum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"


@dataclass(frozen=True, slots=True)
class ComplexityBudget:
    max_turns: int
    planning_required: bool
    scratchpad_recommended: bool


_COMPLEXITY_KEYWORDS: frozenset[str] = frozenset(
    {
        "plan",
        "analyze",
        "research",
        "compare",
        "multi-step",
        "report",
        "investigate",
    }
)

_BUDGETS: dict[TaskComplexity, ComplexityBudget] = {
    TaskComplexity.SIMPLE: ComplexityBudget(
        max_turns=3, planning_required=False, scratchpad_recommended=False
    ),
    TaskComplexity.MEDIUM: ComplexityBudget(
        max_turns=7, planning_required=False, scratchpad_recommended=True
    ),
    TaskComplexity.COMPLEX: ComplexityBudget(
        max_turns=15, planning_required=True, scratchpad_recommended=True
    ),
}

_KEYWORD_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(kw) for kw in _COMPLEXITY_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


class TaskComplexityClassifier:
    """Heuristic classifier for task complexity."""

    def classify(self, prompt: str, tool_count: int = 0) -> TaskComplexity:
        word_count = len(prompt.split())
        has_keywords = bool(_KEYWORD_PATTERN.search(prompt))

        is_complex_prompt = word_count > 200 or has_keywords
        if is_complex_prompt and tool_count > 5:
            return TaskComplexity.COMPLEX

        is_simple_prompt = word_count < 50 and not has_keywords and tool_count <= 3
        if is_simple_prompt:
            return TaskComplexity.SIMPLE

        return TaskComplexity.MEDIUM

    def get_budget(self, complexity: TaskComplexity) -> ComplexityBudget:
        return _BUDGETS[complexity]
