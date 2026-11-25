"""Task 3 (adaptive-budget spec): P0-P5 layer -> 6-category mapping (opt-in) +
``ContextBudget.adaptive``.

Covers REQ-009 (adaptive disabled -> static per-layer caps) and REQ-010
(existing tests stay green, config optional & None-default). Pure
application-layer assertions, zero IO beyond the existing builder fixtures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swarmline.context.adaptive_budget import (
    CATEGORIES,
    AdaptiveContextBudget,
    default_budget_ratios,
)
from swarmline.context.budget import LAYER_TO_CATEGORY, ContextBudget
from swarmline.context.builder import ContextInput, DefaultContextBuilder

# Every builder layer key that must be present in LAYER_TO_CATEGORY (enumerated
# explicitly so a future dropped/renamed layer fails this test instead of
# silently losing its mapping).
EXPECTED_LAYER_KEYS = (
    "guardrails",
    "role",
    "memory_bank",
    "goal",
    "phase",
    "tool_hints",
    "last_messages",
    "memory_recall",
    "user_profile",
    "available_files",
    "summary",
)


def test_layer_to_category_mapping_covers_all_layers() -> None:
    """Every builder layer must be mapped, and only to one of the 6 CATEGORIES."""
    for layer_key in EXPECTED_LAYER_KEYS:
        assert layer_key in LAYER_TO_CATEGORY, (
            f"missing mapping for layer {layer_key!r}"
        )
    for layer_key, category in LAYER_TO_CATEGORY.items():
        assert category in CATEGORIES, (
            f"layer {layer_key!r} maps to {category!r} which is not in CATEGORIES"
        )
    # No stray/unexpected keys either - keep the table exactly in sync with the builder.
    assert set(LAYER_TO_CATEGORY.keys()) == set(EXPECTED_LAYER_KEYS)


@pytest.mark.parametrize(
    ("layer_key", "expected_category"),
    [
        ("guardrails", "system"),
        ("role", "system"),
        ("memory_bank", "memory"),
        ("goal", "task"),
        ("phase", "task"),
        ("tool_hints", "tools"),
        ("last_messages", "events"),
        ("memory_recall", "memory"),
        ("user_profile", "memory"),
        ("available_files", "memory"),
        ("summary", "content"),
    ],
)
def test_layer_to_category_mapping_matches_spec_table(
    layer_key: str, expected_category: str
) -> None:
    """Each layer maps exactly to the category documented in the spec table."""
    assert LAYER_TO_CATEGORY[layer_key] == expected_category


def test_static_path_unchanged_when_adaptive_none() -> None:
    """REQ-009 scenario 3: adaptive=None -> static caps keep their documented
    defaults and nothing about the existing behavior changes."""
    budget = ContextBudget()

    assert budget.adaptive is None
    assert budget.total_tokens == 8000
    assert budget.guardrails_reserved == 1500
    assert budget.goal_max == 1000
    assert budget.tools_max == 2000
    assert budget.messages_max == 2000
    assert budget.memory_max == 1500
    assert budget.profile_max == 1000
    assert budget.summary_max == 1000


@pytest.mark.asyncio
async def test_static_path_builds_context_unchanged_when_adaptive_none(
    tmp_path: Path,
) -> None:
    """REQ-009: a default-budget ContextInput with adaptive=None still produces
    a normal BuiltContext (builder behavior is untouched by Task 3)."""
    (tmp_path / "identity.md").write_text("Identity.", encoding="utf-8")
    (tmp_path / "guardrails.md").write_text("Guardrails.", encoding="utf-8")
    builder = DefaultContextBuilder(tmp_path)
    inp = ContextInput(
        user_id="u1",
        topic_id="t1",
        role_id="unknown_role",
        user_text="hello",
        active_skill_ids=[],
    )

    result = await builder.build(inp)

    assert inp.budget.adaptive is None
    assert "Identity." in result.system_prompt
    assert "Guardrails." in result.system_prompt
    assert result.truncated_packs == []


def test_context_budget_accepts_adaptive() -> None:
    """Opt-in: ContextBudget can store an AdaptiveContextBudget reference."""
    adaptive = AdaptiveContextBudget(default_budget_ratios(), 8000)

    budget = ContextBudget(adaptive=adaptive)

    assert budget.adaptive is adaptive
