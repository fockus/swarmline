"""Utility helpers extracted from ThinRuntime."""

from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from typing import Any

import structlog

from swarmline.guardrails import GuardrailContext, GuardrailResult
from swarmline.observability.redaction import redact_secrets
from swarmline.runtime.cost import CostTracker
from swarmline.runtime.thin.llm_client import default_llm_call
from swarmline.runtime.types import (
    EventJournal,
    Message,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
)

_logger = structlog.get_logger(component="runtime_event_tap")


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


_CAPTURE_CONTENT_KEY = "capture_llm_content"
_CAPTURE_MAX_CHARS = 4000


def _captured_messages(
    messages: list[dict[str, str]], system_prompt: str
) -> list[dict[str, str]]:
    """Redacted, truncated copy of the LLM input for observability events."""
    captured = [
        {
            "role": "system",
            "content": redact_secrets(system_prompt)[:_CAPTURE_MAX_CHARS],
        }
    ]
    for msg in messages:
        captured.append(
            {
                "role": msg.get("role", ""),
                "content": redact_secrets(msg.get("content", ""))[:_CAPTURE_MAX_CHARS],
            }
        )
    return captured


def wrap_with_event_bus(
    llm_call: Callable[..., Any],
    fallback_config: RuntimeConfig,
) -> Callable[..., Any]:
    """Instrument LLM calls with llm_call_start/llm_call_end events.

    Events carry ``model``, a per-call ``correlation_id`` (pairs start/end
    under concurrency), and ``duration_ms``. When
    ``config.extra["capture_llm_content"]`` is truthy, the start event also
    carries redacted, truncated ``messages`` and the end event a redacted
    ``response`` (non-streaming results only) — opt-in, for LLM
    observability exporters (Langfuse, LangSmith).
    """
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
        correlation_id = uuid.uuid4().hex[:12]
        capture = bool((effective.extra or {}).get(_CAPTURE_CONTENT_KEY))
        start_data: dict[str, Any] = {
            "model": effective.model,
            "correlation_id": correlation_id,
        }
        if capture:
            start_data["messages"] = _captured_messages(messages, system_prompt)
        started = time.monotonic()
        await bus.emit("llm_call_start", start_data)
        try:
            result = await llm_call(messages, system_prompt, config=config, **kwargs)
        except Exception as exc:
            await bus.emit(
                "llm_call_end",
                {
                    "model": effective.model,
                    "correlation_id": correlation_id,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "error": True,
                    "error_message": redact_secrets(str(exc)),
                },
            )
            raise
        end_data: dict[str, Any] = {
            "model": effective.model,
            "correlation_id": correlation_id,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
        if capture and isinstance(result, str):
            end_data["response"] = redact_secrets(result)[:_CAPTURE_MAX_CHARS]
        await bus.emit("llm_call_end", end_data)
        return result

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


async def journal_tap(journal: EventJournal, event: RuntimeEvent) -> None:
    """Append a yielded RuntimeEvent into the configured EventJournal (REQ-007).

    Side-channel tap: called once per event that ``ThinRuntime.run()`` yields
    downstream, never filtering or delaying the live stream. ``event.type`` /
    ``event.data`` map directly onto ``EventJournal.append`` -- no ``asdict``,
    which would double-nest the payload (RuntimeEvent is already ``{type, data}``).

    REQ-015: append failures are caught and logged here, not propagated -- a
    misbehaving or unavailable journal must never interrupt the agent run.
    """
    try:
        await journal.append(event.type, event.data)
    except Exception as exc:  # noqa: BLE001 -- tap failures must never break the run
        _logger.warning(
            "runtime_event_tap.append_failed",
            event_type=event.type,
            error=str(exc),
        )


class _JournalTappingAsyncIterator:
    """Async-iterator proxy that taps every yielded RuntimeEvent into a journal.

    Used ONLY when ``event_journal`` is configured (REQ-007) -- the None-journal
    path never constructs this proxy, returning the wrapped generator unwrapped
    instead, so it stays out of the byte-identical default path entirely (REQ-014).

    Fully forwards ``asend``/``athrow``/``aclose`` to the wrapped async
    generator so cancellation/cleanup semantics (GeneratorExit propagation,
    exception injection at the real suspension point, prompt ``finally``
    execution on ``aclose()``) are unchanged for callers -- only actual
    yielded/sent/thrown-back values are tapped. A broken journal can never
    interrupt iteration: ``journal_tap`` already catches and logs append
    failures (REQ-015).
    """

    def __init__(
        self,
        inner: AsyncGenerator[RuntimeEvent, None],
        journal: EventJournal,
    ) -> None:
        self._inner = inner
        self._journal = journal

    def __aiter__(self) -> _JournalTappingAsyncIterator:
        return self

    async def __anext__(self) -> RuntimeEvent:
        event = await self._inner.__anext__()
        await journal_tap(self._journal, event)
        return event

    async def asend(self, value: Any) -> RuntimeEvent:
        """Forward a sent value into the wrapped generator, tapping its reply."""
        event = await self._inner.asend(value)
        await journal_tap(self._journal, event)
        return event

    async def athrow(self, *args: Any, **kwargs: Any) -> RuntimeEvent:
        """Inject the exception into the wrapped generator at its suspension point."""
        event = await self._inner.athrow(*args, **kwargs)
        await journal_tap(self._journal, event)
        return event

    async def aclose(self) -> None:
        """Close the wrapped generator -- runs its ``finally`` blocks promptly."""
        await self._inner.aclose()
