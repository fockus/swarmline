"""Conversational strategy - single LLM call -> final."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

from swarmline.runtime.structured_output import append_structured_output_instruction
from swarmline.runtime.structured_requests import (
    build_llm_call_kwargs,
    structured_mode_uses_native,
)
from swarmline.runtime.thin.errors import ThinLlmError
from swarmline.runtime.thin.finalization import CheckpointFn, finalize_with_validation
from swarmline.runtime.thin.helpers import (
    _messages_to_lm,
    _should_buffer_postprocessing,
)
from swarmline.runtime.thin.llm_client import run_buffered_llm_call, try_stream_llm_call
from swarmline.runtime.thin.parsers import parse_envelope
from swarmline.runtime.thin.prompts import build_conversational_prompt
from swarmline.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
)


async def run_conversational(
    llm_call: Callable[..., Any],
    messages: list[Message],
    system_prompt: str,
    config: RuntimeConfig,
    start_time: float,
    checkpoint: CheckpointFn | None = None,
    on_retry: Callable[[int, float], None] | None = None,
) -> AsyncIterator[RuntimeEvent]:
    """Run conversational."""
    native_structured = structured_mode_uses_native(config)
    prompt_source = (
        system_prompt
        if native_structured
        else append_structured_output_instruction(
            system_prompt,
            config.output_format,
            final_response_field="final_message",
        )
    )
    prompt = build_conversational_prompt(prompt_source)
    lm_messages = _messages_to_lm(messages)
    buffered_postprocessing = _should_buffer_postprocessing(config)
    llm_call_kwargs = build_llm_call_kwargs(config)
    llm_call_kwargs.pop("_swarmline_structured_strategy", None)

    if buffered_postprocessing:
        try:
            checkpoint_event = await _run_checkpoint(checkpoint)
            if checkpoint_event is not None:
                yield checkpoint_event
                return
            attempt = await run_buffered_llm_call(
                llm_call,
                lm_messages,
                prompt,
                retry_policy=config.retry_policy,
                cancellation_token=config.cancellation_token,
                on_retry=on_retry,
                llm_kwargs=llm_call_kwargs,
            )
        except ThinLlmError as exc:
            yield RuntimeEvent.error(exc.error)
            return

        thinking_metadata: dict[str, Any] | None = None
        if attempt.thinking:
            yield RuntimeEvent.thinking_delta(attempt.thinking)
            thinking_metadata = {"thinking": attempt.thinking, "non_compactable": True}

        checkpoint_event = await _run_checkpoint(checkpoint)
        if checkpoint_event is not None:
            yield checkpoint_event
            return

        raw = attempt.raw
        if native_structured:
            async for event in finalize_with_validation(
                raw,
                config,
                lm_messages,
                prompt,
                llm_call,
                start_time,
                checkpoint=checkpoint,
                llm_call_kwargs=llm_call_kwargs,
            ):
                yield event
            return
        envelope = parse_envelope(raw)
        if envelope is not None and envelope.type == "final" and envelope.final_message:
            async for event in finalize_with_validation(
                envelope.final_message,
                config,
                lm_messages,
                prompt,
                llm_call,
                start_time,
                checkpoint=checkpoint,
                assistant_metadata=thinking_metadata,
                llm_call_kwargs=llm_call_kwargs,
            ):
                yield event
            return

        try:
            checkpoint_event = await _run_checkpoint(checkpoint)
            if checkpoint_event is not None:
                yield checkpoint_event
                return
            raw = await llm_call(lm_messages, prompt, **llm_call_kwargs)
        except ThinLlmError as exc:
            yield RuntimeEvent.error(exc.error)
            return
        checkpoint_event = await _run_checkpoint(checkpoint)
        if checkpoint_event is not None:
            yield checkpoint_event
            return

        envelope = parse_envelope(raw)
        if envelope is None:
            yield RuntimeEvent.error(
                RuntimeErrorData(
                    kind="bad_model_output",
                    message="LLM returned invalid JSON after 2 attempts",
                    recoverable=False,
                )
            )
            return

        text = (
            envelope.final_message
            if envelope.type == "final" and envelope.final_message
            else raw
        )
        async for event in finalize_with_validation(
            text,
            config,
            lm_messages,
            prompt,
            llm_call,
            start_time,
            checkpoint=checkpoint,
            llm_call_kwargs=llm_call_kwargs,
        ):
            yield event
        return

    try:
        checkpoint_event = await _run_checkpoint(checkpoint)
        if checkpoint_event is not None:
            yield checkpoint_event
            return
        stream_result = await try_stream_llm_call(
            llm_call,
            lm_messages,
            prompt,
            **llm_call_kwargs,
        )
    except ThinLlmError as exc:
        yield RuntimeEvent.error(exc.error)
        return

    checkpoint_event = await _run_checkpoint(checkpoint)
    if checkpoint_event is not None:
        yield checkpoint_event
        return

    if stream_result is not None:
        chunks, raw = stream_result

        if native_structured:
            async for event in finalize_with_validation(
                raw,
                config,
                lm_messages,
                prompt,
                llm_call,
                start_time,
                checkpoint=checkpoint,
                llm_call_kwargs=llm_call_kwargs,
            ):
                yield event
            return

        # Emit per-chunk deltas
        for chunk in chunks:
            yield RuntimeEvent.assistant_delta(chunk)

        envelope = parse_envelope(raw)
        if envelope is not None and envelope.type == "final" and envelope.final_message:
            text = envelope.final_message
            async for event in finalize_with_validation(
                text,
                config,
                lm_messages,
                prompt,
                llm_call,
                start_time,
                checkpoint=checkpoint,
                llm_call_kwargs=llm_call_kwargs,
            ):
                yield event
            return

        try:
            checkpoint_event = await _run_checkpoint(checkpoint)
            if checkpoint_event is not None:
                yield checkpoint_event
                return
            raw = await llm_call(lm_messages, prompt, **llm_call_kwargs)
        except ThinLlmError as exc:
            yield RuntimeEvent.error(exc.error)
            return
        checkpoint_event = await _run_checkpoint(checkpoint)
        if checkpoint_event is not None:
            yield checkpoint_event
            return
        envelope = parse_envelope(raw)
        if envelope is not None and envelope.type == "final" and envelope.final_message:
            text = envelope.final_message
            async for event in finalize_with_validation(
                text,
                config,
                lm_messages,
                prompt,
                llm_call,
                start_time,
                checkpoint=checkpoint,
                llm_call_kwargs=llm_call_kwargs,
            ):
                yield event
            return

    # Non-streaming path
    try:
        checkpoint_event = await _run_checkpoint(checkpoint)
        if checkpoint_event is not None:
            yield checkpoint_event
            return
        raw = await llm_call(lm_messages, prompt, **llm_call_kwargs)
    except ThinLlmError as exc:
        yield RuntimeEvent.error(exc.error)
        return
    checkpoint_event = await _run_checkpoint(checkpoint)
    if checkpoint_event is not None:
        yield checkpoint_event
        return

    if native_structured:
        async for event in finalize_with_validation(
            raw,
            config,
            lm_messages,
            prompt,
            llm_call,
            start_time,
            checkpoint=checkpoint,
            llm_call_kwargs=llm_call_kwargs,
        ):
            yield event
        return

    envelope = parse_envelope(raw)
    if envelope is None:
        try:
            checkpoint_event = await _run_checkpoint(checkpoint)
            if checkpoint_event is not None:
                yield checkpoint_event
                return
            raw = await llm_call(lm_messages, prompt, **llm_call_kwargs)
        except ThinLlmError as exc:
            yield RuntimeEvent.error(exc.error)
            return
        checkpoint_event = await _run_checkpoint(checkpoint)
        if checkpoint_event is not None:
            yield checkpoint_event
            return
        envelope = parse_envelope(raw)

    if envelope is None:
        yield RuntimeEvent.error(
            RuntimeErrorData(
                kind="bad_model_output",
                message="LLM returned invalid JSON after 2 attempts",
                recoverable=False,
            )
        )
        return

    if envelope.type == "final" and envelope.final_message:
        text = envelope.final_message
    else:
        text = raw

    checkpoint_event = await _run_checkpoint(checkpoint)
    if checkpoint_event is not None:
        yield checkpoint_event
        return
    yield RuntimeEvent.assistant_delta(text)
    async for event in finalize_with_validation(
        text,
        config,
        lm_messages,
        prompt,
        llm_call,
        start_time,
        checkpoint=checkpoint,
        llm_call_kwargs=llm_call_kwargs,
    ):
        yield event


async def _run_checkpoint(checkpoint: CheckpointFn | None) -> RuntimeEvent | None:
    if checkpoint is None:
        return None
    return await checkpoint()
