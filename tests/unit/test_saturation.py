"""Tests for SaturationCalculator — pure saturation ratio (actual/allocated) per category.

Part of the ``adaptive-budget`` spec (REQ-004: pure, no IO; REQ-007: saturation =
actual/allocated). ``allocated`` is the source of truth for which categories exist;
division by zero is impossible because the denominator is floored via ``max(allocated, 1)``.
"""

from __future__ import annotations

import pytest

from swarmline.context.saturation import SaturationCalculator


def test_saturation_ratio_actual_over_allocated() -> None:
    """Saturation is the simple ratio of actual usage to allocated budget."""
    actual = {"content": 500}
    allocated = {"content": 1000}

    result = SaturationCalculator.calculate(actual, allocated)

    assert result == {"content": 0.5}


def test_saturation_handles_zero_allocated_without_div_error() -> None:
    """Zero allocation floors to 1 via max(allocated, 1) — no ZeroDivisionError."""
    actual = {"x": 100}
    allocated = {"x": 0}

    result = SaturationCalculator.calculate(actual, allocated)

    assert result == {"x": 100.0}


def test_saturation_missing_actual_category_defaults_to_zero() -> None:
    """A category present in ``allocated`` but absent from ``actual`` saturates at 0."""
    actual: dict[str, int] = {}
    allocated = {"memory": 1500}

    result = SaturationCalculator.calculate(actual, allocated)

    assert result == {"memory": 0.0}


def test_saturation_keys_follow_allocated_not_actual() -> None:
    """Categories only present in ``actual`` (not in ``allocated``) are ignored."""
    actual = {"content": 500, "extra": 999}
    allocated = {"content": 1000}

    result = SaturationCalculator.calculate(actual, allocated)

    assert result == {"content": 0.5}
    assert "extra" not in result


@pytest.mark.parametrize(
    "actual, allocated, expected",
    [
        (
            {"system": 100, "tools": 400, "content": 900},
            {"system": 200, "tools": 500, "content": 1000},
            {"system": 0.5, "tools": 0.8, "content": 0.9},
        ),
        (
            {"events": 0, "memory": 750},
            {"events": 300, "memory": 1500},
            {"events": 0.0, "memory": 0.5},
        ),
        (
            {"task": 2000},
            {"task": 1000},
            {"task": 2.0},
        ),
    ],
)
def test_saturation_multiple_categories(
    actual: dict[str, int], allocated: dict[str, int], expected: dict[str, float]
) -> None:
    """Saturation is computed independently per category across the whole dict."""
    result = SaturationCalculator.calculate(actual, allocated)

    assert result == expected
