"""Tests for AdaptiveContextBudget.allocate — base ratio + temporal shift +
saturation rebalance + floor/ceil bounds + normalize + exact-sum rounding.

Part of the ``adaptive-budget`` spec (REQ-001, REQ-002, REQ-003, REQ-005,
REQ-006, REQ-008). Pure application-layer logic, zero IO (REQ-004).
"""

from __future__ import annotations

import math

import pytest

from swarmline.context.adaptive_budget import (
    CATEGORIES,
    AdaptiveContextBudget,
    BudgetRatios,
    _enforce_bounds_and_normalize,
    _to_exact_tokens,
    default_budget_ratios,
)

TOTAL_BUDGET = 1000


def test_to_exact_tokens_spreads_remainder_one_at_a_time_never_breaching_ceil() -> None:
    """Defect 1 repro: when the rounding remainder (4) cannot be absorbed by any
    SINGLE category without breaching its ceil (16+4=20 > 17), the old code
    dumped the whole remainder into the largest category (breaching REQ-002).
    The fix must spread it one token at a time across categories with headroom."""
    shares = {cat: 1.0 / len(CATEGORIES) for cat in CATEGORIES}
    ceil = {cat: 0.17 for cat in CATEGORIES}
    floor = {cat: 0.0 for cat in CATEGORIES}

    result = _to_exact_tokens(shares, 100, floor, ceil)

    assert sum(result.values()) == 100
    for cat in CATEGORIES:
        assert result[cat] <= 17, f"{cat}={result[cat]} breaches ceil 17"


def test_to_exact_tokens_via_allocate_respects_ceil_on_tight_equal_split() -> None:
    """Same repro as above but through the public ``allocate()`` entry point,
    matching the exact scenario described in the defect report end-to-end."""
    ratios = BudgetRatios(
        per_mode={"default": {cat: 1.0 / len(CATEGORIES) for cat in CATEGORIES}},
        floor={cat: 0.0 for cat in CATEGORIES},
        ceil={cat: 0.17 for cat in CATEGORIES},
    )
    budget = AdaptiveContextBudget(ratios, 100)

    result = budget.allocate("default", step_progress=0.45)

    assert sum(result.values()) == 100
    for cat in CATEGORIES:
        assert result[cat] <= 17, f"{cat}={result[cat]} breaches ceil 17"


def test_to_exact_tokens_respects_per_category_integer_floor_not_just_sum() -> None:
    """Defect 1 (floor side, round 2): a category pinned exactly at its floor
    share (0.29) can still land 1 token BELOW its own integer floor because
    float multiplication makes ``raw = 0.29 * 100 == 28.999999999999996``, so
    ``int(raw) == 28`` -- and the aggregate remainder can be fully absorbed by
    OTHER categories (sum already == total_budget), so this per-category
    shortfall is never corrected by the old remainder-only distribution. The
    fix must guarantee every category's tokens are >= its own integer floor
    bound (``ceil(floor_share * total_budget)``), not just that the total sum
    is exact."""
    shares = {"system": 0.29, "tools": 0.71}
    floor = {"system": 0.29}
    ceil: dict[str, float] = {}

    result = _to_exact_tokens(shares, 100, floor, ceil)

    assert sum(result.values()) == 100
    assert result["system"] >= 29, f"system={result['system']} below integer floor 29"


def test_to_exact_tokens_via_allocate_respects_integer_floor_end_to_end() -> None:
    """Same repro as above but through the public ``allocate()`` entry point."""
    ratios = BudgetRatios(
        per_mode={"default": {"system": 0.29, "tools": 0.71}},
        floor={"system": 0.29},
        ceil={},
    )
    budget = AdaptiveContextBudget(ratios, 100)

    result = budget.allocate("default", step_progress=0.45)

    assert sum(result.values()) == 100
    assert result["system"] >= 29, f"system={result['system']} below integer floor 29"


def test_to_exact_tokens_tight_floor_and_tight_ceil_both_respected_non_round_total() -> (
    None
):
    """Combined repro: one category with a tight floor, another with a tight
    ceil, and a total_budget that is not a round multiple of the shares --
    every category's tokens must land within its OWN integer
    [floor, ceil] bounds, and the sum must still be exact."""
    shares = {"system": 0.29, "tools": 0.41, "task": 0.30}
    floor = {"system": 0.29}
    ceil = {"tools": 0.42}
    total_budget = 97

    result = _to_exact_tokens(shares, total_budget, floor, ceil)

    assert sum(result.values()) == total_budget
    min_system = math.ceil(0.29 * total_budget - 1e-9)
    max_tools = math.floor(0.42 * total_budget + 1e-9)
    assert result["system"] >= min_system, f"system={result['system']} < {min_system}"
    assert result["tools"] <= max_tools, f"tools={result['tools']} > {max_tools}"


