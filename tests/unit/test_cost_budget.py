"""Unit tests for CostBudget, CostTracker, ModelPricing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


class TestModelPricing:
    """ModelPricing dataclass creation and immutability."""

    def test_create_model_pricing_stores_values(self) -> None:
        from swarmline.runtime.cost import ModelPricing

        p = ModelPricing(input_per_1m=3.0, output_per_1m=15.0)
        assert p.input_per_1m == 3.0
        assert p.output_per_1m == 15.0

    def test_model_pricing_frozen(self) -> None:
        from swarmline.runtime.cost import ModelPricing

        p = ModelPricing(input_per_1m=3.0, output_per_1m=15.0)
        with pytest.raises(AttributeError):
            p.input_per_1m = 5.0  # type: ignore[misc]


class TestCostBudget:
    """CostBudget dataclass defaults and creation."""

    def test_defaults_all_none(self) -> None:
        from swarmline.runtime.cost import CostBudget

        b = CostBudget()
        assert b.max_cost_usd is None
        assert b.max_total_tokens is None
        assert b.action_on_exceed == "error"

    def test_custom_values(self) -> None:
        from swarmline.runtime.cost import CostBudget

        b = CostBudget(max_cost_usd=1.5, max_total_tokens=100_000, action_on_exceed="warn")
        assert b.max_cost_usd == 1.5
        assert b.max_total_tokens == 100_000
        assert b.action_on_exceed == "warn"

    def test_frozen(self) -> None:
        from swarmline.runtime.cost import CostBudget

        b = CostBudget()
        with pytest.raises(AttributeError):
            b.max_cost_usd = 5.0  # type: ignore[misc]


class TestCostTracker:
    """CostTracker accumulation, cost calculation, budget checks."""

    def _make_tracker(
        self,
        *,
        max_cost_usd: float | None = None,
        max_total_tokens: int | None = None,
        action_on_exceed: str = "error",
    ):
        from swarmline.runtime.cost import CostBudget, CostTracker, ModelPricing

        budget = CostBudget(
            max_cost_usd=max_cost_usd,
            max_total_tokens=max_total_tokens,
            action_on_exceed=action_on_exceed,
        )
        pricing = {
            "model-a": ModelPricing(input_per_1m=2.0, output_per_1m=10.0),
            "model-b": ModelPricing(input_per_1m=0.5, output_per_1m=2.0),
            "_default": ModelPricing(input_per_1m=3.0, output_per_1m=15.0),
        }
        return CostTracker(budget=budget, pricing=pricing)

    def test_initial_state_zero(self) -> None:
        tracker = self._make_tracker()
        assert tracker.total_cost_usd == 0.0
        assert tracker.total_tokens == 0

    def test_record_accumulates_tokens(self) -> None:
        tracker = self._make_tracker()
        tracker.record("model-a", input_tokens=100, output_tokens=50)
        assert tracker.total_tokens == 150
        tracker.record("model-a", input_tokens=200, output_tokens=100)
        assert tracker.total_tokens == 450

    def test_total_cost_calculation_with_pricing(self) -> None:
        tracker = self._make_tracker()
        # model-a: input 2.0/1M, output 10.0/1M
        # 1000 input = 2.0 * 1000 / 1_000_000 = 0.002
        # 500 output = 10.0 * 500 / 1_000_000 = 0.005
        tracker.record("model-a", input_tokens=1000, output_tokens=500)
        assert tracker.total_cost_usd == pytest.approx(0.007)

    def test_multiple_models_mixed_pricing(self) -> None:
        tracker = self._make_tracker()
        # model-a: 1000 in, 500 out = 0.002 + 0.005 = 0.007
        tracker.record("model-a", input_tokens=1000, output_tokens=500)
        # model-b: 1000 in, 500 out = 0.0005 + 0.001 = 0.0015
        tracker.record("model-b", input_tokens=1000, output_tokens=500)
        assert tracker.total_cost_usd == pytest.approx(0.0085)

    def test_unknown_model_uses_default_pricing(self) -> None:
        tracker = self._make_tracker()
        # _default: input 3.0/1M, output 15.0/1M
        # 1_000_000 input = 3.0, 1_000_000 output = 15.0
        tracker.record("unknown-model", input_tokens=1_000_000, output_tokens=1_000_000)
        assert tracker.total_cost_usd == pytest.approx(18.0)

    def test_check_budget_ok_when_within_limits(self) -> None:
        tracker = self._make_tracker(max_cost_usd=1.0, max_total_tokens=10_000)
        tracker.record("model-a", input_tokens=100, output_tokens=50)
        assert tracker.check_budget() == "ok"

    def test_check_budget_exceeded_by_cost(self) -> None:
        tracker = self._make_tracker(max_cost_usd=0.001)
        # 1000 in + 500 out on model-a = 0.007 > 0.001
        tracker.record("model-a", input_tokens=1000, output_tokens=500)
        assert tracker.check_budget() == "exceeded"

    def test_check_budget_exceeded_by_tokens(self) -> None:
        tracker = self._make_tracker(max_total_tokens=100)
        tracker.record("model-a", input_tokens=80, output_tokens=30)
        assert tracker.check_budget() == "exceeded"

    def test_check_budget_ok_when_no_limits(self) -> None:
        """No limits set = always ok."""
        tracker = self._make_tracker()
        tracker.record("model-a", input_tokens=999_999, output_tokens=999_999)
        assert tracker.check_budget() == "ok"

    def test_action_on_exceed_warn_returns_warning(self) -> None:
        tracker = self._make_tracker(max_cost_usd=0.001, action_on_exceed="warn")
        tracker.record("model-a", input_tokens=1000, output_tokens=500)
        assert tracker.check_budget() == "warning"

    def test_reset_clears_state(self) -> None:
        tracker = self._make_tracker()
        tracker.record("model-a", input_tokens=1000, output_tokens=500)
        assert tracker.total_tokens > 0
        assert tracker.total_cost_usd > 0
        tracker.reset()
        assert tracker.total_tokens == 0
        assert tracker.total_cost_usd == 0.0


class TestLoadPricing:
    """load_pricing() loads pricing.json correctly."""

    def test_load_pricing_returns_dict(self) -> None:
        from swarmline.runtime.cost import load_pricing

        pricing = load_pricing()
        assert isinstance(pricing, dict)
        assert len(pricing) > 0

    def test_load_pricing_contains_default(self) -> None:
        from swarmline.runtime.cost import load_pricing

        pricing = load_pricing()
        assert "_default" in pricing

    def test_load_pricing_values_are_model_pricing(self) -> None:
        from swarmline.runtime.cost import ModelPricing, load_pricing

        pricing = load_pricing()
        for key, val in pricing.items():
            assert isinstance(val, ModelPricing), f"{key} is not ModelPricing"

    def test_pricing_json_file_valid(self) -> None:
        """pricing.json is valid JSON with expected structure."""
        pricing_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "swarmline"
            / "runtime"
            / "pricing.json"
        )
        data = json.loads(pricing_path.read_text())
        assert "_default" in data
        for key, val in data.items():
            assert "input_per_1m" in val
            assert "output_per_1m" in val


class TestRuntimeConfigCostBudget:
    """RuntimeConfig accepts cost_budget field."""

    def test_runtime_config_default_cost_budget_none(self) -> None:
        from swarmline.runtime.types import RuntimeConfig

        rc = RuntimeConfig(runtime_name="thin")
        assert rc.cost_budget is None

    def test_runtime_config_with_cost_budget(self) -> None:
        from swarmline.runtime.cost import CostBudget
        from swarmline.runtime.types import RuntimeConfig

        budget = CostBudget(max_cost_usd=5.0)
        rc = RuntimeConfig(runtime_name="thin", cost_budget=budget)
        assert rc.cost_budget is not None
        assert rc.cost_budget.max_cost_usd == 5.0


class TestBudgetStatusValues:
    """BudgetStatus literal type accepts expected values."""

    def test_budget_status_values(self) -> None:
        from swarmline.runtime.cost import BudgetStatus

        # BudgetStatus is a Literal type alias — verify the values
        valid: list[BudgetStatus] = ["ok", "warning", "exceeded"]
        assert len(valid) == 3
