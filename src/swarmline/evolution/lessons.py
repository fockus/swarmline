"""LessonsExtractor — extract and store lessons from sub-agent results.

Pure string parsing (no LLM calls). Detects:
1. Explicit markers: "lesson:" / "learning:"
2. Patterns: "failed because" / "succeeded by"

Returns max 3 lessons per result.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

_LESSON_MARKER_RE = re.compile(r"(?:lesson|learning):\s*(.+)", re.IGNORECASE)
_FAILED_BECAUSE_RE = re.compile(r"failed because\s+(.+?)(?:\.|$)", re.IGNORECASE)
_SUCCEEDED_BY_RE = re.compile(r"succeeded by\s+(.+?)(?:\.|$)", re.IGNORECASE)

MAX_LESSONS_PER_RESULT = 3


@dataclass(frozen=True, slots=True)
class LessonEntry:
    """Immutable lesson extracted from a sub-agent result."""

    source_agent: str
    lesson: str
    category: str  # "success" | "failure" | "workaround"


@runtime_checkable
class LessonsStore(Protocol):
    """Port: lesson storage and retrieval."""

    def add(self, lesson: LessonEntry) -> None: ...

    def get_relevant(self, goal: str, limit: int = 5) -> list[LessonEntry]: ...


class LessonsExtractor:
    """Extract lessons from sub-agent result text using pattern matching."""

    def extract(self, result_text: str, agent_goal: str) -> list[LessonEntry]:
        """Parse structured output for lessons. Max 3 per result."""
        if not result_text or not result_text.strip():
            return []

        lessons: list[LessonEntry] = []

        # 1. Explicit markers: "lesson:" / "learning:"
        for match in _LESSON_MARKER_RE.finditer(result_text):
            content = match.group(1).strip()
            if content:
                lessons.append(
                    LessonEntry(
                        source_agent=agent_goal,
                        lesson=content,
                        category="workaround",
                    )
                )
            if len(lessons) >= MAX_LESSONS_PER_RESULT:
                return lessons[:MAX_LESSONS_PER_RESULT]

        # 2. "failed because" patterns
        for match in _FAILED_BECAUSE_RE.finditer(result_text):
            content = match.group(1).strip()
            if content:
                lessons.append(
                    LessonEntry(
                        source_agent=agent_goal,
                        lesson=content,
                        category="failure",
                    )
                )
            if len(lessons) >= MAX_LESSONS_PER_RESULT:
                return lessons[:MAX_LESSONS_PER_RESULT]

        # 3. "succeeded by" patterns
        for match in _SUCCEEDED_BY_RE.finditer(result_text):
            content = match.group(1).strip()
            if content:
                lessons.append(
                    LessonEntry(
                        source_agent=agent_goal,
                        lesson=content,
                        category="success",
                    )
                )
            if len(lessons) >= MAX_LESSONS_PER_RESULT:
                return lessons[:MAX_LESSONS_PER_RESULT]

        return lessons[:MAX_LESSONS_PER_RESULT]


class InMemoryLessonsStore:
    """Simple in-memory store with keyword matching for retrieval."""

    def __init__(self) -> None:
        self._lessons: list[LessonEntry] = []

    def add(self, lesson: LessonEntry) -> None:
        """Add a lesson to the store."""
        self._lessons.append(lesson)

    def get_relevant(self, goal: str, limit: int = 5) -> list[LessonEntry]:
        """Retrieve lessons relevant to the goal using keyword matching."""
        if not self._lessons:
            return []

        goal_words = set(goal.lower().split())
        scored: list[tuple[int, LessonEntry]] = []

        for lesson in self._lessons:
            lesson_words = set(lesson.lesson.lower().split())
            overlap = len(goal_words & lesson_words)
            if overlap > 0:
                scored.append((overlap, lesson))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:limit]]
