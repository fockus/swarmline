"""Edge-case tests for LessonsExtractor + InMemoryLessonsStore.

Additional coverage beyond dev-domain tests.
Covers: malformed markers, case sensitivity, very long text, empty lesson content,
marker at end of line, store keyword edge cases, MAX_LESSONS_PER_RESULT constant,
LessonEntry hashability.
"""

from __future__ import annotations

from swarmline.evolution.lessons import (
    MAX_LESSONS_PER_RESULT,
    InMemoryLessonsStore,
    LessonEntry,
    LessonsExtractor,
    LessonsStore,
)

# ---------------------------------------------------------------------------
# LessonEntry edge cases
# ---------------------------------------------------------------------------


class TestLessonEntryEdge:
    """Edge cases for LessonEntry value object."""

    def test_hashable(self) -> None:
        entry = LessonEntry(source_agent="a", lesson="l", category="success")
        assert hash(entry) is not None

    def test_equality(self) -> None:
        e1 = LessonEntry(source_agent="a", lesson="l", category="success")
        e2 = LessonEntry(source_agent="a", lesson="l", category="success")
        assert e1 == e2

    def test_inequality_different_category(self) -> None:
        e1 = LessonEntry(source_agent="a", lesson="l", category="success")
        e2 = LessonEntry(source_agent="a", lesson="l", category="failure")
        assert e1 != e2

    def test_empty_fields(self) -> None:
        entry = LessonEntry(source_agent="", lesson="", category="")
        assert entry.source_agent == ""
        assert entry.lesson == ""

    def test_long_lesson_text(self) -> None:
        long_text = "x" * 10000
        entry = LessonEntry(source_agent="a", lesson=long_text, category="success")
        assert len(entry.lesson) == 10000


# ---------------------------------------------------------------------------
# LessonsExtractor — marker edge cases
# ---------------------------------------------------------------------------


class TestLessonsExtractorMarkerEdge:
    """Edge cases for explicit marker extraction."""

    def test_lesson_marker_case_insensitive(self) -> None:
        extractor = LessonsExtractor()
        text = "LESSON: Upper case lesson."
        lessons = extractor.extract(text, "goal")
        assert len(lessons) >= 1

    def test_learning_marker_case_insensitive(self) -> None:
        extractor = LessonsExtractor()
        text = "LEARNING: Upper case learning."
        lessons = extractor.extract(text, "goal")
        assert len(lessons) >= 1

    def test_lesson_marker_mixed_case(self) -> None:
        extractor = LessonsExtractor()
        text = "Lesson: Mixed case."
        lessons = extractor.extract(text, "goal")
        assert len(lessons) >= 1

    def test_marker_with_extra_spaces(self) -> None:
        extractor = LessonsExtractor()
        text = "lesson:    Extra spaces before text."
        lessons = extractor.extract(text, "goal")
        assert len(lessons) >= 1
        assert lessons[0].lesson.startswith("Extra")

    def test_marker_at_end_without_content(self) -> None:
        """Marker followed by nothing or only whitespace."""
        extractor = LessonsExtractor()
        text = "lesson:   "
        lessons = extractor.extract(text, "goal")
        assert len(lessons) == 0

    def test_marker_embedded_in_sentence(self) -> None:
        """Marker appearing mid-line."""
        extractor = LessonsExtractor()
        text = "The important lesson: always validate inputs."
        lessons = extractor.extract(text, "goal")
        assert len(lessons) >= 1

    def test_multiple_colons_in_marker(self) -> None:
        extractor = LessonsExtractor()
        text = "lesson: key: value pairs need quoting."
        lessons = extractor.extract(text, "goal")
        assert len(lessons) >= 1
        assert "key: value" in lessons[0].lesson

    def test_marker_without_colon_not_matched(self) -> None:
        """Word 'lesson' without colon should not trigger extraction."""
        extractor = LessonsExtractor()
        text = "This is a lesson I learned the hard way."
        lessons = extractor.extract(text, "goal")
        # No marker pattern → may find nothing from marker regex
        # (could still match other patterns)
        marker_lessons = [le for le in lessons if le.category == "workaround"]
        assert len(marker_lessons) == 0


# ---------------------------------------------------------------------------
# LessonsExtractor — pattern edge cases
# ---------------------------------------------------------------------------


class TestLessonsExtractorPatternEdge:
    """Edge cases for 'failed because' / 'succeeded by' patterns."""

    def test_failed_because_case_insensitive(self) -> None:
        extractor = LessonsExtractor()
        text = "It FAILED BECAUSE the server was down."
        lessons = extractor.extract(text, "goal")
        assert len(lessons) >= 1
        assert any(le.category == "failure" for le in lessons)

    def test_succeeded_by_case_insensitive(self) -> None:
        extractor = LessonsExtractor()
        text = "We SUCCEEDED BY retrying the request."
        lessons = extractor.extract(text, "goal")
        assert len(lessons) >= 1
        assert any(le.category == "success" for le in lessons)

    def test_failed_because_at_end_of_text(self) -> None:
        extractor = LessonsExtractor()
        text = "The task failed because of permissions"
        lessons = extractor.extract(text, "goal")
        assert len(lessons) >= 1

    def test_multiple_failed_because_in_same_text(self) -> None:
        extractor = LessonsExtractor()
        text = "First failed because of timeout. Then failed because of auth."
        lessons = extractor.extract(text, "goal")
        assert len(lessons) >= 2
        assert all(le.category == "failure" for le in lessons)

    def test_very_long_text(self) -> None:
        """Very long text should still be parseable."""
        extractor = LessonsExtractor()
        padding = "Regular text without patterns. " * 500
        text = f"{padding}\nlesson: Hidden deep in text."
        lessons = extractor.extract(text, "goal")
        assert len(lessons) >= 1

    def test_text_with_only_newlines(self) -> None:
        extractor = LessonsExtractor()
        lessons = extractor.extract("\n\n\n\n", "goal")
        assert lessons == []


