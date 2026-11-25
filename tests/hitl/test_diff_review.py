"""Tests for InMemoryDiffReviewManager.

TDD: these tests were written BEFORE the implementation.
"""

from __future__ import annotations

import pytest
from swarmline.hitl.hitl_protocols import DiffReviewPort
from swarmline.hitl.timeline_types import DiffDecision, DiffReview


def _make_review(
    diff_id: str = "diff-1",
    run_id: str = "run-1",
    file_path: str = "src/main.py",
    diff_content: str = "--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1 @@\n-old\n+new",
) -> DiffReview:
    return DiffReview(
        diff_id=diff_id,
        run_id=run_id,
        file_path=file_path,
        diff_content=diff_content,
    )


@pytest.fixture()
def manager() -> DiffReviewPort:
    from swarmline.hitl.diff_review import InMemoryDiffReviewManager

    return InMemoryDiffReviewManager()


class TestInMemoryDiffReviewManager:
    """InMemoryDiffReviewManager implementation tests."""

    def test_satisfies_protocol(self, manager: DiffReviewPort) -> None:
        assert isinstance(manager, DiffReviewPort)

    def test_submit_diff_stores_review(self, manager: DiffReviewPort) -> None:
        review = _make_review(diff_id="d-1")
        manager.submit_diff(review)
        stored = manager.get_review("d-1")
        assert stored is not None
        assert stored.diff_id == "d-1"
        assert stored.decision == DiffDecision.PENDING

    def test_get_review_nonexistent_returns_none(self, manager: DiffReviewPort) -> None:
        assert manager.get_review("nonexistent") is None

    def test_decide_approve_returns_updated_review(
        self, manager: DiffReviewPort
    ) -> None:
        manager.submit_diff(_make_review(diff_id="d-1"))
        result = manager.decide("d-1", DiffDecision.APPROVED, "LGTM")
        assert result.decision == DiffDecision.APPROVED
        assert result.reason == "LGTM"
        assert result.diff_id == "d-1"

    def test_decide_reject_returns_updated_review(
        self, manager: DiffReviewPort
    ) -> None:
        manager.submit_diff(_make_review(diff_id="d-1"))
        result = manager.decide("d-1", DiffDecision.REJECTED, "Security issue")
        assert result.decision == DiffDecision.REJECTED
        assert result.reason == "Security issue"

    def test_decide_changes_requested(self, manager: DiffReviewPort) -> None:
        manager.submit_diff(_make_review(diff_id="d-1"))
        result = manager.decide("d-1", DiffDecision.CHANGES_REQUESTED, "Add tests")
        assert result.decision == DiffDecision.CHANGES_REQUESTED
        assert result.reason == "Add tests"

    def test_decide_updates_stored_review(self, manager: DiffReviewPort) -> None:
        manager.submit_diff(_make_review(diff_id="d-1"))
        manager.decide("d-1", DiffDecision.APPROVED, "OK")
        stored = manager.get_review("d-1")
        assert stored is not None
        assert stored.decision == DiffDecision.APPROVED

    def test_decide_creates_new_frozen_instance(self, manager: DiffReviewPort) -> None:
        original = _make_review(diff_id="d-1")
        manager.submit_diff(original)
        result = manager.decide("d-1", DiffDecision.APPROVED, "OK")
        assert result is not original
        assert original.decision == DiffDecision.PENDING

    def test_decide_nonexistent_raises_key_error(self, manager: DiffReviewPort) -> None:
        with pytest.raises(KeyError):
            manager.decide("nonexistent", DiffDecision.APPROVED, "OK")

    def test_submit_multiple_reviews(self, manager: DiffReviewPort) -> None:
        manager.submit_diff(_make_review(diff_id="d-1"))
        manager.submit_diff(_make_review(diff_id="d-2"))
        assert manager.get_review("d-1") is not None
        assert manager.get_review("d-2") is not None

    @pytest.mark.parametrize(
        "decision",
        [DiffDecision.APPROVED, DiffDecision.REJECTED, DiffDecision.CHANGES_REQUESTED],
    )
    def test_decide_all_non_pending_decisions(
        self, manager: DiffReviewPort, decision: DiffDecision
    ) -> None:
        manager.submit_diff(_make_review(diff_id="d-1"))
        result = manager.decide("d-1", decision, "reason")
        assert result.decision == decision

    def test_preserves_file_path_and_content(self, manager: DiffReviewPort) -> None:
        review = _make_review(
            diff_id="d-1",
            file_path="tests/test_x.py",
            diff_content="--- a\n+++ b\n@@ -1 +1 @@\n-a\n+b",
        )
        manager.submit_diff(review)
        stored = manager.get_review("d-1")
        assert stored is not None
        assert stored.file_path == "tests/test_x.py"
        assert stored.diff_content == review.diff_content
