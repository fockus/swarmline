"""Contract tests for DiffReviewPort.

These tests verify the Protocol contract, not any specific implementation.
Any class implementing submit_diff + get_review + decide should pass.
"""

from __future__ import annotations

import pytest

from swarmline.hitl.timeline_types import DiffDecision, DiffReview
from swarmline.hitl.hitl_protocols import DiffReviewPort


def _make_review(
    diff_id: str = "diff-1",
    run_id: str = "run-1",
    file_path: str = "src/main.py",
    diff_content: str = "--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1 @@\n-old\n+new",
    decision: DiffDecision = DiffDecision.PENDING,
    reason: str = "",
) -> DiffReview:
    return DiffReview(
        diff_id=diff_id,
        run_id=run_id,
        file_path=file_path,
        diff_content=diff_content,
        decision=decision,
        reason=reason,
    )


class _StubDiffReview:
    """Minimal valid implementation for contract testing."""

    def __init__(self) -> None:
        self._reviews: dict[str, DiffReview] = {}

    def submit_diff(self, review: DiffReview) -> None:
        self._reviews[review.diff_id] = review

    def get_review(self, diff_id: str) -> DiffReview | None:
        return self._reviews.get(diff_id)

    def decide(self, diff_id: str, decision: DiffDecision, reason: str) -> DiffReview:
        old = self._reviews[diff_id]
        updated = DiffReview(
            diff_id=old.diff_id,
            run_id=old.run_id,
            file_path=old.file_path,
            diff_content=old.diff_content,
            decision=decision,
            reason=reason,
        )
        self._reviews[diff_id] = updated
        return updated


class _InvalidDiffReview:
    """Class without required methods — should NOT satisfy Protocol."""

    pass


class TestDiffReviewPortContract:
    """DiffReviewPort contract tests."""

    def test_protocol_is_runtime_checkable(self) -> None:
        impl = _StubDiffReview()
        assert isinstance(impl, DiffReviewPort)

    def test_invalid_impl_fails_isinstance(self) -> None:
        invalid = _InvalidDiffReview()
        assert not isinstance(invalid, DiffReviewPort)

    def test_submit_diff_returns_none(self) -> None:
        impl = _StubDiffReview()
        result = impl.submit_diff(_make_review())
        assert result is None

    def test_get_review_returns_diff_review(self) -> None:
        impl = _StubDiffReview()
        impl.submit_diff(_make_review(diff_id="d-1"))
        result = impl.get_review("d-1")
        assert isinstance(result, DiffReview)

    def test_get_review_unknown_diff_returns_none(self) -> None:
        impl = _StubDiffReview()
        assert impl.get_review("nonexistent") is None

    def test_decide_returns_diff_review_with_decision(self) -> None:
        impl = _StubDiffReview()
        impl.submit_diff(_make_review(diff_id="d-1"))
        result = impl.decide("d-1", DiffDecision.APPROVED, "Looks good")
        assert isinstance(result, DiffReview)
        assert result.decision == DiffDecision.APPROVED
        assert result.reason == "Looks good"

    def test_decide_updates_stored_review(self) -> None:
        impl = _StubDiffReview()
        impl.submit_diff(_make_review(diff_id="d-1"))
        impl.decide("d-1", DiffDecision.REJECTED, "Needs changes")
        stored = impl.get_review("d-1")
        assert stored is not None
        assert stored.decision == DiffDecision.REJECTED

    @pytest.mark.parametrize(
        "decision",
        [DiffDecision.APPROVED, DiffDecision.REJECTED, DiffDecision.CHANGES_REQUESTED],
    )
    def test_decide_accepts_all_non_pending_decisions(
        self, decision: DiffDecision
    ) -> None:
        impl = _StubDiffReview()
        impl.submit_diff(_make_review(diff_id="d-1"))
        result = impl.decide("d-1", decision, "reason")
        assert result.decision == decision

    def test_diff_review_preserves_file_path(self) -> None:
        review = _make_review(file_path="tests/test_foo.py")
        assert review.file_path == "tests/test_foo.py"

    def test_diff_review_preserves_diff_content(self) -> None:
        content = "--- a/f.py\n+++ b/f.py"
        review = _make_review(diff_content=content)
        assert review.diff_content == content
