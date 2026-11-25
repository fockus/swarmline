"""Tests for LessonsExtractor — extract lessons from sub-agent results.

TDD Red phase: tests before implementation.
Covers: extraction patterns, store, protocol, wiring.
"""

from __future__ import annotations

import pytest
from swarmline.evolution.lessons import (
    InMemoryLessonsStore,
    LessonEntry,
    LessonsExtractor,
    LessonsStore,
)

# ---------------------------------------------------------------------------
# LessonEntry — frozen dataclass
# ---------------------------------------------------------------------------


class TestLessonEntry:
    """LessonEntry value object tests."""

    def test_frozen(self) -> None:
        entry = LessonEntry(
            source_agent="agent-1",
            lesson="Use grep before read",
            category="success",
        )
        with pytest.raises(AttributeError):
            entry.lesson = "other"  # type: ignore[misc]

    def test_valid_categories(self) -> None:
        for cat in ("success", "failure", "workaround"):
            entry = LessonEntry(source_agent="a", lesson="l", category=cat)
            assert entry.category == cat


# ---------------------------------------------------------------------------
# LessonsExtractor — explicit marker extraction
# ---------------------------------------------------------------------------


class TestLessonsExtractorExplicitMarkers:
    """Extract lessons from explicit 'lesson:' / 'learning:' markers."""

    def test_extract_lesson_marker(self) -> None:
        extractor = LessonsExtractor()
        text = "I completed the task.\nlesson: Always check file exists before reading."
        lessons = extractor.extract(text, "fix the bug")
        assert len(lessons) >= 1
        assert any("check file exists" in le.lesson.lower() for le in lessons)

    def test_extract_learning_marker(self) -> None:
        extractor = LessonsExtractor()
        text = "Done.\nlearning: The API requires auth headers."
        lessons = extractor.extract(text, "call API")
        assert len(lessons) >= 1
        assert any("auth headers" in le.lesson.lower() for le in lessons)

    def test_extract_multiple_markers(self) -> None:
        extractor = LessonsExtractor()
        text = (
            "lesson: First lesson here.\n"
            "learning: Second lesson here.\n"
            "lesson: Third lesson here.\n"
        )
        lessons = extractor.extract(text, "goal")
        assert len(lessons) == 3

    def test_max_3_lessons_per_result(self) -> None:
        extractor = LessonsExtractor()
        text = "\n".join(f"lesson: Lesson number {i}." for i in range(10))
        lessons = extractor.extract(text, "goal")
        assert len(lessons) <= 3


# ---------------------------------------------------------------------------
# LessonsExtractor — pattern extraction
# ---------------------------------------------------------------------------


class TestLessonsExtractorPatterns:
    """Extract from 'failed because' / 'succeeded by' patterns."""

    def test_extract_failed_because(self) -> None:
        extractor = LessonsExtractor()
        text = "The grep approach failed because the file encoding was binary."
        lessons = extractor.extract(text, "search code")
        assert len(lessons) >= 1
        assert any(le.category == "failure" for le in lessons)

    def test_extract_succeeded_by(self) -> None:
        extractor = LessonsExtractor()
        text = "I succeeded by using a different API endpoint."
        lessons = extractor.extract(text, "call service")
        assert len(lessons) >= 1
        assert any(le.category == "success" for le in lessons)

    def test_mixed_patterns(self) -> None:
        extractor = LessonsExtractor()
        text = (
            "First I failed because of timeout.\n"
            "Then I succeeded by increasing the retry count."
        )
        lessons = extractor.extract(text, "deploy")
        assert len(lessons) >= 2
        categories = {le.category for le in lessons}
        assert "failure" in categories
        assert "success" in categories


# ---------------------------------------------------------------------------
# LessonsExtractor — no lessons
# ---------------------------------------------------------------------------


class TestLessonsExtractorNoLessons:
    """Plain text without patterns returns empty."""

    def test_plain_text_no_lessons(self) -> None:
        extractor = LessonsExtractor()
        text = "I completed the task successfully. The output is correct."
        lessons = extractor.extract(text, "do the thing")
        assert lessons == []

    def test_empty_text_no_lessons(self) -> None:
        extractor = LessonsExtractor()
        lessons = extractor.extract("", "goal")
        assert lessons == []

    def test_whitespace_only_no_lessons(self) -> None:
        extractor = LessonsExtractor()
        lessons = extractor.extract("   \n\n  ", "goal")
        assert lessons == []


# ---------------------------------------------------------------------------
# LessonsExtractor — source_agent
# ---------------------------------------------------------------------------


class TestLessonsExtractorSourceAgent:
    """Agent goal is used as source_agent in extracted entries."""

    def test_source_agent_from_goal(self) -> None:
        extractor = LessonsExtractor()
        text = "lesson: Something important."
        lessons = extractor.extract(text, "fix deployment")
        assert all(le.source_agent == "fix deployment" for le in lessons)


# ---------------------------------------------------------------------------
# LessonsStore Protocol
# ---------------------------------------------------------------------------


class TestLessonsStoreProtocol:
    """InMemoryLessonsStore satisfies LessonsStore protocol."""

    def test_implements_protocol(self) -> None:
        store = InMemoryLessonsStore()
        assert isinstance(store, LessonsStore)


# ---------------------------------------------------------------------------
# InMemoryLessonsStore
# ---------------------------------------------------------------------------


class TestInMemoryLessonsStore:
    """InMemoryLessonsStore with keyword retrieval."""

    def test_add_and_get_relevant(self) -> None:
        store = InMemoryLessonsStore()
        store.add(LessonEntry("a", "Always use grep for searching", "success"))
        store.add(LessonEntry("b", "Deploy with docker compose", "success"))

        results = store.get_relevant("searching files", limit=5)
        assert len(results) >= 1
        assert any("grep" in le.lesson.lower() for le in results)

    def test_get_relevant_empty_store(self) -> None:
        store = InMemoryLessonsStore()
        results = store.get_relevant("anything")
        assert results == []

    def test_get_relevant_respects_limit(self) -> None:
        store = InMemoryLessonsStore()
        for i in range(10):
            store.add(LessonEntry("a", f"Lesson about topic {i}", "success"))

        results = store.get_relevant("topic", limit=3)
        assert len(results) <= 3

    def test_get_relevant_keyword_matching(self) -> None:
        store = InMemoryLessonsStore()
        store.add(LessonEntry("a", "Database queries need indexes", "success"))
        store.add(LessonEntry("a", "Use pytest for testing", "success"))
        store.add(LessonEntry("a", "API endpoints need auth", "success"))

        results = store.get_relevant("database optimization")
        assert any("database" in le.lesson.lower() for le in results)

    def test_add_multiple_and_retrieve(self) -> None:
        store = InMemoryLessonsStore()
        entries = [
            LessonEntry("a", "Retry failed network calls", "workaround"),
            LessonEntry("b", "Network timeouts need longer limits", "failure"),
            LessonEntry("c", "Cache network responses locally", "success"),
        ]
        for e in entries:
            store.add(e)

        results = store.get_relevant("network", limit=5)
        assert len(results) == 3
