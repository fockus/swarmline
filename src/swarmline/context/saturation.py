"""SaturationCalculator — pure ratio of actual usage to allocated budget per category.

Part of the ``adaptive-budget`` spec (REQ-004: pure application-layer function, zero IO;
REQ-007: saturation = actual / allocated). Feeds back into
``AdaptiveContextBudget.allocate`` on the following turn (two-pass feedback loop).
"""

from __future__ import annotations


class SaturationCalculator:
    """Computes per-category saturation ratios."""

    @staticmethod
    def calculate(
        actual: dict[str, int], allocated: dict[str, int]
    ) -> dict[str, float]:
        """Return ``{category: actual/allocated}`` for every category in ``allocated``.

        ``allocated`` is the source of truth for which categories exist. A category
        missing from ``actual`` saturates at 0. Division by zero is impossible because
        the denominator is floored via ``max(allocated[cat], 1)``.
        """
        return {
            category: actual.get(category, 0) / max(allocated_tokens, 1)
            for category, allocated_tokens in allocated.items()
        }
