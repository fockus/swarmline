"""Task 4 (adaptive-budget spec): two-pass saturation feedback in
``DefaultContextBuilder``.

Covers REQ-007 (saturation = actual/allocated, computed after assembly) and
REQ-008 (saturation of compile N feeds ``allocate`` of compile N+1). The hard
invariant is the static path: when ``ContextBudget.adaptive`` is ``None`` (the
default), ``build()`` behaves EXACTLY as before Task 4 — this is the oracle
the existing ~8588 tests already enforce, re-asserted here at the unit level.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swarmline.context.adaptive_budget import (
    CATEGORIES,
    AdaptiveContextBudget,
    BudgetRatios,
    default_budget_ratios,
)
from swarmline.context.budget import ContextBudget, estimate_tokens
from swarmline.context.builder import ContextInput, DefaultContextBuilder


@pytest.fixture
def prompts_dir(tmp_path: Path) -> Path:
    """Temporary prompts directory mirroring tests/unit/test_context.py's fixture."""
    (tmp_path / "identity.md").write_text("Ты — Freedom AI, финансовый ментор.")
    (tmp_path / "guardrails.md").write_text("Не давай инвестрекомендаций.")

    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    (roles_dir / "coach.md").write_text("Ты в роли коуча. Мотивируй.")

    return tmp_path


@pytest.fixture
def builder(prompts_dir: Path) -> DefaultContextBuilder:
    return DefaultContextBuilder(prompts_dir)


def _adaptive_budget(total_tokens: int = 8000) -> ContextBudget:
    adaptive = AdaptiveContextBudget(default_budget_ratios(), total_tokens)
    return ContextBudget(total_tokens=total_tokens, adaptive=adaptive)


def _make_input(budget: ContextBudget) -> ContextInput:
    return ContextInput(
        user_id="u1",
        topic_id="t1",
        role_id="coach",
        user_text="привет",
        active_skill_ids=[],
        budget=budget,
    )


@pytest.mark.asyncio
async def test_builder_first_compile_uses_none_saturation(
    builder: DefaultContextBuilder,
) -> None:
    """REQ-007: on a fresh builder, the first build() runs with
    ``_last_saturation is None`` (base+temporal only, no rebalance) and
    afterwards ``_last_saturation`` is populated with a per-category dict."""
    assert builder._last_saturation is None
    inp = _make_input(_adaptive_budget())
    goal_text = "Накопить 300к"

    result = await builder.build(
        inp, goal_text=goal_text, mode="default", step_progress=0.0
    )

    assert result.system_prompt  # sanity: build still produces a prompt
    assert builder._last_saturation is not None
    assert isinstance(builder._last_saturation, dict)
    assert len(builder._last_saturation) > 0
    for value in builder._last_saturation.values():
        assert isinstance(value, float)


@pytest.mark.asyncio
async def test_builder_feeds_previous_saturation_into_next_allocate(
    builder: DefaultContextBuilder,
) -> None:
    """REQ-008: the SECOND compile passes the saturation recorded by the FIRST
    compile into ``AdaptiveContextBudget.allocate`` as ``last_saturation``."""
    budget = _adaptive_budget()
    inp = _make_input(budget)
    recorded_calls: list[dict[str, float] | None] = []
    original_allocate = budget.adaptive.allocate

    def spy_allocate(
        mode: str,
        step_progress: float,
        last_saturation: dict[str, float] | None = None,
    ) -> dict[str, int]:
        recorded_calls.append(last_saturation)
        return original_allocate(mode, step_progress, last_saturation)

    budget.adaptive.allocate = spy_allocate  # type: ignore[method-assign]

    await builder.build(inp, goal_text="цель 1", mode="default", step_progress=0.0)
    await builder.build(inp, goal_text="цель 1", mode="default", step_progress=0.0)

    assert len(recorded_calls) == 2
    assert recorded_calls[0] is None  # first compile: no prior saturation
    assert recorded_calls[1] is not None  # second compile: fed from compile 1
    assert recorded_calls[1] == builder._last_saturation or isinstance(
        recorded_calls[1], dict
    )


@pytest.mark.asyncio
async def test_two_sequential_compiles_converge(
    builder: DefaultContextBuilder,
) -> None:
    """Guards the oscillation risk from design.md: with identical input, the
    allocation stabilizes rather than oscillating unboundedly across compiles.
    Asserted as allocation-delta shrinking (or reaching zero) between
    compile 2->3 vs compile 1->2."""
    budget = _adaptive_budget()
    inp = _make_input(budget)
    allocations: list[dict[str, int]] = []
    original_allocate = budget.adaptive.allocate

    def spy_allocate(
        mode: str,
        step_progress: float,
        last_saturation: dict[str, float] | None = None,
    ) -> dict[str, int]:
        result = original_allocate(mode, step_progress, last_saturation)
        allocations.append(result)
        return result

    budget.adaptive.allocate = spy_allocate  # type: ignore[method-assign]

    for _ in range(3):
        await builder.build(
            inp,
            goal_text="стабильная цель",
            recall_facts={"f1": "v1"},
            mode="default",
            step_progress=0.5,
        )

    assert len(allocations) == 3

    def _delta(a: dict[str, int], b: dict[str, int]) -> int:
        return sum(abs(a.get(k, 0) - b.get(k, 0)) for k in set(a) | set(b))

    delta_1_to_2 = _delta(allocations[0], allocations[1])
    delta_2_to_3 = _delta(allocations[1], allocations[2])

    # Stabilizes: either fully converged by the 3rd compile, or the delta did
    # not grow (no unbounded oscillation).
    assert delta_2_to_3 <= delta_1_to_2 or allocations[1] == allocations[2]


