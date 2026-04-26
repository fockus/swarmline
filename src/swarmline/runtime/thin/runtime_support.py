"""Utility helpers extracted from ThinRuntime."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator, Callable
from typing import Any

from swarmline.guardrails import GuardrailContext, GuardrailResult
from swarmline.runtime.cost import CostTracker
from swarmline.runtime.thin.llm_client import default_llm_call
from swarmline.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
)


def auto_wrap_retriever(config: RuntimeConfig) -> None:
    """Auto-wrap config.retriever into input_filters if not already present."""
    if config.retriever is None:
        return

    from swarmline.rag import RagInputFilter

    for current_filter in config.input_filters:
        if isinstance(current_filter, RagInputFilter):
            return

    config.input_filters.insert(0, RagInputFilter(retriever=config.retriever))


def wrap_user_llm_call(user_fn: Callable[..., Any]) -> Callable[..., Any]:
    """Adapt legacy user-provided llm_call to ThinRuntime's config-aware signature."""
    signature = inspect.signature(user_fn)
    params = signature.parameters
    accepts_config = "config" in params or any(
        param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()
    )
    if accepts_config:
        return user_fn

    async def _adapted(
        messages: list[dict[str, str]],
        system_prompt: str,
        *,
        config: RuntimeConfig | None = None,  # noqa: ARG001
        **kwargs: Any,
    ) -> Any:
        return await user_fn(messages, system_prompt, **kwargs)

    return _adapted


def make_default_llm_call(
    fallback_config: RuntimeConfig,
    llm_impl: Callable[..., Any] = default_llm_call,
) -> Callable[..., Any]:
    """Create the default LLM call wrapper with per-call config overrides."""

    async def _call(
        messages: list[dict[str, str]],
        system_prompt: str,
        *,
        config: RuntimeConfig | None = None,
        **kwargs: Any,
    ) -> str | AsyncIterator[str]:
        effective = config or fallback_config
        return await llm_impl(effective, messages, system_prompt, **kwargs)

    return _call


def wrap_with_event_bus(
    llm_call: Callable[..., Any],
    fallback_config: RuntimeConfig,
) -> Callable[..., Any]:
    """Instrument LLM calls with llm_call_start/llm_call_end events."""
    bus = fallback_config.event_bus
    if bus is None:
        raise ValueError("event_bus must not be None")

    async def _instrumented_call(
        messages: list[dict[str, str]],
        system_prompt: str,
        *,
        config: RuntimeConfig | None = None,
        **kwargs: Any,
    ) -> str | AsyncIterator[str]:
        effective = config or fallback_config
        await bus.emit("llm_call_start", {"model": effective.model})
        try:
            result = await llm_call(messages, system_prompt, config=config, **kwargs)
            await bus.emit("llm_call_end", {"model": effective.model})
            return result
        except Exception:
            await bus.emit("llm_call_end", {"model": effective.model, "error": True})
            raise

    return _instrumented_call


def extract_last_user_text(messages: list[Message]) -> str:
    """Extract last user text."""
    for msg in reversed(messages):
        if msg.role == "user" and msg.content:
            return msg.content
    return ""


async def run_guardrails(
    guardrails: list[Any],
    text: str,
    config: RuntimeConfig,
) -> RuntimeEvent | None:
    """Run guardrails in parallel and map the first failure to RuntimeEvent.error."""
    ctx = GuardrailContext(
        model=config.model,
        session_id=config.extra.get("session_id") if config.extra else None,
    )
    results: list[GuardrailResult] = await asyncio.gather(
        *[guardrail.check(ctx, text) for guardrail in guardrails]
    )
    for result in results:
        if not result.passed:
            return RuntimeEvent.error(
                RuntimeErrorData(
                    kind="guardrail_tripwire",
                    message=result.reason or "Guardrail check failed",
                    recoverable=not result.tripwire,
                )
            )
    return None


def cancelled_event(token: Any | None) -> RuntimeEvent | None:
    """Map a cancelled token to the canonical RuntimeEvent.error."""
    if token is None or not token.is_cancelled:
        return None
    return RuntimeEvent.error(
        RuntimeErrorData(
            kind="cancelled",
            message="Operation cancelled",
            recoverable=False,
        )
    )


def budget_exceeded_event(tracker: CostTracker, *, prefix: str) -> RuntimeEvent:
    """Build a budget-exceeded terminal event."""
    return RuntimeEvent.error(
        RuntimeErrorData(
            kind="budget_exceeded",
            message=(
                f"{prefix}: "
                f"${tracker.total_cost_usd:.4f} spent, "
                f"{tracker.total_tokens} tokens used"
            ),
            recoverable=False,
        )
    )
