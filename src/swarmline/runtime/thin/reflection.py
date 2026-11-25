"""ReflectionState — bounded per-run verify-loop budget (Task 5).

A small mutable counter that bounds how many times edit-introduced verify
failures keep being fed back to the model within a single run. The budget is
sourced from ``CodingProfileConfig.max_reflections`` and resets on success
(REQ-SCA-041) so a fresh failure later in the run can still reflect.

This object does NOT halt the agent loop. A ``PostToolUse`` hook can only
rewrite ``tool_output``; loop termination stays with the runtime's existing
``final`` / ``max_iterations`` mechanism (NEW-ISSUE-2). The budget only governs
WHETHER verify-failure feedback keeps being appended.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReflectionState:
    """Per-run reflection budget for the in-turn verify loop.

    Attributes:
        max_reflections: Maximum consecutive verify-failure reflections before
                         feedback is suppressed. Sourced from
                         ``CodingProfileConfig.max_reflections`` (default 3).
        count: Number of failures recorded since the last success/reset.
    """

    max_reflections: int
    count: int = 0

    def should_reflect(self) -> bool:
        """True while the budget still permits another verify-failure reflection."""
        return self.count < self.max_reflections

    def record_failure(self) -> None:
        """Account for one verify-failure reflection."""
        self.count += 1

    def reset_on_success(self) -> None:
        """Reset the budget after a clean verify (REQ-SCA-041)."""
        self.count = 0
