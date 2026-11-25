"""AdaptiveContextBudget — dynamic, mode-aware allocation of a context-token budget.

Part of the ``adaptive-budget`` spec (REQ-001, REQ-002, REQ-003, REQ-005, REQ-006,
REQ-008). Ported from aura's ``resilience/adaptive_budget.py``. Pure application-layer
logic, zero IO (REQ-004): allocation is steering, not cutting — the actual content
truncation still happens in the existing drop-order ``DefaultContextBuilder``.

Pipeline (design.md), run in this order on every ``allocate`` call:

1. base       -- start from ``ratios.per_mode[mode]`` (fallback: the "default"
                 entry, else the first configured mode).
2. temporal   -- early progress (``step_progress <= 0.3``) shifts budget toward
                 ``content``; late progress (``>= 0.6``) shifts budget toward
                 ``events`` + ``memory``. Between the two thresholds: no shift.
3. rebalance  -- when ``last_saturation`` is available (REQ-008), categories
                 under 0.5 saturation give up a share to categories over 0.8
                 saturation.
4-5. bounds + normalize -- clamp every category into ``[floor, ceil]`` *and*
                 rescale so shares sum to 1.0, in a single water-filling pass
                 (see note below) so both constraints hold on the FINAL
                 ratios, not just on an intermediate step.
6. tokens     -- multiply by ``total_budget`` and round to integers so the
                 returned dict sums to EXACTLY ``total_budget`` (REQ-003),
                 crediting/debiting the rounding remainder ONE TOKEN AT A TIME
                 across the categories with headroom under/above their bound
                 (never dumping the whole remainder into a single category,
                 which could breach REQ-002 when no one category has enough
                 headroom to absorb it alone).

Note on steps 4-5 (deliberate deviation from a literal "clamp, then divide by
sum" reading): dividing by the post-clamp sum can rescale a tightly-ceiled
category right back OUT of bounds when the scale factor is > 1 (i.e. when other
clamped categories left less than 1.0 of share on the table). REQ-002 requires
bounds to hold on the allocation actually returned, so steps 4 and 5 are
implemented together as iterative water-filling: categories that would breach a
bound are pinned at that bound, and the remaining budget is re-divided only
among the still-free categories, repeating until stable. Assumes
``floor``/``ceil`` are jointly feasible (``sum(floor) <= 1 <= sum(ceil)``);
best-effort otherwise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

#: The 6 fixed layer categories every ``BudgetRatios.per_mode`` entry must cover.
CATEGORIES: tuple[str, ...] = ("system", "tools", "task", "memory", "content", "events")

_EARLY_PROGRESS_THRESHOLD = 0.3
_LATE_PROGRESS_THRESHOLD = 0.6
_TEMPORAL_SHIFT_DELTA = 0.1
_SATURATION_UNDERFILLED = 0.5
_SATURATION_OVERFILLED = 0.8
_REBALANCE_TAKE_FRACTION = 0.3


@dataclass(frozen=True)
class BudgetRatios:
    """Per-mode base ratios plus per-category floor/ceil bounds.

    ``per_mode[mode]`` must sum to 1.0 across the 6 categories in ``CATEGORIES``.
    ``floor``/``ceil`` bound the final share of each category; a category absent
    from ``floor``/``ceil`` defaults to 0.0/1.0 (unbounded).
    """

    per_mode: dict[str, dict[str, float]]
    floor: dict[str, float] = field(default_factory=dict)
    ceil: dict[str, float] = field(default_factory=dict)


class AdaptiveContextBudget:
    """Allocates a total token budget across the 6 fixed categories.

    Pure application-layer object: holds only immutable config
    (``BudgetRatios``) and a total; ``allocate`` performs no IO.
    """

    def __init__(self, ratios: BudgetRatios, total_budget: int) -> None:
        self._ratios = ratios
        self._total_budget = total_budget

    def allocate(
        self,
        mode: str,
        step_progress: float,
        last_saturation: dict[str, float] | None = None,
    ) -> dict[str, int]:
        """Return ``{category: tokens}`` summing to exactly ``total_budget``."""
        shares = self._base_shares(mode)
        shares = _apply_temporal_shift(shares, step_progress)
        if last_saturation is not None:
            shares = _apply_saturation_rebalance(shares, last_saturation)
        shares = _enforce_bounds_and_normalize(
            shares, self._ratios.floor, self._ratios.ceil
        )
        return _to_exact_tokens(
            shares, self._total_budget, self._ratios.floor, self._ratios.ceil
        )

    def _base_shares(self, mode: str) -> dict[str, float]:
        per_mode = self._ratios.per_mode
        if mode in per_mode:
            return dict(per_mode[mode])
        if "default" in per_mode:
            return dict(per_mode["default"])
        # No exact match and no "default" entry: fall back to the first
        # configured mode (dict insertion order) rather than raising.
        return dict(next(iter(per_mode.values())))


def _apply_temporal_shift(
    shares: dict[str, float], step_progress: float
) -> dict[str, float]:
    """REQ-005/REQ-006: shift a modest, fixed share toward content (early) or
    events+memory (late). No shift in the neutral 0.3-0.6 zone."""
    if step_progress <= _EARLY_PROGRESS_THRESHOLD:
        return _shift_toward(shares, ("content",), _TEMPORAL_SHIFT_DELTA)
    if step_progress >= _LATE_PROGRESS_THRESHOLD:
        return _shift_toward(shares, ("events", "memory"), _TEMPORAL_SHIFT_DELTA)
    return dict(shares)


def _shift_toward(
    shares: dict[str, float], targets: tuple[str, ...], delta: float
) -> dict[str, float]:
    """Move ``delta`` of total share from non-target categories to ``targets``.

    Donors give up a share proportional to their own current size (so none can
    go negative); the moved total is split evenly across ``targets``. The sum
    of all shares is preserved exactly.
    """
    result = dict(shares)
    donors = [category for category in shares if category not in targets]
    donor_total = sum(shares[category] for category in donors)
    if donor_total <= 0 or not donors:
        return result
    per_target = delta / len(targets)
    for donor in donors:
        result[donor] = shares[donor] - shares[donor] * (delta / donor_total)
    for target in targets:
        result[target] = shares.get(target, 0.0) + per_target
    return result


def _apply_saturation_rebalance(
    shares: dict[str, float], last_saturation: dict[str, float]
) -> dict[str, float]:
    """REQ-008: move budget from under-filled (<0.5) to over-filled (>0.8)
    categories. No-op unless at least one category qualifies on each side."""
    underfilled = [
        category
        for category in shares
        if category in last_saturation
        and last_saturation[category] < _SATURATION_UNDERFILLED
    ]
    overfilled = [
        category
        for category in shares
        if category in last_saturation
        and last_saturation[category] > _SATURATION_OVERFILLED
    ]
    if not underfilled or not overfilled:
        return dict(shares)
    result = dict(shares)
    pool = 0.0
    for donor in underfilled:
        taken = shares[donor] * _REBALANCE_TAKE_FRACTION
        result[donor] = shares[donor] - taken
        pool += taken
    per_receiver = pool / len(overfilled)
    for receiver in overfilled:
        result[receiver] = result.get(receiver, shares[receiver]) + per_receiver
    return result


def _clamp_candidate(candidate: float, lo: float, hi: float) -> tuple[float, bool]:
    """Clamp ``candidate`` into ``[lo, hi]``. Returns ``(value, was_pinned)``."""
    if candidate < lo:
        return lo, True
    if candidate > hi:
        return hi, True
    return candidate, False


def _enforce_bounds_and_normalize(
    shares: dict[str, float], floor: dict[str, float], ceil: dict[str, float]
) -> dict[str, float]:
    """Clamp every category to ``[floor, ceil]`` while keeping the sum at 1.0.

    Iterative water-filling: categories whose rescaled share would breach a
    bound are pinned at that bound; the remaining ``1.0 - pinned`` budget is
    re-divided only among the still-free categories, repeated until stable.

    When the still-free categories' CURRENT combined value is ``<= 0`` (e.g.
    their incoming share was exactly 0, so scaling a 0 value can never top it
    up), an equal split of the remaining budget is used instead of a scale
    factor to avoid a division by zero. That equal split is clamped into
    ``[floor, ceil]`` exactly like the scaled path below, and pinning from it
    keeps the water-filling loop going (rather than returning an out-of-bounds
    value outright) -- this is what Defect 2 fixed: the old code assigned the
    unclamped equal share and unconditionally ``break``-ed.
    """
    values = dict(shares)
    pinned: set[str] = set()
    for _ in range(len(values)):
        free = [category for category in values if category not in pinned]
        if not free:
            break
        pinned_total = sum(values[category] for category in pinned)
        free_total = sum(values[category] for category in free)
        target_total = 1.0 - pinned_total
        newly_pinned: list[str] = []
        if free_total <= 0:
            equal_share = target_total / len(free)
            for category in free:
                lo = floor.get(category, 0.0)
                hi = ceil.get(category, 1.0)
                values[category], was_pinned = _clamp_candidate(equal_share, lo, hi)
                if was_pinned:
                    newly_pinned.append(category)
        else:
            scale = target_total / free_total
            for category in free:
                lo = floor.get(category, 0.0)
                hi = ceil.get(category, 1.0)
                values[category], was_pinned = _clamp_candidate(
                    values[category] * scale, lo, hi
                )
                if was_pinned:
                    newly_pinned.append(category)
        if not newly_pinned:
            break
        pinned.update(newly_pinned)
    return values


def _to_exact_tokens(
    shares: dict[str, float],
    total_budget: int,
    floor: dict[str, float],
    ceil: dict[str, float],
) -> dict[str, int]:
    """Convert normalized shares to ints summing to EXACTLY ``total_budget``,
    respecting each category's own INTEGER floor/ceil bound (REQ-002) -- not
    just the aggregate sum (REQ-003).

    Clamps each category's raw float value into its OWN integer
    ``[min_tokens, max_tokens]`` bound BEFORE flooring (rather than flooring
    the raw share first and only patching the AGGREGATE remainder after). The
    old flooring-first approach has a structural hole: a category pinned
    exactly at its floor share (e.g. 0.29 of a 100-token budget) floats to
    ``raw = 0.29 * 100 == 28.999999999999996``, so ``int(raw) == 28`` -- one
    token below its integer floor of 29 -- while the aggregate remainder is
    fully absorbed by OTHER categories, so it's never corrected. Clamping into
    the integer bound first rules that out structurally: flooring a value
    already >= an integer bound can never floor below it, and flooring a value
    already <= an integer bound can never floor above it either -- so both
    sides of REQ-002 hold unconditionally, while still tracking the actual
    proportional share (unlike seeding every category at ``min_tokens`` and
    redistributing the FULL budget round-robin, which flattens distinct shares
    into a near-equal split and breaks REQ-005/REQ-006).

    The (typically small) rounding remainder left after clamp-then-floor is
    handed out ONE TOKEN AT A TIME -- in either direction -- to categories
    with headroom under ``max_tokens``/above ``min_tokens``, in a fixed
    deterministic order (largest raw share first, tie-break by ``CATEGORIES``
    index), cycling until exhausted. This keeps the sum exact (REQ-003)
    without ever dumping the whole remainder into a single category (which
    could breach its bound alone).

    Assumes ``floor``/``ceil`` are jointly feasible (``sum(floor) <= 1 <=
    sum(ceil)``), matching ``_enforce_bounds_and_normalize``'s contract. If
    infeasible for this ``total_budget`` (e.g. ``sum(min_tokens) >
    total_budget``), every category's headroom gets exhausted and the residual
    is dumped into the deterministic first category; REQ-002 is best-effort in
    that unsupported case, but REQ-003 never breaks.
    """
    if not shares:
        return {}

    raw = {category: value * total_budget for category, value in shares.items()}
    min_tokens: dict[str, int] = {}
    max_tokens: dict[str, int] = {}
    for category in shares:
        lo = max(math.ceil(floor.get(category, 0.0) * total_budget - 1e-9), 0)
        hi = min(
            math.floor(ceil.get(category, 1.0) * total_budget + 1e-9), total_budget
        )
        hi = max(hi, lo)
        min_tokens[category] = lo
        max_tokens[category] = hi

    values = {
        category: int(
            min(max(raw[category], min_tokens[category]), max_tokens[category])
        )
        for category in shares
    }
    ordering = sorted(
        shares, key=lambda category: (-raw[category], _category_index(category))
    )

    remainder = total_budget - sum(values.values())
    if remainder == 0:
        return values

    step = 1 if remainder > 0 else -1
    left = abs(remainder)
    # No fixed iteration cap: `left` can, in the pathological infeasible-bound
    # case, approach `total_budget`, so bound the safety net on that instead
    # of a handful of passes over `ordering` (which was sufficient only when
    # the remainder was guaranteed small).
    for _ in range(left + len(ordering) + 1):
        if left <= 0:
            break
        progressed = False
        for category in ordering:
            if left <= 0:
                break
            bound = max_tokens[category] if step > 0 else min_tokens[category]
            if step > 0 and values[category] >= bound:
                continue
            if step < 0 and values[category] <= bound:
                continue
            values[category] += step
            left -= 1
            progressed = True
        if not progressed:
            break
    if left > 0:
        # Best-effort fallback for infeasible bounds: no category has
        # headroom left in the needed direction; dump the residual into the
        # deterministic first category rather than silently breaking the sum
        # invariant.
        values[ordering[0]] += step * left
    return values


def _category_index(category: str) -> int:
    return CATEGORIES.index(category) if category in CATEGORIES else len(CATEGORIES)


def default_budget_ratios() -> BudgetRatios:
    """Reasonable default ``BudgetRatios`` covering ``research``/``execution``/``default``.

    Each mode's base ratios sum to 1.0 across all 6 ``CATEGORIES``. Used by
    integration (Task 3/4) when the caller does not supply custom ratios.

    - ``research``: favors ``content`` (exploration) over ``task``/``events``.
    - ``execution``: favors ``task``/``tools``/``events`` (recent actions) over
      ``content``.
    - ``default``: balanced fallback for unrecognized modes.
    """
    return BudgetRatios(
        per_mode={
            "research": {
                "system": 0.05,
                "tools": 0.15,
                "task": 0.15,
                "memory": 0.15,
                "content": 0.35,
                "events": 0.15,
            },
            "execution": {
                "system": 0.05,
                "tools": 0.20,
                "task": 0.30,
                "memory": 0.10,
                "content": 0.15,
                "events": 0.20,
            },
            "default": {
                "system": 0.10,
                "tools": 0.15,
                "task": 0.20,
                "memory": 0.15,
                "content": 0.20,
                "events": 0.20,
            },
        },
        floor={
            "system": 0.03,
            "tools": 0.05,
            "task": 0.05,
            "memory": 0.05,
            "content": 0.05,
            "events": 0.05,
        },
        ceil={
            "system": 0.20,
            "tools": 0.35,
            "task": 0.45,
            "memory": 0.40,
            "content": 0.50,
            "events": 0.40,
        },
    )
