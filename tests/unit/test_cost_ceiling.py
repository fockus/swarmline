"""Unit tests for swarmline.runtime.cost_ceiling — fail-closed cost-ceiling layer.

Covers REQ-OSS-010 (30+ model pricing table + fail-closed) and the precheck
decision logic (REQ-OSS-011). The ceiling layer is additive and generic: keyed by
a plain ``str`` (no tenant/workspace/AccessContext), audit via a plain-dict callback.
"""

from __future__ import annotations

import pytest


class TestComputeCostCents:
    """compute_cost_cents — CEILING arithmetic, normalization, graceful unknown."""

    def test_known_model_ceil_arithmetic_exact(self) -> None:
        from swarmline.runtime.cost_ceiling import compute_cost_cents

        # gpt-4o: input 250¢/M, output 1000¢/M.
        # 1_000_000 input → 250¢; 500_000 output → 500¢; total 750¢.
        assert compute_cost_cents("openai", "gpt-4o", 1_000_000, 500_000) == 750

    def test_one_token_positive_rate_costs_at_least_one_cent(self) -> None:
        from swarmline.runtime.cost_ceiling import compute_cost_cents

        # 1 input token at 250¢/M = 0.00025¢ → math.ceil → 1¢ (never rounds to 0).
        assert compute_cost_cents("openai", "gpt-4o", 1, 0) == 1

    def test_zero_tokens_known_model_costs_zero(self) -> None:
        from swarmline.runtime.cost_ceiling import compute_cost_cents

        assert compute_cost_cents("openai", "gpt-4o", 0, 0) == 0

    def test_unknown_model_returns_none(self) -> None:
        from swarmline.runtime.cost_ceiling import compute_cost_cents

        assert compute_cost_cents("nope", "nonexistent-model-xyz", 100, 50) is None

    def test_slash_prefixed_model_resolves(self) -> None:
        from swarmline.runtime.cost_ceiling import compute_cost_cents

        # 'anthropic/claude-opus-4-7' → strip slash prefix → 'claude-opus-4-7'.
        assert compute_cost_cents("anthropic", "anthropic/claude-opus-4-7", 1, 0) == 1

    def test_dot_version_normalizes(self) -> None:
        from swarmline.runtime.cost_ceiling import compute_cost_cents

        # 'claude-opus-4.7' → 'claude-opus-4-7' via dot→dash version normalization.
        assert compute_cost_cents("anthropic", "claude-opus-4.7", 1, 0) is not None

    def test_bedrock_cross_region_prefix_resolves(self) -> None:
        from swarmline.runtime.cost_ceiling import compute_cost_cents

        # 'us.anthropic.claude-opus-4-6' → strip region prefix → 'anthropic.claude-opus-4-6'.
        assert (
            compute_cost_cents("bedrock", "us.anthropic.claude-opus-4-6", 1, 0)
            is not None
        )

    def test_pricing_table_covers_at_least_30_models(self) -> None:
        from swarmline.runtime.cost_ceiling import _KNOWN_PRICING

        assert len(_KNOWN_PRICING) >= 30


