"""Task 3 (observability-events spec): hibernate/rehydrate snapshot primitives.

Covers REQ-009 (CostTracker snapshot/restore), REQ-010 (builder saturation
export/import), REQ-011 (HibernateRecord composing both + plan reference).
Scenario 2: hibernate/rehydrate roundtrip preserves cost and budget state.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from swarmline.context.adaptive_budget import (
    AdaptiveContextBudget,
    default_budget_ratios,
)
from swarmline.context.budget import ContextBudget
from swarmline.context.builder import ContextInput, DefaultContextBuilder
from swarmline.runtime.cost import CostBudget, CostTracker, ModelPricing


def _make_tracker() -> CostTracker:
    budget = CostBudget(max_cost_usd=10.0, max_total_tokens=100_000)
    pricing = {
        "model-a": ModelPricing(input_per_1m=2.0, output_per_1m=10.0),
        "_default": ModelPricing(input_per_1m=3.0, output_per_1m=15.0),
    }
    return CostTracker(budget=budget, pricing=pricing)


def test_cost_snapshot_restore_roundtrip_preserves_totals() -> None:
    """REQ-009: snapshot carries only the accumulated counters; restore into a
    fresh CostTracker reproduces the same totals, budget/pricing untouched."""
    original = _make_tracker()
    original.record("model-a", input_tokens=1000, output_tokens=500)
    original.record("model-a", input_tokens=200, output_tokens=100)

    snapshot = original.snapshot()

    # Only the accumulated counters -- NOT constructor config.
    assert "_budget" not in snapshot
    assert "_pricing" not in snapshot
    assert set(snapshot.keys()) == {
        "total_input_tokens",
        "total_output_tokens",
        "total_cost",
    }

    fresh = _make_tracker()
    assert fresh.total_tokens == 0
    assert fresh.total_cost_usd == 0.0

    fresh.restore(snapshot)

    assert fresh.total_tokens == original.total_tokens
    assert fresh.total_cost_usd == pytest.approx(original.total_cost_usd)
    # budget/pricing (constructor config) unaffected by restore
    assert fresh.check_budget() == original.check_budget()


def test_cost_snapshot_is_json_serializable() -> None:
    """The snapshot must be a plain, json-serializable mapping (REQ-009)."""
    tracker = _make_tracker()
    tracker.record("model-a", input_tokens=1000, output_tokens=500)

    snapshot = tracker.snapshot()

    assert json.dumps(snapshot)


def test_cost_restore_requires_all_three_keys() -> None:
    """restore() requires the three counter keys -- no silent tolerance of a
    partial mapping (avoids restoring into an inconsistent half-state)."""
    tracker = _make_tracker()

    with pytest.raises(KeyError):
        tracker.restore({"total_input_tokens": 10})


def test_restore_with_missing_key_leaves_totals_unchanged() -> None:
    """restore() must be atomic: when a required key is missing, KeyError is
    raised BEFORE any counter is mutated, so the tracker's prior totals are
    left exactly as they were (no half-restored state)."""
    tracker = _make_tracker()
    tracker.record("model-a", input_tokens=1000, output_tokens=500)
    prior_input_tokens = tracker.total_tokens
    prior_cost = tracker.total_cost_usd

    with pytest.raises(KeyError):
        tracker.restore(
            {"total_input_tokens": 999, "total_output_tokens": 999}
        )  # missing "total_cost"

    assert tracker.total_tokens == prior_input_tokens
    assert tracker.total_cost_usd == pytest.approx(prior_cost)


@pytest.fixture
def prompts_dir(tmp_path: Path) -> Path:
    """Minimal prompts directory for DefaultContextBuilder."""
    (tmp_path / "identity.md").write_text("Identity text.")
    (tmp_path / "guardrails.md").write_text("Guardrails text.")
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    (roles_dir / "coach.md").write_text("Coach role text.")
    return tmp_path


def _adaptive_budget(total_tokens: int = 8000) -> ContextBudget:
    adaptive = AdaptiveContextBudget(default_budget_ratios(), total_tokens)
    return ContextBudget(total_tokens=total_tokens, adaptive=adaptive)


def _make_input(budget: ContextBudget) -> ContextInput:
    return ContextInput(
        user_id="u1",
        topic_id="t1",
        role_id="coach",
        user_text="hi",
        active_skill_ids=[],
        budget=budget,
    )


def test_export_saturation_none_before_any_adaptive_compile(prompts_dir: Path) -> None:
    """REQ-010: a fresh builder that never ran an adaptive compile exports
    None -- never fabricated."""
    builder = DefaultContextBuilder(prompts_dir)
    assert builder.export_saturation() is None


@pytest.mark.asyncio
async def test_saturation_export_import_steers_next_allocate_identically(
    prompts_dir: Path,
) -> None:
    """REQ-010, scenario 2: exporting the original builder's saturation and
    importing it into a FRESH builder must steer the fresh builder's next
    ``allocate()`` (via build()) identically to the original's."""
    original_budget = _adaptive_budget()
    original = DefaultContextBuilder(prompts_dir)
    inp = _make_input(original_budget)

    # First compile on the original populates _last_saturation.
    await original.build(inp, goal_text="goal one", mode="default", step_progress=0.5)
    exported = original.export_saturation()
    assert exported is not None

    # A brand-new builder + a brand-new (but equally-configured) adaptive
    # budget, seeded via import_saturation instead of a real prior compile.
    fresh_budget = _adaptive_budget()
    fresh = DefaultContextBuilder(prompts_dir)
    fresh.import_saturation(exported)

    original_next_allocated = original_budget.adaptive.allocate(
        "default", 0.5, original.export_saturation()
    )
    fresh_next_allocated = fresh_budget.adaptive.allocate(
        "default", 0.5, fresh.export_saturation()
    )

    assert fresh_next_allocated == original_next_allocated

    # And end-to-end through build() itself: the SECOND compile on each
    # builder (with the same inputs) produces the same system_prompt.
    result_original = await original.build(
        inp, goal_text="goal one", mode="default", step_progress=0.5
    )
    fresh_inp = _make_input(fresh_budget)
    result_fresh = await fresh.build(
        fresh_inp, goal_text="goal one", mode="default", step_progress=0.5
    )
    assert result_fresh.system_prompt == result_original.system_prompt


