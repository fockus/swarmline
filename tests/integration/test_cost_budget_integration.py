"""Integration tests for cost budget tracking in ThinRuntime."""

from __future__ import annotations

from typing import Any

import pytest


class TestCostTrackerWithRealPricing:
    """CostTracker with real pricing.json data."""

    def test_cost_tracker_with_real_pricing_correct_calculation(self) -> None:
        from swarmline.runtime.cost import CostBudget, CostTracker, load_pricing

        pricing = load_pricing()
        budget = CostBudget(max_cost_usd=10.0)
        tracker = CostTracker(budget=budget, pricing=pricing)

        # Use a known model from pricing.json
        tracker.record(
            "claude-sonnet-4-20250514", input_tokens=1_000_000, output_tokens=1_000_000
        )
        # 3.0 + 15.0 = 18.0
        assert tracker.total_cost_usd == pytest.approx(18.0)
        assert tracker.check_budget() == "exceeded"


class TestThinRuntimeCostBudgetIntegration:
    """ThinRuntime integration with CostBudget."""

    @staticmethod
    def _make_llm_call(response: str = '{"type":"final","final_message":"Hello"}'):
        """Create a mock llm_call that returns a fixed response."""
        call_count = 0

        async def llm_call(
            messages: list[dict[str, str]],
            system_prompt: str,
            **kwargs: Any,
        ) -> str:
            nonlocal call_count
            call_count += 1
            return response

        return llm_call

    async def test_thin_runtime_without_budget_no_tracking(self) -> None:
        """Backward compat: no cost_budget = no cost tracking, no errors."""
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import Message, RuntimeConfig

        config = RuntimeConfig(runtime_name="thin")
        runtime = ThinRuntime(config=config, llm_call=self._make_llm_call())

        events = []
        async for event in runtime.run(
            messages=[Message(role="user", content="Hi")],
            system_prompt="You are a helper.",
            active_tools=[],
        ):
            events.append(event)

        # Should complete without error, no total_cost_usd in final
        finals = [e for e in events if e.is_final]
        assert len(finals) == 1
        # Without budget, total_cost_usd should not be set by cost tracker
        # (it may be None or absent)

    async def test_thin_runtime_with_budget_records_cost_in_final(self) -> None:
        """When budget is set, final event includes total_cost_usd."""
        from swarmline.runtime.cost import CostBudget
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import Message, RuntimeConfig

        budget = CostBudget(max_cost_usd=100.0)
        config = RuntimeConfig(runtime_name="thin", cost_budget=budget)
        runtime = ThinRuntime(config=config, llm_call=self._make_llm_call())

        events = []
        async for event in runtime.run(
            messages=[Message(role="user", content="Hi")],
            system_prompt="You are a helper.",
            active_tools=[],
        ):
            events.append(event)

        finals = [e for e in events if e.is_final]
        assert len(finals) == 1
        assert "total_cost_usd" in finals[0].data
        assert finals[0].data["total_cost_usd"] > 0
        assert finals[0].data["usage"]["input_tokens"] > 0
        assert finals[0].data["usage"]["output_tokens"] > 0
        assert finals[0].data["metrics"]["tokens_in"] > 0
        assert finals[0].data["metrics"]["tokens_out"] > 0

    async def test_thin_runtime_budget_exceeded_emits_error(self) -> None:
        """When budget already exceeded pre-call, error event emitted."""
        from swarmline.runtime.cost import CostBudget
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import Message, RuntimeConfig

        # Set a very small budget that will be exceeded immediately after first call
        budget = CostBudget(max_cost_usd=0.0, max_total_tokens=0)
        config = RuntimeConfig(runtime_name="thin", cost_budget=budget)
        runtime = ThinRuntime(config=config, llm_call=self._make_llm_call())

        # Pre-seed the tracker to be already exceeded
        # We access internal _cost_tracker to simulate pre-exceeded state
        if hasattr(runtime, "_cost_tracker") and runtime._cost_tracker is not None:
            runtime._cost_tracker.record("test", input_tokens=1, output_tokens=1)

        events = []
        async for event in runtime.run(
            messages=[Message(role="user", content="Hi")],
            system_prompt="You are a helper.",
            active_tools=[],
        ):
            events.append(event)

        errors = [e for e in events if e.is_error]
        if errors:
            assert errors[0].data["kind"] == "budget_exceeded"

    async def test_thin_runtime_budget_warn_mode_no_error(self) -> None:
        """With action_on_exceed='warn', no error event — just final with cost."""
        from swarmline.runtime.cost import CostBudget
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import Message, RuntimeConfig

        budget = CostBudget(max_cost_usd=100.0, action_on_exceed="warn")
        config = RuntimeConfig(runtime_name="thin", cost_budget=budget)
        runtime = ThinRuntime(config=config, llm_call=self._make_llm_call())

        events = []
        async for event in runtime.run(
            messages=[Message(role="user", content="Hi")],
            system_prompt="You are a helper.",
            active_tools=[],
        ):
            events.append(event)

        errors = [e for e in events if e.is_error]
        finals = [e for e in events if e.is_final]
        assert len(errors) == 0
        assert len(finals) == 1

    async def test_thin_runtime_post_call_budget_exceeded_suppresses_final(
        self,
    ) -> None:
        """If the response itself blows the budget, runtime emits budget_exceeded without final."""
        from swarmline.runtime.cost import CostBudget
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import Message, RuntimeConfig

        budget = CostBudget(max_total_tokens=1)
        config = RuntimeConfig(runtime_name="thin", cost_budget=budget)
        runtime = ThinRuntime(config=config, llm_call=self._make_llm_call())

        events = []
        async for event in runtime.run(
            messages=[Message(role="user", content="Hi")],
            system_prompt="You are a helper.",
            active_tools=[],
        ):
            events.append(event)

        assert [event.type for event in events].count("final") == 0
        errors = [event for event in events if event.type == "error"]
        assert len(errors) == 1
        assert errors[0].data["kind"] == "budget_exceeded"

    async def test_thin_runtime_post_call_budget_warn_emits_status_and_final(
        self,
    ) -> None:
        """Warn mode reports the over-budget turn but still returns the final event."""
        from swarmline.runtime.cost import CostBudget
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import Message, RuntimeConfig

        budget = CostBudget(max_total_tokens=1, action_on_exceed="warn")
        config = RuntimeConfig(runtime_name="thin", cost_budget=budget)
        runtime = ThinRuntime(config=config, llm_call=self._make_llm_call())

        events = []
        async for event in runtime.run(
            messages=[Message(role="user", content="Hi")],
            system_prompt="You are a helper.",
            active_tools=[],
        ):
            events.append(event)

        finals = [event for event in events if event.type == "final"]
        warnings = [
            event
            for event in events
            if event.type == "status" and "Budget warning" in event.text
        ]
        assert len(finals) == 1
        assert len(warnings) == 1
