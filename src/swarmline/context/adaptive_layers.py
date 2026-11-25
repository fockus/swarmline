"""Adaptive-budget helpers for ``DefaultContextBuilder``'s two-pass allocation.

Part of the ``adaptive-budget`` spec, Task 4 (REQ-007, REQ-008). Pure,
zero-IO functions extracted out of ``builder.py`` purely to respect the
file-size ceiling (<400 lines) without touching or restructuring the static
(``adaptive=None``) code path in the builder itself.
"""

from __future__ import annotations

from swarmline.context.budget import (
    LAYER_TO_CATEGORY,
    estimate_tokens,
    truncate_to_budget,
)


def derive_layer_caps(
    allocated: dict[str, int], present_layers: dict[str, bool]
) -> dict[str, int]:
    """Split each category's allocated tokens across the layers of that
    category that are actually present in this build.

    "Present" is determined by the caller from the raw call arguments (e.g.
    ``bool(goal_text)``), not from budget-dependent rendering decisions -
    avoids a chicken-and-egg dependency on the caps this function computes.

    When several layers share a category (e.g. ``memory_bank``,
    ``memory_recall`` and ``user_profile`` all map to ``"memory"``), the
    category's tokens are split EQUALLY among only the present layers of that
    category; any floor-division remainder is handed out one token at a time,
    in the stable order the layers appear in ``LAYER_TO_CATEGORY``, so the caps
    for a category always sum to EXACTLY that category's allocation (a naive
    floor split, e.g. 1000 // 3 == 333, would silently lose tokens: 999 !=
    1000, distorting saturation feedback on tight budgets). A layer absent
    this turn does not consume a share. A layer whose category has no present
    members at all gets no entry in the returned dict (nothing to divide).
    """
    layers_by_category: dict[str, list[str]] = {}
    for layer_key, category in LAYER_TO_CATEGORY.items():
        if present_layers.get(layer_key):
            layers_by_category.setdefault(category, []).append(layer_key)

    caps: dict[str, int] = {}
    for category, layer_keys in layers_by_category.items():
        total = allocated.get(category, 0)
        share, remainder = divmod(total, len(layer_keys))
        for index, layer_key in enumerate(layer_keys):
            caps[layer_key] = share + (1 if index < remainder else 0)
    return caps


def compute_present_layers(
    *,
    role_text: str,
    memory_bank_prompt: str | None,
    goal_text: str | None,
    phase_text: str | None,
    skills: object | None,
    last_messages: object | None,
    recall_facts: object | None,
    user_profile_facts: object | None,
    summary: str | None,
    available_files: str | None = None,
) -> dict[str, bool]:
    """Which builder layers this build call will attempt to render.

    Derived from the raw ``build()`` call arguments (truthiness only), not
    from budget-dependent rendering decisions - avoids a chicken-and-egg
    dependency on the caps ``derive_layer_caps`` computes from this. Feeds
    ``derive_layer_caps`` so a shared category's tokens split only among the
    layers actually present this turn. ``guardrails`` is always present.
    """
    return {
        "guardrails": True,
        "role": bool(role_text),
        "memory_bank": bool(memory_bank_prompt),
        "goal": bool(goal_text),
        "phase": bool(phase_text),
        "tool_hints": bool(skills),
        "last_messages": bool(last_messages),
        "memory_recall": bool(recall_facts),
        "user_profile": bool(user_profile_facts),
        "available_files": bool(available_files),
        "summary": bool(summary),
    }


def apply_optional_cap(pack: str, cap: int | None) -> tuple[str, bool]:
    """Truncate ``pack`` to ``cap`` tokens if a cap is set and exceeded.

    ``cap=None`` means "no cap" - the static-path passthrough for layers (like
    ``phase``) that have no static per-layer ceiling of their own. Returns
    ``(possibly_truncated_pack, was_truncated)`` so the caller can append to
    its own ``truncated`` list. Centralizes the truncate-if-over-cap idiom
    used at every builder cap site (Task 4, Defect 3 fix).
    """
    if cap is not None and estimate_tokens(pack) > cap:
        return truncate_to_budget(pack, cap), True
    return pack, False


def category_actuals(layer_tokens: dict[str, int]) -> dict[str, int]:
    """Group actual per-layer token counts by category, summing within it.

    Feeds ``SaturationCalculator.calculate(actual, allocated)`` (REQ-007).
    """
    totals: dict[str, int] = {}
    for layer_key, tokens in layer_tokens.items():
        category = LAYER_TO_CATEGORY.get(layer_key)
        if category is None:
            continue
        totals[category] = totals.get(category, 0) + tokens
    return totals
