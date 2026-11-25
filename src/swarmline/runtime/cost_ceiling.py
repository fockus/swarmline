# Attribution: adapted from hermes-agent (MIT)
# Upstream file: agent/usage_pricing.py
# Copyright: (c) Nous Research and contributors
# Changes: stripped to a dependency-free (provider, model)→cents corpus; added
#          Bedrock cross-region prefix + dot-version normalization; recast as a
#          fail-closed CEILING enforcement layer (CostCeiling.precheck) with a
#          generic str key, an injected budget reader, and a plain-dict audit
#          callback — no tenant/workspace/AccessContext/AuditEvent coupling.
"""Fail-closed cost-ceiling layer — worst-case known-pricing budget guard.

ADDITIVE layer, distinct from the best-effort USD ``CostTracker`` in
``swarmline.runtime.cost``. Fail-closed contract: integer US cents, keyed by
``(provider, model)``, CEILING division so even 1 token at a positive rate costs
at least 1¢. The pricing corpus is a Python constant here, not merged into
``pricing.json`` (which stays USD-float/model-keyed, read verbatim by
``load_pricing()``) — separate is the lower-risk option: zero schema clash, default
path byte-identical. No product coupling (REQ-OSS-051): plain ``str`` identifiers,
injected budget read, optional dict audit callback.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

__all__ = [
    "BudgetExceededError",
    "CostCeiling",
    "UnknownModelError",
    "compute_cost_cents",
]


class BudgetExceededError(Exception):
    """Projected ceiling cost exceeds the remaining budget for a generic key.

    Carries only neutral fields — no tenant/workspace/product types (REQ-OSS-051).
    """

    def __init__(
        self, *, key: str, projected_cents: int, remaining_cents: int, model: str
    ) -> None:
        super().__init__(
            f"Budget exceeded for key {key!r}: projected {projected_cents}¢ > "
            f"remaining {remaining_cents}¢ (model={model})"
        )
        self.key = key
        self.projected_cents = projected_cents
        self.remaining_cents = remaining_cents
        self.model = model


class UnknownModelError(Exception):
    """No pricing ceiling is known for the given provider/model pair.

    Fail-closed: rather than guess a ceiling and risk under-blocking, the call is
    denied so an operator must add the model to the pricing corpus or disable
    fail-closed enforcement explicitly.
    """

    def __init__(self, provider: str, model: str) -> None:
        super().__init__(
            f"No known pricing ceiling for provider={provider!r} model={model!r}. "
            "Add it to the pricing corpus or set fail_closed=False to allow unknown models."
        )
        self.provider = provider
        self.model = model


# ---------------------------------------------------------------------------
# Known-pricing ceiling corpus — (provider, model_normalized) → (input¢/M, output¢/M)
# Adapted from hermes usage_pricing official-docs pricing (MIT © Nous Research).
# ---------------------------------------------------------------------------

_KNOWN_PRICING: dict[tuple[str, str], tuple[int, int]] = {
    # Anthropic Claude 4.x family
    ("anthropic", "claude-opus-4-8"): (500, 2500),
    ("anthropic", "claude-opus-4-8-fast"): (1000, 5000),
    ("anthropic", "claude-opus-4-7"): (500, 2500),
    ("anthropic", "claude-opus-4-7-20250507"): (500, 2500),
    ("anthropic", "claude-opus-4-6"): (500, 2500),
    ("anthropic", "claude-opus-4-6-20250414"): (500, 2500),
    ("anthropic", "claude-opus-4-5"): (500, 2500),
    ("anthropic", "claude-sonnet-4-6"): (300, 1500),
    ("anthropic", "claude-sonnet-4-6-20250414"): (300, 1500),
    ("anthropic", "claude-sonnet-4-5"): (300, 1500),
    ("anthropic", "claude-haiku-4-5"): (100, 500),
    # Anthropic Claude 4 / 4.1
    ("anthropic", "claude-opus-4-20250514"): (1500, 7500),
    ("anthropic", "claude-sonnet-4-20250514"): (300, 1500),
    # Anthropic older
    ("anthropic", "claude-3-5-sonnet-20241022"): (300, 1500),
    ("anthropic", "claude-3-5-haiku-20241022"): (80, 400),
    ("anthropic", "claude-3-opus-20240229"): (1500, 7500),
    ("anthropic", "claude-3-haiku-20240307"): (25, 125),
    # OpenAI
    ("openai", "gpt-4o"): (250, 1000),
    ("openai", "gpt-4o-mini"): (15, 60),
    ("openai", "gpt-4.1"): (200, 800),
    ("openai", "gpt-4.1-mini"): (40, 160),
    ("openai", "gpt-4.1-nano"): (10, 40),
    ("openai", "o3"): (1000, 4000),
    ("openai", "o3-mini"): (110, 440),
    # Google Gemini
    ("google", "gemini-2.5-pro"): (125, 1000),
    ("google", "gemini-2.5-flash"): (15, 60),
    ("google", "gemini-2.0-flash"): (10, 40),
    # DeepSeek
    ("deepseek", "deepseek-chat"): (14, 28),
    ("deepseek", "deepseek-reasoner"): (55, 219),
    ("deepseek", "deepseek-v4-pro"): (174, 348),
    # OpenRouter list price $0.035/M in, $0.29/M out (2026-09); ceiling-rounded to cents/M.
    ("deepseek", "deepseek-v4-1-flash"): (4, 29),
    # AWS Bedrock (on-demand, carrier rates)
    ("bedrock", "anthropic.claude-opus-4-6"): (1500, 7500),
    ("bedrock", "anthropic.claude-sonnet-4-6"): (300, 1500),
    ("bedrock", "anthropic.claude-sonnet-4-5"): (300, 1500),
    ("bedrock", "anthropic.claude-haiku-4-5"): (80, 400),
    ("bedrock", "amazon.nova-pro"): (80, 320),
    ("bedrock", "amazon.nova-lite"): (6, 24),
    ("bedrock", "amazon.nova-micro"): (4, 14),
    # MiniMax
    ("minimax", "minimax-m2.7"): (30, 120),
    ("minimax-cn", "minimax-m2.7"): (30, 120),
}

# Bedrock cross-region inference profile prefixes (region scope before model id).
_BEDROCK_REGION_PREFIXES = ("us.", "global.", "eu.", "ap.", "jp.")


def _normalize_model_name(provider: str, model: str) -> str:
    """Strip provider/region prefixes and normalize version notation.

    Handles: slash-prefixed provider ('anthropic/claude-opus-4-7' → 'claude-opus-4-7'),
    dot version numbers ('opus-4.7' → 'opus-4-7'), and Bedrock cross-region prefixes
    ('us.anthropic.claude-opus-4-6' → 'anthropic.claude-opus-4-6').
    """
    name = model.lower().strip()

    if "/" in name:
        name = name.split("/", 1)[1]

    if provider == "bedrock":
        for prefix in _BEDROCK_REGION_PREFIXES:
            if name.startswith(prefix):
                name = name[len(prefix) :]
                break

    name = re.sub(r"(\d+)\.(\d+)", r"\1-\2", name)
    return name


def _lookup_ceiling(provider: str, model: str) -> tuple[int, int] | None:
    """Return (input¢/M, output¢/M) or None if unknown (caller must fail closed)."""
    p = provider.lower().strip()
    m = model.lower().strip()

    entry = _KNOWN_PRICING.get((p, m))
    if entry:
        return entry

    m_norm = _normalize_model_name(p, m)
    if m_norm != m:
        entry = _KNOWN_PRICING.get((p, m_norm))
        if entry:
            return entry

    return None


def _projected_cost_cents_ceiling(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> tuple[int, bool]:
    """Worst-case ceiling cost in cents via CEILING division.

    Returns (cost_cents, known) where known=False means the pair was not found —
    the caller decides whether to fail closed. math.ceil ensures even 1 token at a
    positive rate costs at least 1¢.
    """
    ceiling = _lookup_ceiling(provider, model)
    if ceiling is None:
        return 0, False

    input_cents_per_m, output_cents_per_m = ceiling
    input_cost = (
        math.ceil(input_tokens * input_cents_per_m / 1_000_000)
        if input_tokens > 0
        else 0
    )
    output_cost = (
        math.ceil(output_tokens * output_cents_per_m / 1_000_000)
        if output_tokens > 0
        else 0
    )
    return input_cost + output_cost, True


def compute_cost_cents(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> int | None:
    """Actual cost in cents (CEILING) for a completed call; None when unknown.

    Unlike precheck this does NOT raise — callers gracefully skip recording unknowns.
    """
    cost, known = _projected_cost_cents_ceiling(
        provider, model, input_tokens, output_tokens
    )
    return cost if known else None


class CostCeiling:
    """Hard-enforces a worst-case known-pricing budget ceiling BEFORE a call.

    Generic and product-free (REQ-OSS-051):
    - ``get_remaining_cents`` — async reader of remaining budget in cents for a key.
    - ``on_decision`` — optional async callback invoked with a plain dict for every
      allow/block decision (NOT for early zero-token returns or unknown fail-closed).
    - ``fail_closed`` — when True (default) an unknown model raises UnknownModelError;
      when False the unknown model is treated as a zero ceiling (allowed). Disabling
      fail-closed risks under-blocking newly-added models — opt out deliberately.
    """

    def __init__(
        self,
        *,
        get_remaining_cents: Callable[[str], Awaitable[int]],
        on_decision: Callable[[dict], Awaitable[None]] | None = None,
        fail_closed: bool = True,
    ) -> None:
        self._get_remaining = get_remaining_cents
        self._on_decision = on_decision
        self._fail_closed = fail_closed

    async def precheck(
        self,
        *,
        key: str,
        model: str,
        provider: str,
        estimated_input_tokens: int,
        estimated_output_tokens: int,
    ) -> None:
        """Enforce the budget ceiling BEFORE a call.

        Raises:
          UnknownModelError — provider/model not in the corpus and fail_closed=True.
          BudgetExceededError — projected ceiling cost > remaining budget.
        """
        if estimated_input_tokens == 0 and estimated_output_tokens == 0:
            return  # zero-token calls cost nothing — always allowed

        projected, known = _projected_cost_cents_ceiling(
            provider, model, estimated_input_tokens, estimated_output_tokens
        )

        if not known:
            if self._fail_closed:
                raise UnknownModelError(provider=provider, model=model)
            projected = 0  # treat unknown as zero ceiling → allowed

        remaining = await self._get_remaining(key)
        blocked = projected > remaining

        logger.debug(
            "CostCeiling.precheck key=%s model=%s/%s projected=%d¢ remaining=%d¢ blocked=%s",
            key,
            provider,
            model,
            projected,
            remaining,
            blocked,
        )

        if self._on_decision is not None:
            await self._on_decision(
                {
                    "key": key,
                    "model": model,
                    "provider": provider,
                    "projected_cents": projected,
                    "remaining_cents": remaining,
                    "decision": "blocked" if blocked else "allowed",
                }
            )

        if blocked:
            raise BudgetExceededError(
                key=key,
                projected_cents=projected,
                remaining_cents=remaining,
                model=model,
            )
