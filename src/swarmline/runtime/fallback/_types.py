"""Error taxonomy, FallbackEntry, and FallbackChain — product-original types.

No hermes attribution: these data types originate in the taskloom product and are
ported to swarmline as generic, product-free reimplementations (REQ-OSS-051).
No product coupling — stdlib only; ``str`` tiers (no ModelTier); ``ValueError``
(no product error type).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "RemediationAction",
    "ClassifiedError",
    "FallbackEntry",
    "FallbackChain",
]


# ---------------------------------------------------------------------------
# Error taxonomy
# ---------------------------------------------------------------------------


class RemediationAction(StrEnum):
    """How the resolver should react to a classified runtime error."""

    RETRY = "retry"
    COMPRESS = "compress"  # context_overflow → compress, not failover
    FAILOVER = "failover"  # advance the cascade to the next entry
    ABORT = "abort"  # auth_permanent / format_error → stop immediately


@dataclass(slots=True, frozen=True)
class ClassifiedError:
    """Provider-agnostic error classification."""

    retryable: bool
    action: RemediationAction
    message: str


# ---------------------------------------------------------------------------
# FallbackEntry — one rung of the cascade
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class FallbackEntry:
    """One rung of the model cascade chain.

    ``tier`` is a plain ``str``; callers define the tier vocabulary.
    ``model`` and ``provider`` must not be blank.
    """

    tier: str
    model: str
    provider: str

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("FallbackEntry.model must not be blank")
        if not self.provider.strip():
            raise ValueError("FallbackEntry.provider must not be blank")


# ---------------------------------------------------------------------------
# FallbackChain — ordered, immutable cascade sequence
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class FallbackChain:
    """Immutable, ordered sequence of FallbackEntry rungs.

    Invariant: at least one entry (empty chain cannot be resolved).
    """

    entries: tuple[FallbackEntry, ...]

    def __post_init__(self) -> None:
        if not self.entries:
            raise ValueError("FallbackChain must contain at least one entry")

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):  # type: ignore[override]
        return iter(self.entries)

    def remaining_after(
        self, tried: frozenset[tuple[str, str]]
    ) -> tuple[FallbackEntry, ...]:
        """Return entries whose (provider, model) pair is NOT in *tried*.

        Comparison is case-insensitive (hermes dedup semantics).
        """
        normalised_tried = frozenset((p.lower(), m.lower()) for p, m in tried)
        return tuple(
            e
            for e in self.entries
            if (e.provider.lower(), e.model.lower()) not in normalised_tried
        )

    @classmethod
    def build_from_tier(
        cls,
        requested: str,
        *,
        tier_order: tuple[str, ...],
        tier_map: dict[str, FallbackEntry],
    ) -> FallbackChain:
        """Build the cascade chain starting at *requested* and descending.

        Walks *tier_order* from *requested* downward.  Tiers absent from
        *tier_map* are silently skipped.

        Args:
            requested: Starting tier; must be present in *tier_map*.
            tier_order: Ordered tier names, highest first.
            tier_map: Tier name → FallbackEntry mapping.

        Raises:
            ValueError: If *requested* is not in *tier_map*.
        """
        if requested not in tier_map:
            raise ValueError(
                f"Tier '{requested}' not found in tier_map "
                f"(available: {sorted(tier_map)})"
            )
        if requested in tier_order:
            start_idx = tier_order.index(requested)
            tiers_to_walk = tier_order[start_idx:]
        else:
            tiers_to_walk = (requested,)

        entries = [tier_map[t] for t in tiers_to_walk if t in tier_map]
        return cls(entries=tuple(entries))
