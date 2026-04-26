"""Cost budget tracking for runtime execution.

Provides:
- ModelPricing: per-model token pricing (USD per 1M tokens)
- CostBudget: budget limits configuration
- CostTracker: accumulates usage and checks budget
- load_pricing(): loads pricing.JSON via importlib.resources
"""

from __future__ import annotations

import importlib.resources
import json
from dataclasses import dataclass
from typing import Literal

BudgetStatus = Literal["ok", "warning", "exceeded"]


@dataclass(frozen=True)
class ModelPricing:
    """Per-model token pricing in USD per 1M tokens."""

    input_per_1m: float
    output_per_1m: float


@dataclass(frozen=True)
class CostBudget:
    """Budget limits for cost tracking.

    Attributes:
      max_cost_usd: Maximum total cost in USD. None = no limit.
      max_total_tokens: Maximum total tokens (input + output). None = no limit.
      action_on_exceed: What to do when budget is exceeded.
        "error" = emit budget_exceeded error event.
        "warn" = report warning status but continue.
    """

    max_cost_usd: float | None = None
    max_total_tokens: int | None = None
    action_on_exceed: Literal["error", "warn"] = "error"


class CostTracker:
    """Accumulates token usage and checks budget limits.

    Thread-safe for single-threaded async usage (no locks needed).
    """

    def __init__(self, budget: CostBudget, pricing: dict[str, ModelPricing]) -> None:
        self._budget = budget
        self._pricing = pricing
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._total_cost: float = 0.0

    def record(self, model: str, input_tokens: int, output_tokens: int) -> None:
        """Record token usage for a single LLM call."""
        pricing = self._pricing.get(model) or self._pricing.get("_default")
        if pricing is None:
            return

        cost = (
            pricing.input_per_1m * input_tokens / 1_000_000
            + pricing.output_per_1m * output_tokens / 1_000_000
        )
        self._total_input_tokens += input_tokens
        self._total_output_tokens += output_tokens
        self._total_cost += cost

    @property
    def total_cost_usd(self) -> float:
        """Total accumulated cost in USD."""
        return self._total_cost

    @property
    def total_tokens(self) -> int:
        """Total accumulated tokens (input + output)."""
        return self._total_input_tokens + self._total_output_tokens

    def check_budget(self) -> BudgetStatus:
        """Check whether budget limits have been exceeded.

        Returns:
          "ok" - wiThin limits (or no limits set).
          "exceeded" - over limit with action_on_exceed="error".
          "warning" - over limit with action_on_exceed="warn".
        """
        exceeded = False
        if (
            self._budget.max_cost_usd is not None
            and self._total_cost > self._budget.max_cost_usd
        ):
            exceeded = True
        if (
            self._budget.max_total_tokens is not None
            and self.total_tokens > self._budget.max_total_tokens
        ):
            exceeded = True

        if not exceeded:
            return "ok"

        if self._budget.action_on_exceed == "warn":
            return "warning"
        return "exceeded"

    def reset(self) -> None:
        """Reset all accumulated usage to zero."""
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_cost = 0.0


def load_pricing() -> dict[str, ModelPricing]:
    """Load model pricing from bundled pricing.JSON.

    Uses importlib.resources for reliable package-relative loading.
    """
    ref = importlib.resources.files("swarmline.runtime").joinpath("pricing.json")
    raw = ref.read_text(encoding="utf-8")
    data: dict[str, dict[str, float]] = json.loads(raw)
    return {
        model: ModelPricing(
            input_per_1m=info["input_per_1m"], output_per_1m=info["output_per_1m"]
        )
        for model, info in data.items()
    }
