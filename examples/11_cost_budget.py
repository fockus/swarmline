"""Cost budget tracking and enforcement.

Demonstrates: CostBudget, CostTracker, ModelPricing, load_pricing.
No API keys required.
"""

import asyncio

from swarmline.runtime.cost import (
    CostBudget,
    CostTracker,
    ModelPricing,
    load_pricing,
)


async def main() -> None:
    # 1. Load bundled pricing data
    pricing = load_pricing()
    print(f"Known models: {len(pricing)}")
    for model_name in list(pricing)[:3]:
        p = pricing[model_name]
        print(f"  {model_name}: ${p.input_per_1m}/1M input, ${p.output_per_1m}/1M output")

    # 2. Create cost budget and tracker
    budget = CostBudget(max_cost_usd=1.0, action_on_exceed="error")
    tracker = CostTracker(budget=budget, pricing=pricing)

    # 3. Record some usage
    tracker.record(model="claude-sonnet-4-20250514", input_tokens=1000, output_tokens=500)
    print(f"\nAfter call 1: ${tracker.total_cost_usd:.6f}")

    tracker.record(model="claude-sonnet-4-20250514", input_tokens=5000, output_tokens=2000)
    print(f"After call 2: ${tracker.total_cost_usd:.6f}")

    # 4. Check budget status
    status = tracker.check_budget()
    print(f"Budget status: {status}")
    print(f"Remaining: ${budget.max_cost_usd - tracker.total_cost_usd:.6f}")

    # 5. Custom pricing for unlisted models
    custom = {"my-local-model": ModelPricing(input_per_1m=0.0, output_per_1m=0.0)}
    custom.update(pricing)
    free_tracker = CostTracker(budget=budget, pricing=custom)
    free_tracker.record(model="my-local-model", input_tokens=100000, output_tokens=50000)
    print(f"\nLocal model cost: ${free_tracker.total_cost_usd:.6f} (free!)")

    # 6. Token budget (alternative to cost budget)
    token_budget = CostBudget(max_total_tokens=10000, action_on_exceed="warn")
    print(f"\nToken budget: {token_budget.max_total_tokens} tokens max")
    print(f"Action on exceed: {token_budget.action_on_exceed}")


if __name__ == "__main__":
    asyncio.run(main())