def test_to_exact_tokens_negative_remainder_respects_floor() -> None:
    """Defect 1 (floor side): when floored raw values OVERSHOOT total_budget
    (raw shares summing above 1.0 -- reachable via float drift upstream), the
    remainder is negative. The fix must remove tokens one at a time only from
    categories that still have headroom ABOVE their floor, never ignoring
    floor (the old code had a dead ``cap=0.0`` placeholder here)."""
    shares = {"system": 0.6, "tools": 0.45}
    floor = {"system": 0.5, "tools": 0.3}
    ceil: dict[str, float] = {}

    result = _to_exact_tokens(shares, 100, floor, ceil)

    assert sum(result.values()) == 100
    assert result["system"] >= 50
    assert result["tools"] >= 30


def test_enforce_bounds_free_total_zero_still_respects_tight_ceil() -> None:
    """Defect 2 repro: once A and B get pinned at their ceilings, the two
    categories left free (C, D) have a combined CURRENT value of exactly 0
    (their incoming share was 0, and 0 * scale stays 0) -- the ``free_total <=
    0`` shortcut must still clamp the equal split into [floor, ceil] instead of
    handing out an unclamped equal share that breaches C's tight ceil."""
    shares = {"A": 0.6, "B": 0.4, "C": 0.0, "D": 0.0}
    floor: dict[str, float] = {}
    ceil = {"A": 0.3, "B": 0.3, "C": 0.05}

    result = _enforce_bounds_and_normalize(shares, floor, ceil)

    assert result["C"] <= 0.05 + 1e-9, f"C={result['C']} breaches ceil 0.05"
    for category, value in result.items():
        lo = floor.get(category, 0.0)
        hi = ceil.get(category, 1.0)
        assert lo - 1e-9 <= value <= hi + 1e-9, f"{category}={value} out of [{lo},{hi}]"
    assert sum(result.values()) == pytest.approx(1.0)


@pytest.mark.parametrize("mode", ["research", "execution", "default"])
def test_allocation_sums_to_total_budget_for_every_mode(mode: str) -> None:
    """REQ-003: every category allocation for every mode sums to the total budget."""
    budget = AdaptiveContextBudget(default_budget_ratios(), TOTAL_BUDGET)

    result = budget.allocate(mode, step_progress=0.5)

    assert sum(result.values()) == TOTAL_BUDGET


@pytest.mark.parametrize("step_progress", [0.0, 0.15, 0.3, 0.45, 0.6, 0.75, 1.0])
def test_allocation_sums_to_total_budget_across_progress_range(
    step_progress: float,
) -> None:
    """REQ-003 must hold across the whole step_progress range, including the
    temporal-shift boundaries (0.3, 0.6)."""
    budget = AdaptiveContextBudget(default_budget_ratios(), TOTAL_BUDGET)

    result = budget.allocate("research", step_progress=step_progress)

    assert sum(result.values()) == TOTAL_BUDGET


def test_default_ratios_each_mode_sums_to_one() -> None:
    """Each configured mode's base ratios sum to 1.0 across the 6 categories."""
    ratios = default_budget_ratios()

    for mode, per_category in ratios.per_mode.items():
        assert set(per_category) == set(CATEGORIES), mode
        assert sum(per_category.values()) == pytest.approx(1.0), mode


def test_early_progress_boosts_content() -> None:
    """REQ-005 / scenario 1: near step_progress=0.0, content gets a larger
    share than the mid-task baseline."""
    budget = AdaptiveContextBudget(default_budget_ratios(), TOTAL_BUDGET)

    early = budget.allocate("research", step_progress=0.0)
    mid = budget.allocate("research", step_progress=0.45)

    assert early["content"] > mid["content"]


def test_late_progress_boosts_events_memory() -> None:
    """REQ-006: near step_progress=1.0, events+memory get a larger combined
    share than the mid-task baseline."""
    budget = AdaptiveContextBudget(default_budget_ratios(), TOTAL_BUDGET)

    late = budget.allocate("research", step_progress=0.9)
    mid = budget.allocate("research", step_progress=0.45)

    assert (late["events"] + late["memory"]) > (mid["events"] + mid["memory"])


def test_saturation_rebalances_from_underfilled_to_overfilled() -> None:
    """REQ-008 / scenario 2: a category under 0.5 saturation gives up share to
    a category over 0.8 saturation; bounds are still respected."""
    equal_ratios = BudgetRatios(
        per_mode={"default": {cat: 1.0 / len(CATEGORIES) for cat in CATEGORIES}},
        floor={cat: 0.0 for cat in CATEGORIES},
        ceil={cat: 1.0 for cat in CATEGORIES},
    )
    budget = AdaptiveContextBudget(equal_ratios, TOTAL_BUDGET)
    # step_progress in the neutral zone (0.3 < p < 0.6) so temporal shift does
    # not interfere with isolating the saturation-rebalance effect.
    baseline = budget.allocate("default", step_progress=0.45)
    saturation = {"system": 0.2, "content": 0.9}

    rebalanced = budget.allocate(
        "default", step_progress=0.45, last_saturation=saturation
    )

    assert rebalanced["system"] < baseline["system"]
    assert rebalanced["content"] > baseline["content"]
    assert sum(rebalanced.values()) == TOTAL_BUDGET


