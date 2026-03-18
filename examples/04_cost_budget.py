"""Cost budget tracking for LLM calls.

Demonstrates: CostBudget, CostTracker, ModelPricing, budget status checks.
No API keys required.
"""

import asyncio

from cognitia.runtime.cost import CostBudget, CostTracker, ModelPricing


async def main() -> None:
    # 1. Define pricing for models
    pricing = {
        "gpt-4o": ModelPricing(input_per_1m=2.50, output_per_1m=10.00),
        "claude-sonnet": ModelPricing(input_per_1m=3.00, output_per_1m=15.00),
    }

    # 2. Set a budget: max $0.01, error on exceed
    budget = CostBudget(max_cost_usd=0.01, action_on_exceed="error")
    tracker = CostTracker(budget=budget, pricing=pricing)

    # 3. Simulate LLM calls
    tracker.record("gpt-4o", input_tokens=500, output_tokens=200)
    print(f"After call 1: cost=${tracker.total_cost_usd:.6f}, status={tracker.check_budget()}")

    tracker.record("claude-sonnet", input_tokens=1000, output_tokens=500)
    print(f"After call 2: cost=${tracker.total_cost_usd:.6f}, status={tracker.check_budget()}")

    # 4. Blow the budget
    tracker.record("gpt-4o", input_tokens=50_000, output_tokens=20_000)
    print(f"After call 3: cost=${tracker.total_cost_usd:.4f}, status={tracker.check_budget()}")
    print(f"Total tokens used: {tracker.total_tokens}")

    # 5. Reset and start fresh
    tracker.reset()
    print(f"After reset: cost=${tracker.total_cost_usd:.2f}, status={tracker.check_budget()}")


if __name__ == "__main__":
    asyncio.run(main())