def test_import_saturation_none_resets_to_none(prompts_dir: Path) -> None:
    """import_saturation(None) clears any prior state back to None."""
    builder = DefaultContextBuilder(prompts_dir)
    builder._last_saturation = {"system": 0.5}

    builder.import_saturation(None)

    assert builder.export_saturation() is None


def test_export_saturation_returns_a_copy_not_a_live_reference(
    prompts_dir: Path,
) -> None:
    """Mutating the exported dict must not mutate the builder's internal state."""
    builder = DefaultContextBuilder(prompts_dir)
    builder._last_saturation = {"system": 0.5}

    exported = builder.export_saturation()
    assert exported is not None
    exported["system"] = 999.0

    assert builder._last_saturation == {"system": 0.5}


def test_hibernate_record_roundtrip_composes_all_four(prompts_dir: Path) -> None:
    """REQ-011: capture_hibernate composes cost snapshot + context-budget
    snapshot + plan_ref + plan_step into one record; the record is
    json-serializable; restore_hibernate mutates FRESH instances so their
    state matches the originals. plan_ref/plan_step carry the plan's identity
    only -- the plan itself is never serialized."""
    from swarmline.observability.hibernate import capture_hibernate, restore_hibernate

    cost_tracker = _make_tracker()
    cost_tracker.record("model-a", input_tokens=1000, output_tokens=500)

    context_builder = DefaultContextBuilder(prompts_dir)
    context_builder._last_saturation = {"system": 0.42, "content": 0.73}

    record = capture_hibernate(
        "session-123",
        cost_tracker=cost_tracker,
        context_builder=context_builder,
        plan_ref="plan-abc",
        plan_step="step-2",
    )

    assert record.session_id == "session-123"
    assert record.plan_ref == "plan-abc"
    assert record.plan_step == "step-2"
    assert record.cost == cost_tracker.snapshot()
    assert record.context_budget == {"system": 0.42, "content": 0.73}

    # json-serializable
    serialized = json.dumps(dataclasses.asdict(record))
    assert serialized

    # plan is NOT serialized -- only the id string is present.
    assert "plan-abc" in serialized
    assert isinstance(record.plan_ref, str)

    # Restore into FRESH instances.
    fresh_cost_tracker = _make_tracker()
    fresh_builder = DefaultContextBuilder(prompts_dir)
    assert fresh_cost_tracker.total_tokens == 0
    assert fresh_builder.export_saturation() is None

    restore_hibernate(
        record, cost_tracker=fresh_cost_tracker, context_builder=fresh_builder
    )

    assert fresh_cost_tracker.total_tokens == cost_tracker.total_tokens
    assert fresh_cost_tracker.total_cost_usd == pytest.approx(
        cost_tracker.total_cost_usd
    )
    assert fresh_builder.export_saturation() == {"system": 0.42, "content": 0.73}


def test_hibernate_record_defaults_plan_ref_and_step_to_none(
    prompts_dir: Path,
) -> None:
    """plan_ref/plan_step are optional -- default to None when the caller has
    no active plan for this session."""
    from swarmline.observability.hibernate import capture_hibernate

    cost_tracker = _make_tracker()
    context_builder = DefaultContextBuilder(prompts_dir)

    record = capture_hibernate(
        "session-no-plan", cost_tracker=cost_tracker, context_builder=context_builder
    )

    assert record.plan_ref is None
    assert record.plan_step is None
    assert record.context_budget is None
    assert json.dumps(dataclasses.asdict(record))


def test_hibernate_record_is_frozen(prompts_dir: Path) -> None:
    """HibernateRecord is an immutable dataclass (domain-object convention)."""
    from swarmline.observability.hibernate import HibernateRecord

    record = HibernateRecord(
        session_id="s1",
        plan_ref=None,
        plan_step=None,
        cost={"total_input_tokens": 0, "total_output_tokens": 0, "total_cost": 0.0},
        context_budget=None,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.session_id = "s2"  # type: ignore[misc]
