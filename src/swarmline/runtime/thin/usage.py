"""Native token-usage capture shared between LLM adapters and finalization.

Provider adapters (``llm_providers.py``) record the real token counts returned
by the provider for every LLM call of the current run into a
:class:`~contextvars.ContextVar` accumulator. ``finalization._build_usage``
then *consumes* the accumulated totals when building the final event's usage
payload, preferring real numbers (``usage_source: "native"``) over the
repo-wide ~4 chars/token heuristic (``usage_source: "estimated"``).

Totals accumulate across the whole turn (react iterations, finalization and
schema-repair calls included), so multi-step runs report full-turn usage, not
just the last call.

A ContextVar is used instead of threading a value through every strategy:
adapter calls and finalization always happen within the same asyncio task, and
subagent tasks get their own copy of the context, so recordings never leak
across concurrent runs.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar, Token
from typing import Any

_native_usage_totals: ContextVar[dict[str, int] | None] = ContextVar(
    "swarmline_thin_native_usage_totals",
    default=None,
)


_CACHE_KEYS = ("cache_read_tokens", "cache_write_tokens")


def _native_usage_calls() -> int:
    return (_native_usage_totals.get() or {}).get("native_calls", 0)


def _record_missing_native_usage(
    usage: Mapping[str, Any] | None, *, calls_before: int
) -> None:
    """Дополняет ContextVar данными вызова, если адаптер сам их не записал."""
    if _native_usage_calls() != calls_before or not usage:
        return
    counts = add_call_usage(None, usage)
    if counts is not None:
        record_native_usage(
            counts.get("input_tokens"),
            counts.get("output_tokens"),
            cache_read_tokens=counts.get("cache_read_tokens"),
            cache_write_tokens=counts.get("cache_write_tokens"),
        )


def record_native_usage(
    input_tokens: int | None,
    output_tokens: int | None,
    *,
    cache_read_tokens: int | None = None,
    cache_write_tokens: int | None = None,
) -> dict[str, int] | None:
    """Add real provider usage for one LLM call into the run's totals.

    Cache counters are summed across calls too (BL-98) — a cache key is present
    in the totals only once some call reported it. Returns the updated totals, or
    None (recording nothing) when the provider reported no usable counts at all.
    """
    if input_tokens is None and output_tokens is None:
        return None
    totals = _native_usage_totals.get() or {
        "input_tokens": 0,
        "output_tokens": 0,
        "native_calls": 0,
    }
    updated = {
        **totals,
        "input_tokens": totals["input_tokens"] + int(input_tokens or 0),
        "output_tokens": totals["output_tokens"] + int(output_tokens or 0),
        "native_calls": totals.get("native_calls", 0) + 1,
    }
    for key, value in zip(_CACHE_KEYS, (cache_read_tokens, cache_write_tokens)):
        if value is not None:
            updated[key] = updated.get(key, 0) + int(value)
    _native_usage_totals.set(updated)
    return updated


def consume_native_usage() -> dict[str, int] | None:
    """Return the accumulated native usage and clear it (one-shot read)."""
    totals = _native_usage_totals.get()
    if totals is not None:
        _native_usage_totals.set(None)
        consumed = {
            "input_tokens": totals["input_tokens"],
            "output_tokens": totals["output_tokens"],
        }
        consumed.update({k: totals[k] for k in _CACHE_KEYS if k in totals})
        return consumed
    return None


def reset_native_usage() -> None:
    """Clear any pending totals (drops stale data; tests and one-off callers)."""
    _native_usage_totals.set(None)


def begin_native_usage_scope() -> Token[dict[str, int] | None]:
    """Start a run's own totals; the caller's totals come back at the end.

    A run nested inside a tool of another run shares its asyncio task and so
    this ContextVar: a plain reset would wipe the parent's totals and the
    nested run's finalization would consume them (parent undercounted).
    """
    return _native_usage_totals.set(None)


def end_native_usage_scope(token: Token[dict[str, int] | None]) -> None:
    """Restore the totals the run started from (see ``begin_native_usage_scope``)."""
    try:
        _native_usage_totals.reset(token)
    except ValueError:
        # Finalized from another context (e.g. an abandoned generator closed by
        # the event loop): that context never saw the run's set, nothing to undo.
        pass


# Counters summed across the calls of one run (BL-89/BL-98). ``prompt_tokens``
# is deliberately absent: it describes ONE request (the budget anchor of the
# per-round refresher), and a sum of request sizes means nothing.
_SUMMED_USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
)


def add_call_usage(
    total: dict[str, int] | None, usage: Mapping[str, Any] | None
) -> dict[str, int] | None:
    """Add one call's usage to the run's running total (a new dict, never mutated).

    Only integer counters the provider actually reported are summed, so a cache
    key appears in the total only when some call reported it. ``total_tokens``
    is always recomputed as input + output. ``None`` usage leaves the total as is.
    """
    if not usage:
        return total
    summed = dict(total or {})
    for key in _SUMMED_USAGE_KEYS:
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            summed[key] = summed.get(key, 0) + value
    if not summed:
        return total
    summed["total_tokens"] = summed.get("input_tokens", 0) + summed.get(
        "output_tokens", 0
    )
    return summed


def _int_attr(obj: Any, name: str) -> int | None:
    value = getattr(obj, name, None) if obj is not None else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def cache_counts(usage_obj: Any) -> tuple[int | None, int | None]:
    """(cache read, cache write) from any provider's usage object, if reported.

    The attribute names are provider-specific and disjoint: Anthropic
    ``cache_read_input_tokens``/``cache_creation_input_tokens``, OpenAI-compatible
    ``prompt_tokens_details.cached_tokens``, Gemini ``cached_content_token_count``.
    """
    read = _int_attr(usage_obj, "cache_read_input_tokens")
    if read is None:
        details = getattr(usage_obj, "prompt_tokens_details", None)
        read = _int_attr(details, "cached_tokens")
    if read is None:
        read = _int_attr(usage_obj, "cached_content_token_count")
    return read, _int_attr(usage_obj, "cache_creation_input_tokens")


def native_call_usage(
    usage_obj: Any, *, input_attr: str, output_attr: str, cached_in_input: bool
) -> dict[str, int] | None:
    """Usage of ONE native tool call, normalized across providers.

    ``prompt_tokens`` is the full size of the request as the provider counted it
    (tool schemas included) — the per-round budget anchor. Providers that report
    cached tokens INSIDE the input count (OpenAI, Gemini) pass
    ``cached_in_input=True``; Anthropic reports them separately, so its prompt is
    input + cache read + cache write. ``None`` when no usable counts arrived.
    """
    input_tokens = _int_attr(usage_obj, input_attr)
    output_tokens = _int_attr(usage_obj, output_attr)
    if input_tokens is None or output_tokens is None:
        return None
    usage: dict[str, int] = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }
    cache_read, cache_write = cache_counts(usage_obj)
    if cache_read is not None:
        usage["cache_read_tokens"] = cache_read
    if cache_write is not None:
        usage["cache_write_tokens"] = cache_write
    usage["prompt_tokens"] = (
        input_tokens
        if cached_in_input
        else input_tokens + (cache_read or 0) + (cache_write or 0)
    )
    return usage


def anthropic_call_usage(usage_obj: Any) -> dict[str, int] | None:
    """Anthropic Messages API usage of one native call."""
    return native_call_usage(
        usage_obj,
        input_attr="input_tokens",
        output_attr="output_tokens",
        cached_in_input=False,
    )


def openai_call_usage(usage_obj: Any) -> dict[str, int] | None:
    """OpenAI-compatible chat completion usage of one native call."""
    return native_call_usage(
        usage_obj,
        input_attr="prompt_tokens",
        output_attr="completion_tokens",
        cached_in_input=True,
    )


def google_call_usage(usage_obj: Any) -> dict[str, int] | None:
    """Gemini ``usage_metadata`` of one native call."""
    return native_call_usage(
        usage_obj,
        input_attr="prompt_token_count",
        output_attr="candidates_token_count",
        cached_in_input=True,
    )
