"""Tests for ReflectionState — bounded per-run verify-loop budget (Task 5).

REQ-SCA-040: cap reflections at ``max_reflections`` per run.
REQ-SCA-041: a clean (success) verify resets the budget so a later failure
reflects again.
"""

from __future__ import annotations

import pytest
from swarmline.runtime.thin.reflection import ReflectionState


class TestReflectionState:
    def test_should_reflect_true_below_cap(self) -> None:
        """Below the cap → reflection allowed."""
        state = ReflectionState(max_reflections=3)
        assert state.should_reflect() is True
        state.record_failure()
        assert state.should_reflect() is True  # 1 < 3
        state.record_failure()
        assert state.should_reflect() is True  # 2 < 3

    def test_should_reflect_false_at_and_after_cap(self) -> None:
        """At the cap (and past it) → reflection exhausted."""
        state = ReflectionState(max_reflections=2)
        state.record_failure()
        state.record_failure()
        assert state.should_reflect() is False  # 2 == 2, not < 2
        state.record_failure()
        assert state.should_reflect() is False  # 3 > 2

    def test_record_failure_increments_count(self) -> None:
        """Each failure bumps the counter by exactly one."""
        state = ReflectionState(max_reflections=5)
        assert state.count == 0
        state.record_failure()
        assert state.count == 1
        state.record_failure()
        assert state.count == 2

    def test_reset_on_success_zeroes_counter(self) -> None:
        """A success zeroes the budget so it can reflect from scratch again."""
        state = ReflectionState(max_reflections=3)
        state.record_failure()
        state.record_failure()
        assert state.count == 2
        state.reset_on_success()
        assert state.count == 0
        assert state.should_reflect() is True

    @pytest.mark.parametrize("cap", [0, 1, 3])
    def test_default_count_starts_at_zero(self, cap: int) -> None:
        """A freshly built state starts at count 0 regardless of cap."""
        state = ReflectionState(max_reflections=cap)
        assert state.count == 0