# ---------------------------------------------------------------------------
# LessonsExtractor — MAX_LESSONS_PER_RESULT
# ---------------------------------------------------------------------------


class TestLessonsExtractorMaxLessons:
    """MAX_LESSONS_PER_RESULT constant and enforcement."""

    def test_constant_is_3(self) -> None:
        assert MAX_LESSONS_PER_RESULT == 3

    def test_mixed_patterns_capped_at_3(self) -> None:
        extractor = LessonsExtractor()
        text = (
            "lesson: First.\n"
            "lesson: Second.\n"
            "failed because of timeout.\n"
            "succeeded by retrying.\n"
            "learning: Fifth.\n"
        )
        lessons = extractor.extract(text, "goal")
        assert len(lessons) <= 3

    def test_exactly_3_lessons(self) -> None:
        extractor = LessonsExtractor()
        text = "lesson: A.\nlesson: B.\nlesson: C."
        lessons = extractor.extract(text, "goal")
        assert len(lessons) == 3


# ---------------------------------------------------------------------------
# LessonsExtractor — category assignment
# ---------------------------------------------------------------------------


class TestLessonsExtractorCategories:
    """Verify correct category assignment per pattern type."""

    def test_lesson_marker_is_workaround(self) -> None:
        extractor = LessonsExtractor()
        text = "lesson: Use caching for speed."
        lessons = extractor.extract(text, "goal")
        assert lessons[0].category == "workaround"

    def test_learning_marker_is_workaround(self) -> None:
        extractor = LessonsExtractor()
        text = "learning: Enable debug mode for more info."
        lessons = extractor.extract(text, "goal")
        assert lessons[0].category == "workaround"

    def test_failed_because_is_failure(self) -> None:
        extractor = LessonsExtractor()
        text = "It failed because of missing dependency."
        lessons = extractor.extract(text, "goal")
        assert lessons[0].category == "failure"

    def test_succeeded_by_is_success(self) -> None:
        extractor = LessonsExtractor()
        text = "I succeeded by using a workaround."
        lessons = extractor.extract(text, "goal")
        assert lessons[0].category == "success"


# ---------------------------------------------------------------------------
# InMemoryLessonsStore edge cases
# ---------------------------------------------------------------------------


class TestInMemoryLessonsStoreEdge:
    """Edge cases for InMemoryLessonsStore."""

    def test_no_keyword_overlap_returns_empty(self) -> None:
        store = InMemoryLessonsStore()
        store.add(LessonEntry("a", "database optimization", "success"))
        results = store.get_relevant("completely unrelated query")
        assert results == []

    def test_single_word_overlap(self) -> None:
        store = InMemoryLessonsStore()
        store.add(LessonEntry("a", "Use retry logic for network calls", "workaround"))
        results = store.get_relevant("network")
        assert len(results) == 1

    def test_goal_with_special_chars(self) -> None:
        store = InMemoryLessonsStore()
        store.add(LessonEntry("a", "Check file permissions", "failure"))
        results = store.get_relevant("file! permissions?")
        # Special chars are part of words, may not match exactly
        # But "file!" split → {"file!"}, "file" in lesson → {"file"}
        # No overlap due to punctuation
        assert isinstance(results, list)

    def test_duplicate_lessons_stored(self) -> None:
        store = InMemoryLessonsStore()
        entry = LessonEntry("a", "Same lesson twice", "success")
        store.add(entry)
        store.add(entry)
        results = store.get_relevant("same lesson", limit=10)
        assert len(results) == 2  # Both stored, no dedup

    def test_limit_zero(self) -> None:
        store = InMemoryLessonsStore()
        store.add(LessonEntry("a", "Some lesson", "success"))
        results = store.get_relevant("some", limit=0)
        assert results == []

    def test_limit_one(self) -> None:
        store = InMemoryLessonsStore()
        store.add(LessonEntry("a", "Lesson about testing", "success"))
        store.add(LessonEntry("b", "Lesson about testing too", "failure"))
        results = store.get_relevant("testing", limit=1)
        assert len(results) == 1

    def test_ranking_by_overlap(self) -> None:
        """Lessons with more keyword overlap should rank higher."""
        store = InMemoryLessonsStore()
        store.add(LessonEntry("a", "database", "success"))
        store.add(LessonEntry("b", "database query optimization", "success"))
        results = store.get_relevant("database query optimization", limit=2)
        assert len(results) == 2
        # The one with more overlap should come first
        assert (
            "query" in results[0].lesson.lower()
            or "optimization" in results[0].lesson.lower()
        )

    def test_empty_goal_returns_empty(self) -> None:
        store = InMemoryLessonsStore()
        store.add(LessonEntry("a", "Some lesson", "success"))
        results = store.get_relevant("")
        assert results == []

    def test_protocol_conformance(self) -> None:
        """InMemoryLessonsStore implements LessonsStore."""
        store = InMemoryLessonsStore()
        assert isinstance(store, LessonsStore)
        assert hasattr(store, "add")
        assert hasattr(store, "get_relevant")