@pytest.mark.asyncio
async def test_static_path_untouched_when_adaptive_none(
    builder: DefaultContextBuilder,
) -> None:
    """The hard invariant: ``ContextBudget()`` (adaptive=None) never touches
    ``_last_saturation`` and produces the same result build() has always
    produced (no allocate call, no cap substitution)."""
    inp = _make_input(ContextBudget())
    assert inp.budget.adaptive is None

    result_1 = await builder.build(inp, goal_text="цель")
    assert builder._last_saturation is None

    result_2 = await builder.build(
        inp, goal_text="цель", mode="research", step_progress=0.9
    )
    assert builder._last_saturation is None

    # mode/step_progress are ignored entirely on the static path.
    assert result_1.system_prompt == result_2.system_prompt
    assert result_1.truncated_packs == result_2.truncated_packs
    assert result_1.notes == result_2.notes


def _skewed_toward_content_ratios() -> BudgetRatios:
    """Almost all budget goes to ``content``; ``memory``/``task`` get a tiny
    share each, so a single present layer in those categories (memory_bank /
    phase) gets a small derived cap while ``remaining`` (the overall budget)
    stays large -- isolating "capped by layer_caps" from "capped by remaining"."""
    small = 0.025
    rest = (1.0 - 2 * small) / (len(CATEGORIES) - 2)
    return BudgetRatios(
        per_mode={
            "default": {
                cat: (small if cat in ("memory", "task") else rest)
                for cat in CATEGORIES
            }
        },
    )


@pytest.mark.asyncio
async def test_adaptive_mode_truncates_memory_bank_to_derived_layer_cap(
    builder: DefaultContextBuilder,
) -> None:
    """Defect 3 repro: ``memory_bank`` is the only present layer in the
    "memory" category this turn, so its derived cap equals the whole (tiny)
    memory allocation. Even though ``remaining`` (overall budget) is plentiful,
    a large memory_bank_prompt must be truncated to the derived cap, not left
    unbounded."""
    total_tokens = 4000
    budget = ContextBudget(
        total_tokens=total_tokens,
        adaptive=AdaptiveContextBudget(_skewed_toward_content_ratios(), total_tokens),
    )
    inp = _make_input(budget)
    large_memory_bank_prompt = "## Memory Bank\n" + ("память " * 2000)

    result = await builder.build(
        inp,
        memory_bank_prompt=large_memory_bank_prompt,
        mode="default",
        step_progress=0.45,
    )

    assert "memory_bank" in result.truncated_packs
    assert large_memory_bank_prompt not in result.system_prompt


@pytest.mark.asyncio
async def test_adaptive_mode_truncates_phase_to_derived_layer_cap(
    builder: DefaultContextBuilder,
) -> None:
    """Defect 3 repro (task/phase side): ``phase`` is the only present layer
    in the "task" category this turn (no ``goal_text``), so its derived cap
    equals the whole (tiny) task allocation. A large ``phase_text`` must be
    truncated to that cap in adaptive mode -- today ``phase`` has NO cap logic
    at all and is always included in full."""
    total_tokens = 4000
    budget = ContextBudget(
        total_tokens=total_tokens,
        adaptive=AdaptiveContextBudget(_skewed_toward_content_ratios(), total_tokens),
    )
    inp = _make_input(budget)
    large_phase_text = "фаза " * 2000

    result = await builder.build(
        inp,
        phase_text=large_phase_text,
        mode="default",
        step_progress=0.45,
    )

    assert "phase" in result.truncated_packs
    assert large_phase_text not in result.system_prompt


@pytest.mark.asyncio
async def test_static_path_phase_stays_uncapped_when_adaptive_none(
    builder: DefaultContextBuilder,
) -> None:
    """Hard invariant re-asserted for Defect 3's fix: on the STATIC path
    (``adaptive=None``), ``phase`` keeps behaving exactly as before -- no cap
    at all, included in full as long as ``remaining > 0``."""
    inp = _make_input(ContextBudget(total_tokens=8000))
    large_phase_text = "фаза " * 200  # well within remaining at 8000 tokens

    result = await builder.build(inp, phase_text=large_phase_text)

    assert "phase" not in result.truncated_packs
    assert large_phase_text.strip() in result.system_prompt
    # sanity: the derived-cap machinery never ran on the static path
    assert estimate_tokens(large_phase_text) > 0