def test_bounds_enforced_floor_ceil() -> None:
    """REQ-002: a tight ceil/floor is never breached by the final allocation."""
    even_share = 1.0 / len(CATEGORIES)
    ratios = BudgetRatios(
        per_mode={"default": {cat: even_share for cat in CATEGORIES}},
        floor={"system": 0.5},
        ceil={"content": 0.05},
    )
    budget = AdaptiveContextBudget(ratios, TOTAL_BUDGET)

    result = budget.allocate("default", step_progress=0.45)

    assert result["content"] <= 0.05 * TOTAL_BUDGET
    assert result["system"] >= 0.5 * TOTAL_BUDGET
    assert sum(result.values()) == TOTAL_BUDGET


def test_bounds_enforced_even_with_temporal_shift_and_saturation() -> None:
    """REQ-002 must hold end-to-end, not just on the isolated bounds step."""
    even_share = 1.0 / len(CATEGORIES)
    ratios = BudgetRatios(
        per_mode={"default": {cat: even_share for cat in CATEGORIES}},
        floor={},
        ceil={"content": 0.10, "events": 0.10, "memory": 0.10},
    )
    budget = AdaptiveContextBudget(ratios, TOTAL_BUDGET)

    # step_progress=0.0 boosts content; step_progress=0.9 boosts events+memory —
    # both are exactly the paths that would try to push past the tight ceils.
    early = budget.allocate(
        "default", step_progress=0.0, last_saturation={"content": 0.95}
    )
    late = budget.allocate(
        "default", step_progress=0.9, last_saturation={"events": 0.95, "memory": 0.95}
    )

    assert early["content"] <= 0.10 * TOTAL_BUDGET
    assert late["events"] <= 0.10 * TOTAL_BUDGET
    assert late["memory"] <= 0.10 * TOTAL_BUDGET
    assert sum(early.values()) == TOTAL_BUDGET
    assert sum(late.values()) == TOTAL_BUDGET


def test_first_pass_none_saturation_uses_base_plus_temporal() -> None:
    """last_saturation=None does not crash and matches the default (omitted)
    argument — i.e. only base+temporal shift are applied, no rebalance."""
    budget = AdaptiveContextBudget(default_budget_ratios(), TOTAL_BUDGET)

    explicit_none = budget.allocate("research", step_progress=0.5, last_saturation=None)
    omitted = budget.allocate("research", step_progress=0.5)

    assert explicit_none == omitted
    assert sum(explicit_none.values()) == TOTAL_BUDGET


@pytest.mark.parametrize(
    "saturation",
    [
        {"system": 0.1, "tools": 0.95},
        {"task": 0.05, "memory": 0.85, "content": 0.9},
        {"events": 0.49, "system": 0.81},
        {},
    ],
)
def test_sum_invariant_holds_with_saturation_rebalance_active(
    saturation: dict[str, float],
) -> None:
    """REQ-003 rounding must still be exact once saturation rebalance runs."""
    budget = AdaptiveContextBudget(default_budget_ratios(), TOTAL_BUDGET)

    result = budget.allocate(
        "execution", step_progress=0.45, last_saturation=saturation
    )

    assert sum(result.values()) == TOTAL_BUDGET
    assert set(result) == set(CATEGORIES)


def test_unknown_mode_falls_back_to_default_ratios() -> None:
    """A mode missing from per_mode falls back to the 'default' entry rather
    than crashing."""
    budget = AdaptiveContextBudget(default_budget_ratios(), TOTAL_BUDGET)

    result = budget.allocate("nonexistent-mode", step_progress=0.5)
    expected = budget.allocate("default", step_progress=0.5)

    assert result == expected


def test_unknown_mode_falls_back_to_first_mode_when_no_default_entry() -> None:
    """When neither the requested mode nor 'default' is configured, allocate
    falls back to the first configured mode instead of raising."""
    ratios = BudgetRatios(
        per_mode={
            "only-mode": {cat: 1.0 / len(CATEGORIES) for cat in CATEGORIES},
        },
    )
    budget = AdaptiveContextBudget(ratios, TOTAL_BUDGET)

    result = budget.allocate("missing", step_progress=0.5)

    assert sum(result.values()) == TOTAL_BUDGET
