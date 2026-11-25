# Attribution: adapted from hermes-agent (MIT)
# Upstream file: agent/iteration_budget.py
# Copyright: (c) Nous Research and contributors
# Changes: immutable frozen+slots VO; ValueError instead of a product error;
#          no product coupling (no taskloom / AccessContext / DomainValidationError)
"""IterationBudget — immutable turn-cap value object for agent run loops.

Ported from hermes-agent (MIT).  The hermes original is a mutable thread-safe
counter; this VO is a frozen dataclass suitable for functional-style state
passing and serialisation.

Key differences from the hermes original:
- Frozen / slots dataclass — every mutation returns a new instance.
- No threading.Lock — immutability makes synchronisation the caller's concern.
- Grace-call semantics preserved: ``increment()`` past ``max_iterations`` is
  allowed so the caller can detect exhaustion after the turn rather than
  special-casing the last one.
- ``ValueError`` instead of a product-layer error type (REQ-OSS-051).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

__all__ = ["IterationBudget"]


@dataclass(slots=True, frozen=True)
class IterationBudget:
    """Immutable turn-cap budget for an agent run loop.

    ``max_iterations`` is the hard cap.  ``used`` tracks consumed iterations.
    Once ``used >= max_iterations`` the budget is exhausted.  A single
    *grace call* (``increment()`` past the cap) is allowed so that the loop
    can detect exhaustion after each turn without special-casing the last one.

    Attributes:
        max_iterations: Maximum number of iterations allowed (>= 0).
        used: Number of iterations consumed so far (>= 0).
    """

    max_iterations: int
    used: int = 0

    def __post_init__(self) -> None:
        if self.max_iterations < 0:
            raise ValueError(f"max_iterations must be >= 0, got {self.max_iterations}")
        if self.used < 0:
            raise ValueError(f"used must be >= 0, got {self.used}")

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def remaining(self) -> int:
        """Return the number of iterations left (clamped to 0)."""
        return max(0, self.max_iterations - self.used)

    def is_exhausted(self) -> bool:
        """Return True when the budget is at or past its cap."""
        return self.used >= self.max_iterations

    # ------------------------------------------------------------------
    # Mutation helpers (immutable — each returns a new instance)
    # ------------------------------------------------------------------

    def increment(self) -> IterationBudget:
        """Return a new budget with ``used`` incremented by one.

        Grace-call semantics: incrementing past ``max_iterations`` is allowed
        so the caller can check exhaustion after each turn.
        """
        return replace(self, used=self.used + 1)

    def with_used(self, n: int) -> IterationBudget:
        """Return a new budget with ``used`` set to *n* (hydration helper).

        Args:
            n: New used count (must be >= 0).

        Raises:
            ValueError: If n < 0.
        """
        if n < 0:
            raise ValueError(f"used must be >= 0, got {n}")
        return replace(self, used=n)