class TestCostCeilingPrecheck:
    """CostCeiling.precheck — fail-closed enforcement, generic keys, plain-dict audit."""

    def _ceiling(self, remaining_cents: int, **kwargs: object):
        from swarmline.runtime.cost_ceiling import CostCeiling

        async def _get(_key: str) -> int:
            return remaining_cents

        return CostCeiling(get_remaining_cents=_get, **kwargs)  # type: ignore[arg-type]

    async def test_zero_token_call_allowed_even_with_zero_budget(self) -> None:
        ceiling = self._ceiling(0)
        # Zero-token administrative calls cost nothing → never blocked, never unknown-checked.
        await ceiling.precheck(
            key="k",
            model="gpt-4o",
            provider="openai",
            estimated_input_tokens=0,
            estimated_output_tokens=0,
        )

    async def test_within_budget_allowed(self) -> None:
        ceiling = self._ceiling(10_000)
        await ceiling.precheck(
            key="k",
            model="gpt-4o",
            provider="openai",
            estimated_input_tokens=1,
            estimated_output_tokens=1,
        )  # must not raise

    async def test_unknown_model_fails_closed_by_default(self) -> None:
        from swarmline.runtime.cost_ceiling import UnknownModelError

        ceiling = self._ceiling(999_999)  # plenty of budget — still denied for unknown
        with pytest.raises(UnknownModelError) as ei:
            await ceiling.precheck(
                key="k",
                model="mystery-model",
                provider="mystery-provider",
                estimated_input_tokens=1,
                estimated_output_tokens=1,
            )
        assert ei.value.provider == "mystery-provider"
        assert ei.value.model == "mystery-model"

    async def test_unknown_model_allowed_when_fail_closed_false(self) -> None:
        ceiling = self._ceiling(0, fail_closed=False)
        # fail_closed=False → unknown model treated as zero-ceiling → allowed even at 0 budget.
        await ceiling.precheck(
            key="k",
            model="mystery-model",
            provider="mystery-provider",
            estimated_input_tokens=100,
            estimated_output_tokens=50,
        )  # must not raise

    async def test_budget_exceeded_raises_with_generic_fields_no_tenant(self) -> None:
        from swarmline.runtime.cost_ceiling import BudgetExceededError

        ceiling = self._ceiling(5)  # 5¢ remaining
        with pytest.raises(BudgetExceededError) as ei:
            await ceiling.precheck(
                key="acct-7",
                model="claude-opus-4-7",
                provider="anthropic",
                estimated_input_tokens=1_000_000,  # 500¢ ceiling ≫ 5¢
                estimated_output_tokens=0,
            )
        err = ei.value
        assert err.key == "acct-7"
        assert err.projected_cents > err.remaining_cents
        assert err.remaining_cents == 5
        assert err.model == "claude-opus-4-7"
        # No product coupling: the generic error must NOT carry a tenant_id.
        assert not hasattr(err, "tenant_id")

    async def test_on_decision_callback_fires_for_allow_and_block_with_plain_dict(
        self,
    ) -> None:
        from swarmline.runtime.cost_ceiling import BudgetExceededError, CostCeiling

        events: list[dict] = []

        async def on_decision(d: dict) -> None:
            events.append(d)

        async def _get_big(_key: str) -> int:
            return 10_000

        allow_ceiling = CostCeiling(
            get_remaining_cents=_get_big, on_decision=on_decision
        )
        await allow_ceiling.precheck(
            key="acct-1",
            model="gpt-4o",
            provider="openai",
            estimated_input_tokens=1,
            estimated_output_tokens=0,
        )
        assert events[-1].__class__ is dict
        assert events[-1]["decision"] == "allowed"
        assert events[-1]["key"] == "acct-1"
        assert "tenant_id" not in events[-1]

        async def _get_small(_key: str) -> int:
            return 5

        block_ceiling = CostCeiling(
            get_remaining_cents=_get_small, on_decision=on_decision
        )
        with pytest.raises(BudgetExceededError):
            await block_ceiling.precheck(
                key="acct-2",
                model="claude-opus-4-7",
                provider="anthropic",
                estimated_input_tokens=1_000_000,
                estimated_output_tokens=0,
            )
        assert events[-1]["decision"] == "blocked"
        assert events[-1]["projected_cents"] > events[-1]["remaining_cents"]
        assert "tenant_id" not in events[-1]


class TestDefaultPathUntouched:
    """Regression: the existing best-effort CostTracker/load_pricing path is byte-identical."""

    def test_load_pricing_still_returns_six_known_models(self) -> None:
        from swarmline.runtime.cost import load_pricing

        pricing = load_pricing()
        assert len(pricing) == 6
        assert "_default" in pricing
        assert "gpt-4o" in pricing
        assert pricing["gpt-4o"].input_per_1m == 2.5


class TestDeepseekV41FlashPricing:
    """DeepSeek V4.1 Flash via OpenRouter: $0.035/M in, $0.29/M out -> ceiling (4, 29) cents/M."""

    @pytest.mark.parametrize(
        "model",
        [
            "deepseek/deepseek-v4.1-flash",
            "deepseek-v4.1-flash",
            "deepseek-v4-1-flash",
            "DeepSeek/DeepSeek-V4.1-Flash",
        ],
    )
    def test_compute_cost_deepseek_v41_flash_one_million_each_is_33_cents(
        self, model: str
    ) -> None:
        from swarmline.runtime.cost_ceiling import compute_cost_cents

        assert compute_cost_cents("deepseek", model, 1_000_000, 1_000_000) == 33

    def test_compute_cost_deepseek_v41_flash_one_token_costs_one_cent(self) -> None:
        from swarmline.runtime.cost_ceiling import compute_cost_cents

        assert compute_cost_cents("deepseek", "deepseek/deepseek-v4.1-flash", 1, 0) == 1

    def test_compute_cost_deepseek_v41_flash_under_wrong_provider_is_unknown(
        self,
    ) -> None:
        from swarmline.runtime.cost_ceiling import compute_cost_cents

        # The canary failure mode: an OpenRouter model priced under "anthropic" stays unknown.
        assert (
            compute_cost_cents("anthropic", "deepseek/deepseek-v4.1-flash", 1000, 500)
            is None
        )

    async def test_precheck_deepseek_v41_flash_fail_closed_passes_within_budget(
        self,
    ) -> None:
        from swarmline.runtime.cost_ceiling import CostCeiling

        async def _remaining(_key: str) -> int:
            return 1_000

        ceiling = CostCeiling(get_remaining_cents=_remaining, fail_closed=True)
        await ceiling.precheck(
            key="tenant-1",
            provider="deepseek",
            model="deepseek/deepseek-v4.1-flash",
            estimated_input_tokens=1000,
            estimated_output_tokens=500,
        )

    async def test_precheck_unknown_deepseek_variant_fail_closed_raises(self) -> None:
        from swarmline.runtime.cost_ceiling import CostCeiling, UnknownModelError

        async def _remaining(_key: str) -> int:
            return 1_000

        ceiling = CostCeiling(get_remaining_cents=_remaining, fail_closed=True)
        with pytest.raises(UnknownModelError):
            await ceiling.precheck(
                key="tenant-1",
                provider="deepseek",
                model="deepseek/deepseek-v9-imaginary",
                estimated_input_tokens=1000,
                estimated_output_tokens=500,
            )
