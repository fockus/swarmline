"""Unit tests for swarmline.runtime.iteration_budget — IterationBudget VO.

TDD Red phase: tests before implementation.
Covers: increment/remaining/is_exhausted/with_used, grace-call semantics,
immutability (each mutation returns a new instance), __post_init__ ValueError.
"""

from __future__ import annotations

import pytest

from swarmline.runtime.iteration_budget import IterationBudget


# ---------------------------------------------------------------------------
# Construction / __post_init__ validation
# ---------------------------------------------------------------------------


def test_post_init_negative_max_iterations_raises_value_error() -> None:
    with pytest.raises(ValueError, match="max_iterations must be >= 0"):
        IterationBudget(max_iterations=-1)


def test_post_init_negative_used_raises_value_error() -> None:
    with pytest.raises(ValueError, match="used must be >= 0"):
        IterationBudget(max_iterations=5, used=-1)


def test_post_init_zero_max_iterations_allowed() -> None:
    b = IterationBudget(max_iterations=0)
    assert b.max_iterations == 0


def test_post_init_default_used_is_zero() -> None:
    b = IterationBudget(max_iterations=5)
    assert b.used == 0


# ---------------------------------------------------------------------------
# remaining()
# ---------------------------------------------------------------------------


def test_remaining_initial_equals_max() -> None:
    b = IterationBudget(max_iterations=5)
    assert b.remaining() == 5


def test_remaining_decreases_with_use() -> None:
    b = IterationBudget(max_iterations=5, used=3)
    assert b.remaining() == 2


def test_remaining_clamped_to_zero_when_exhausted() -> None:
    b = IterationBudget(max_iterations=3, used=5)
    assert b.remaining() == 0


# ---------------------------------------------------------------------------
# is_exhausted()
# ---------------------------------------------------------------------------


def test_is_exhausted_false_when_used_less_than_max() -> None:
    b = IterationBudget(max_iterations=3, used=2)
    assert b.is_exhausted() is False


def test_is_exhausted_true_at_exact_cap() -> None:
    b = IterationBudget(max_iterations=3, used=3)
    assert b.is_exhausted() is True


def test_is_exhausted_true_past_cap() -> None:
    b = IterationBudget(max_iterations=3, used=4)
    assert b.is_exhausted() is True


def test_is_exhausted_zero_max_is_immediately_exhausted() -> None:
    b = IterationBudget(max_iterations=0, used=0)
    assert b.is_exhausted() is True


# ---------------------------------------------------------------------------
# increment() — immutability + grace-call
# ---------------------------------------------------------------------------


def test_increment_returns_new_instance() -> None:
    b = IterationBudget(max_iterations=5)
    b2 = b.increment()
    assert b is not b2


def test_increment_does_not_mutate_original() -> None:
    b = IterationBudget(max_iterations=5)
    _ = b.increment()
    assert b.used == 0


def test_increment_increases_used_by_one() -> None:
    b = IterationBudget(max_iterations=5)
    b2 = b.increment()
    assert b2.used == 1


def test_increment_chain() -> None:
    b = IterationBudget(max_iterations=3)
    b = b.increment().increment().increment()
    assert b.used == 3
    assert b.is_exhausted() is True


def test_increment_grace_call_past_cap_allowed() -> None:
    """Grace-call: incrementing past max_iterations is allowed (no error raised)."""
    b = IterationBudget(max_iterations=2, used=2)
    b2 = b.increment()
    assert b2.used == 3
    assert b2.is_exhausted() is True


# ---------------------------------------------------------------------------
# with_used() — immutability + validation
# ---------------------------------------------------------------------------


def test_with_used_returns_new_instance() -> None:
    b = IterationBudget(max_iterations=10)
    b2 = b.with_used(7)
    assert b is not b2


def test_with_used_sets_used_field() -> None:
    b = IterationBudget(max_iterations=10)
    b2 = b.with_used(7)
    assert b2.used == 7


def test_with_used_does_not_mutate_original() -> None:
    b = IterationBudget(max_iterations=10)
    _ = b.with_used(5)
    assert b.used == 0


def test_with_used_negative_raises_value_error() -> None:
    b = IterationBudget(max_iterations=5)
    with pytest.raises(ValueError, match="used must be >= 0"):
        b.with_used(-1)


def test_with_used_zero_allowed() -> None:
    b = IterationBudget(max_iterations=5, used=3)
    b2 = b.with_used(0)
    assert b2.used == 0


# ---------------------------------------------------------------------------
# Frozen / immutable dataclass
# ---------------------------------------------------------------------------


def test_frozen_cannot_assign_to_field() -> None:
    b = IterationBudget(max_iterations=5)
    with pytest.raises((AttributeError, TypeError)):
        b.used = 1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# __all__ export
# ---------------------------------------------------------------------------


def test_all_exports_iteration_budget() -> None:
    from swarmline.runtime.iteration_budget import __all__

    assert "IterationBudget" in __all__
