"""Shared finalization helpers for ThinRuntime strategies."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from swarmline.context.budget import estimate_tokens
from swarmline.runtime.structured_output import try_resolve_structured_output
from swarmline.runtime.thin.errors import ThinLlmError
from swarmline.runtime.thin.helpers import _build_metrics
from swarmline.runtime.thin.parsers import parse_envelope
from swarmline.runtime.types import Message, RuntimeConfig, RuntimeErrorData, RuntimeEvent

_RETRY_INSTRUCTION = (
    "Previous response was not valid JSON matching the schema. "
    "Error: {error}. Please respond with valid JSON only."
)

CheckpointFn = Callable[[], Awaitable[RuntimeEvent | None]]


def _estimate_tokens_for_prompt(
    lm_messages: list[dict[str, str]],
    prompt: str,
) -> int:
    """Approximate input tokens for the current LLM call."""
    serialized_messages = "\n".join(
        f"{msg.get('role', '')}:{msg.get('name', '')}:{msg.get('content', '')}"
        for msg in lm_messages
    )
    return estimate_tokens(f"{prompt}\n{serialized_messages}")


def _build_usage(
    lm_messages: list[dict[str, str]],
    prompt: str,
    text: str,
) -> dict[str, int]:
    """Build portable usage payload using the repo-wide ~4 chars/token heuristic."""
    input_tokens = _estimate_tokens_for_prompt(lm_messages, prompt)
    output_tokens = estimate_tokens(text)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
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
) -> RuntimeEvent:
    usage = _build_usage(lm_messages, prompt, text)
    metrics = _build_metrics(
        start_time,
        config,
        iterations=iterations,
        tool_calls=tool_calls,
        tokens_in=usage["input_tokens"],
        tokens_out=usage["output_tokens"],
    )
    new_messages = list(new_messages_prefix or [])
    new_messages.append(Message(role="assistant", content=text, metadata=assistant_metadata))
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
) -> AsyncIterator[RuntimeEvent]:
    """Validate structured output, retry if needed, then emit a final event."""
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
    structured_output, error = try_resolve_structured_output(
        current_text,
        config.output_format,
        config.output_type,
    )

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

    retry_messages = list(lm_messages)
    for _ in range(config.max_model_retries):
        retry_messages.append({"role": "assistant", "content": current_text})
        retry_messages.append(
            {
                "role": "user",
                "content": _RETRY_INSTRUCTION.format(error=error),
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
        structured_output, error = try_resolve_structured_output(
            current_text,
            config.output_format,
            config.output_type,
        )
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
