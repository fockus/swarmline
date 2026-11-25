"""In-memory DiffReview manager — implements DiffReviewPort."""

from __future__ import annotations

from swarmline.hitl.timeline_types import DiffDecision, DiffReview


class InMemoryDiffReviewManager:
    """In-memory storage for diff reviews.

    Frozen dataclass pattern: decide() creates a new DiffReview instance
    rather than mutating the existing one.
    """

    def __init__(self) -> None:
        self._reviews: dict[str, DiffReview] = {}

    def submit_diff(self, review: DiffReview) -> None:
        """Store a diff review with its current decision (typically PENDING)."""
        self._reviews[review.diff_id] = review

    def get_review(self, diff_id: str) -> DiffReview | None:
        """Return stored review or None if not found."""
        return self._reviews.get(diff_id)

    def decide(self, diff_id: str, decision: DiffDecision, reason: str) -> DiffReview:
        """Update decision on a review — creates new frozen instance.

        Raises KeyError if diff_id not found.
        Raises ValueError if review already decided (not PENDING).
        """
        old = self._reviews[diff_id]
        if old.decision != DiffDecision.PENDING:
            msg = f"Review {diff_id} already decided: {old.decision.value}"
            raise ValueError(msg)
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
