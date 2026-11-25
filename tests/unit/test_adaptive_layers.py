"""Task 4 (adaptive-budget spec): pure helpers used by the builder's two-pass
allocation - ``derive_layer_caps`` and ``category_actuals``.

Kept in their own tiny module (``adaptive_layers.py``) purely to respect the
file-size ceiling on ``builder.py``; tested directly here, independent of the
full ``DefaultContextBuilder`` (see ``test_adaptive_builder_twopass.py`` for
the integration-level two-pass behavior).
"""

from __future__ import annotations

from swarmline.context.adaptive_layers import category_actuals, derive_layer_caps


def test_derive_layer_caps_splits_equally_among_present_layers_in_shared_category() -> (
    None
):
    """ "memory" category is shared by memory_bank/memory_recall/user_profile;
    when all three are present, the category budget splits 3 ways."""
    allocated = {"memory": 900, "task": 500}
    present_layers = {
        "memory_bank": True,
        "memory_recall": True,
        "user_profile": True,
        "goal": True,
        "phase": False,
    }

    caps = derive_layer_caps(allocated, present_layers)

    assert caps["memory_bank"] == 300
    assert caps["memory_recall"] == 300
    assert caps["user_profile"] == 300
    assert caps["goal"] == 500  # only present layer of "task" -> gets it all
    assert "phase" not in caps  # absent this turn


def test_derive_layer_caps_ignores_absent_layers_when_splitting() -> None:
    """A category with only one present layer this turn gets the whole share,
    even though the category is normally shared by more layers."""
    allocated = {"memory": 900}
    present_layers = {
        "memory_bank": False,
        "memory_recall": True,
        "user_profile": False,
    }

    caps = derive_layer_caps(allocated, present_layers)

    assert caps == {"memory_recall": 900}


def test_derive_layer_caps_no_present_layers_in_category_yields_no_entries() -> None:
    """If nothing in a category is present, no caps are derived for it."""
    allocated = {"tools": 400}
    present_layers = {"tool_hints": False}

    caps = derive_layer_caps(allocated, present_layers)

    assert caps == {}


def test_derive_layer_caps_missing_category_in_allocated_defaults_to_zero() -> None:
    """Defensive: a category absent from ``allocated`` floors the split to 0."""
    allocated: dict[str, int] = {}
    present_layers = {"goal": True}

    caps = derive_layer_caps(allocated, present_layers)

    assert caps == {"goal": 0}


def test_derive_layer_caps_distributes_floor_division_remainder_across_layers() -> None:
    """Defect 4 repro: 1000 // 3 == 333, so a naive equal split (333+333+333 ==
    999) silently loses a token vs the 1000 actually allocated, distorting
    saturation feedback on tight budgets. The remainder must be handed out
    across the category's present layers (stable ``LAYER_TO_CATEGORY`` order:
    memory_bank, memory_recall, user_profile) so the caps sum EXACTLY to the
    category's allocation."""
    allocated = {"memory": 1000}
    present_layers = {
        "memory_bank": True,
        "memory_recall": True,
        "user_profile": True,
    }

    caps = derive_layer_caps(allocated, present_layers)

    assert caps["memory_bank"] + caps["memory_recall"] + caps["user_profile"] == 1000
    assert caps["memory_bank"] == 334
    assert caps["memory_recall"] == 333
    assert caps["user_profile"] == 333


def test_category_actuals_sums_within_category() -> None:
    """Layers sharing a category are summed into a single category total."""
    layer_tokens = {
        "memory_bank": 100,
        "memory_recall": 50,
        "user_profile": 25,
        "goal": 200,
    }

    totals = category_actuals(layer_tokens)

    assert totals["memory"] == 175
    assert totals["task"] == 200


def test_category_actuals_empty_input_yields_empty_output() -> None:
    assert category_actuals({}) == {}
