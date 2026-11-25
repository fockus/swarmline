"""Shared finalization helpers for ThinRuntime strategies."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from swarmline.context.budget import estimate_image_tokens, estimate_tokens
from swarmline.runtime.structured_output import (
    empty_result_error,
    try_resolve_structured_output,
)
from swarmline.runtime.thin.errors import ThinLlmError
from swarmline.runtime.thin.helpers import _build_metrics
from swarmline.runtime.thin.parsers import parse_envelope
from swarmline.runtime.thin.usage import consume_native_usage
from swarmline.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
)
from swarmline.verification.gate import _apply_verification_gate

_RETRY_INSTRUCTION = (
    "Previous response was not valid JSON matching the schema. "
    "Error: {error}. Please respond with valid JSON only."
)

_EMPTY_RETRY_INSTRUCTION = (
    "Previous response was valid JSON matching the schema but reported no usable result "
    "(it was semantically empty). Error: {error}. Please provide a complete response with "
    "actual content."
)

CheckpointFn = Callable[[], Awaitable[RuntimeEvent | None]]


def _resolve_checked(
    text: str,
    config: RuntimeConfig,
) -> tuple[Any, str | None, bool]:
    """Resolve structured output, then flag a schema-valid-but-empty result as retryable.

    Returns ``(output, error, is_empty)``:

    * Parse/validation failure → ``(None, error, False)`` (unchanged legacy behaviour).
    * Schema-valid but the output opts into emptiness and reports itself empty →
      ``(output, empty_message, True)`` so the caller routes it through the existing retry loop.
    * Otherwise → ``(output, None, False)``.
    """
    output, error = try_resolve_structured_output(
        text,
        config.output_format,
        config.output_type,
    )
    if error is not None:
        return output, error, False
    empty_msg = empty_result_error(output)
    if empty_msg is not None:
        return output, empty_msg, True
    return output, None, False


def _estimate_tokens_for_prompt(
    lm_messages: list[dict[str, str]],
    prompt: str,
) -> int:
    """Approximate input tokens for the current LLM call."""
    serialized_messages = "\n".join(
        f"{msg.get('role', '')}:{msg.get('name', '')}:{msg.get('content', '')}"
        for msg in lm_messages
    )
    images = sum(
        estimate_image_tokens(msg.get("content_blocks")) for msg in lm_messages
    )
    return estimate_tokens(f"{prompt}\n{serialized_messages}") + images


_CACHE_USAGE_KEYS = ("cache_read_tokens", "cache_write_tokens", "cache_creation_tokens")


def _build_usage(
    lm_messages: list[dict[str, str]],
    prompt: str,
    text: str,
    *,
    provider_usage: dict[str, Any] | None = None,
    attempts: int = 1,
) -> dict[str, Any]:
    """Build the usage payload for a finished turn.

    Real numbers are preferred over the repo-wide ~4 chars/token heuristic, from two
    complementary capture paths (merge of Этап 26 explicit threading + I-098a native
    accumulator):

    1. ``consume_native_usage()`` — full-turn totals the provider adapters accumulated
       into the run's ContextVar (react iterations, finalization and schema-repair
       calls included). Preferred when present: it covers every adapter-backed call
       of the turn, not just the final one.
    2. ``provider_usage`` — usage the caller threaded for the ONE logical call that
       produced ``text`` (``run_buffered_llm_call``). Fallback when the accumulator
       is empty (e.g. a user-supplied ``llm_call`` the adapters never saw). Its
       cache token counts (``_CACHE_USAGE_KEYS``) are attached only when the
       accumulator carries none; the accumulator's cache counts are summed over
       every call of the turn (BL-98).

    Either real source is marked ``"estimated": False`` / ``"usage_source": "native"``;
    the heuristic is marked ``"estimated": True`` / ``"usage_source": "estimated"`` and
    is used only when there is truly no real number to report. Callers must never
    silently mix real numbers with estimates.

    ``attempts`` (Fable-gate rider, Этап 26) — how many provider-level HTTP attempts the
    caller's ``run_buffered_llm_call``/``run_react`` retry loop made for the ONE logical
    call that produced ``text``. Orthogonal to ``estimated``: a heuristic-estimated call
    can still have retried. attempts>1 is a reconciliation signal downstream (a
    provider may bill tokens for a partially-generated failed attempt that never reaches
    this accounting) — always included, default 1 (no retry) is the minimal honest value.
    """
    native = consume_native_usage()
    real = native if native is not None else provider_usage
    if real is not None:
        input_tokens = int(real.get("input_tokens", 0))
        output_tokens = int(real.get("output_tokens", 0))
        usage: dict[str, Any] = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": int(real.get("total_tokens", input_tokens + output_tokens)),
            "estimated": False,
            "attempts": attempts,
            "usage_source": "native",
        }
        # BL-98: the accumulator sums cache counters over EVERY call of the turn;
        # provider_usage (one call, or a caller-summed run) is the fallback.
        cache_source = (
            native
            if native is not None and any(k in native for k in _CACHE_USAGE_KEYS)
            else provider_usage
        )
        if cache_source is not None:
            for cache_key in _CACHE_USAGE_KEYS:
                if cache_key in cache_source:
                    usage[cache_key] = cache_source[cache_key]
        return usage

    input_tokens = _estimate_tokens_for_prompt(lm_messages, prompt)
    output_tokens = estimate_tokens(text)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "estimated": True,
        "attempts": attempts,
        "usage_source": "estimated",
    }


async def _run_checkpoint(checkpoint: CheckpointFn | None) -> RuntimeEvent | None:
    if checkpoint is None:
        return None
    return await checkpoint()


def _make_final_event(
    *,
    text: str,
    config: RuntimeConfig,
    lm_messages: list[dict[str, str]],
    prompt: str,
    start_time: float,
    iterations: int,
    tool_calls: int,
    structured_output: Any,
    new_messages_prefix: list[Message] | None,
    assistant_metadata: dict[str, Any] | None = None,
    provider_usage: dict[str, Any] | None = None,
    attempts: int = 1,
) -> RuntimeEvent:
    usage = _build_usage(
        lm_messages, prompt, text, provider_usage=provider_usage, attempts=attempts
    )
    metrics = _build_metrics(
        start_time,
        config,
        iterations=iterations,
        tool_calls=tool_calls,
        tokens_in=usage["input_tokens"],
        tokens_out=usage["output_tokens"],
    )
    new_messages = list(new_messages_prefix or [])
    new_messages.append(
        Message(role="assistant", content=text, metadata=assistant_metadata)
    )
    return RuntimeEvent.final(
        text=text,
        new_messages=new_messages,
        metrics=metrics,
        usage=usage,
        structured_output=structured_output,
    )


async def finalize_with_validation(
    text: str,
    config: RuntimeConfig,
    lm_messages: list[dict[str, str]],
    prompt: str,
    llm_call: Callable[..., Any],
    start_time: float,
    *,
    iterations: int = 1,
    tool_calls: int = 0,
    new_messages_prefix: list[Message] | None = None,
    checkpoint: CheckpointFn | None = None,
    assistant_metadata: dict[str, Any] | None = None,
    llm_call_kwargs: dict[str, Any] | None = None,
    provider_usage: dict[str, Any] | None = None,
    attempts: int = 1,
) -> AsyncIterator[RuntimeEvent]:
    """Validate structured output, retry if needed, then emit a final event.

    ``provider_usage`` — the REAL usage the provider reported for producing ``text``
    (input/output/total tokens, optionally cache token counts) — is honored ONLY on the
    first-attempt success path below: it describes exactly the one LLM call that
    produced ``text``, so it must never be reused for a retried answer produced by a
    DIFFERENT call. A structured-retry success (further down) has no real usage for its
    own call and always falls back to the honest heuristic estimate.

    ``attempts`` — provider-level HTTP attempts (``run_buffered_llm_call``'s
    ``retry_policy`` loop) that produced ``text``; same one-call-only scoping as
    ``provider_usage`` (a structured-retry success is a DIFFERENT call and always
    reports its own default of 1, never the original attempt's count).
    """
    llm_call_kwargs = dict(llm_call_kwargs or {})
    current_text = text
    current_messages = list(lm_messages)
    if config.event_bus is not None and config.output_type is not None:
        await config.event_bus.emit(
            "structured_validation_start",
            {
                "model": config.model,
                "structured_mode": config.structured_mode,
                "schema_name": config.structured_schema_name,
            },
        )
    structured_output, error, is_empty = _resolve_checked(current_text, config)

    if error is None or config.output_type is None:
        if config.event_bus is not None and config.output_type is not None:
            await config.event_bus.emit(
                "structured_validation_end",
                {
                    "model": config.model,
                    "structured_mode": config.structured_mode,
                    "schema_name": config.structured_schema_name,
                    "ok": error is None,
                },
            )
        checkpoint_event = await _run_checkpoint(checkpoint)
        if checkpoint_event is not None:
            yield checkpoint_event
            return
        gate_block = await _apply_verification_gate(config, current_text, checkpoint)
        if gate_block is not None:
            yield gate_block
            return
        yield _make_final_event(
            text=current_text,
            config=config,
            lm_messages=current_messages,
            prompt=prompt,
            start_time=start_time,
            iterations=iterations,
            tool_calls=tool_calls,
            structured_output=structured_output,
            new_messages_prefix=new_messages_prefix,
            assistant_metadata=assistant_metadata,
            provider_usage=provider_usage,
            attempts=attempts,
        )
        return

    retry_messages = list(lm_messages)
    for _ in range(config.max_model_retries):
        # Only echo a NON-empty prior answer back as the assistant turn. An empty-stop
        # (native loop returned no text and no tool calls) would otherwise seed a confusing
        # empty assistant message; we just ask for the schema-valid answer given the context.
        if current_text:
            retry_messages.append({"role": "assistant", "content": current_text})
        retry_instruction = _EMPTY_RETRY_INSTRUCTION if is_empty else _RETRY_INSTRUCTION
        retry_messages.append(
            {
                "role": "user",
                "content": retry_instruction.format(error=error),
            }
        )
        if config.event_bus is not None:
            await config.event_bus.emit(
                "structured_retry",
                {
                    "model": config.model,
                    "structured_mode": config.structured_mode,
                    "schema_name": config.structured_schema_name,
                    "error": error,
                },
            )

        checkpoint_event = await _run_checkpoint(checkpoint)
        if checkpoint_event is not None:
            yield checkpoint_event
            return

        try:
            raw = await llm_call(retry_messages, prompt, **llm_call_kwargs)
        except ThinLlmError as exc:
            yield RuntimeEvent.error(exc.error)
            return

        checkpoint_event = await _run_checkpoint(checkpoint)
        if checkpoint_event is not None:
            yield checkpoint_event
            return

        envelope = parse_envelope(raw)
        if envelope is not None and envelope.type == "final" and envelope.final_message:
            current_text = envelope.final_message
        else:
            current_text = raw

        current_messages = list(retry_messages)
        structured_output, error, is_empty = _resolve_checked(current_text, config)
        if error is None:
            if config.event_bus is not None:
                await config.event_bus.emit(
                    "structured_validation_end",
                    {
                        "model": config.model,
                        "structured_mode": config.structured_mode,
                        "schema_name": config.structured_schema_name,
                        "ok": True,
                    },
                )
            checkpoint_event = await _run_checkpoint(checkpoint)
            if checkpoint_event is not None:
                yield checkpoint_event
                return
            gate_block = await _apply_verification_gate(
                config, current_text, checkpoint
            )
            if gate_block is not None:
                yield gate_block
                return
            yield _make_final_event(
                text=current_text,
                config=config,
                lm_messages=current_messages,
                prompt=prompt,
                start_time=start_time,
                iterations=iterations,
                tool_calls=tool_calls,
                structured_output=structured_output,
                new_messages_prefix=new_messages_prefix,
                assistant_metadata=assistant_metadata,
            )
            return

    if config.event_bus is not None:
        await config.event_bus.emit(
            "structured_validation_end",
            {
                "model": config.model,
                "structured_mode": config.structured_mode,
                "schema_name": config.structured_schema_name,
                "ok": False,
                "error": error,
            },
        )
    yield RuntimeEvent.error(
        RuntimeErrorData(
            kind="bad_model_output",
            message=(
                "Structured output validation failed after "
                f"{config.max_model_retries} retries: {error}"
            ),
            recoverable=False,
        )
    )
