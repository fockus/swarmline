"""Conversational strategy - single LLM call -> final."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

from cognitia.runtime.structured_output import append_structured_output_instruction
from cognitia.runtime.thin.errors import ThinLlmError
from cognitia.runtime.thin.finalization import CheckpointFn, finalize_with_validation
from cognitia.runtime.thin.helpers import _messages_to_lm, _should_buffer_postprocessing
from cognitia.runtime.thin.llm_client import run_buffered_llm_call, try_stream_llm_call
from cognitia.runtime.thin.parsers import parse_envelope
from cognitia.runtime.thin.prompts import build_conversational_prompt
from cognitia.runtime.types import (
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
    prompt = build_conversational_prompt(
        append_structured_output_instruction(
            system_prompt,
            config.output_format,
            final_response_field="final_message",
        )
    )
    lm_messages = _messages_to_lm(messages)
    buffered_postprocessing = _should_buffer_postprocessing(config)

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
            )
        except ThinLlmError as exc:
            yield RuntimeEvent.error(exc.error)
            return

        checkpoint_event = await _run_checkpoint(checkpoint)
        if checkpoint_event is not None:
            yield checkpoint_event
            return

        raw = attempt.raw
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
            ):
                yield event
            return

        try:
            checkpoint_event = await _run_checkpoint(checkpoint)
            if checkpoint_event is not None:
                yield checkpoint_event
                return
            raw = await llm_call(lm_messages, prompt)
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

        text = envelope.final_message if envelope.type == "final" and envelope.final_message else raw
        async for event in finalize_with_validation(
            text,
            config,
            lm_messages,
            prompt,
            llm_call,
            start_time,
            checkpoint=checkpoint,
        ):
            yield event
        return


    try:
        checkpoint_event = await _run_checkpoint(checkpoint)
        if checkpoint_event is not None:
            yield checkpoint_event
            return
        stream_result = await try_stream_llm_call(llm_call, lm_messages, prompt)
    except ThinLlmError as exc:
        yield RuntimeEvent.error(exc.error)
        return

    checkpoint_event = await _run_checkpoint(checkpoint)
    if checkpoint_event is not None:
        yield checkpoint_event
        return

    if stream_result is not None:
        chunks, raw = stream_result

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
            ):
                yield event
            return


        try:
            checkpoint_event = await _run_checkpoint(checkpoint)
            if checkpoint_event is not None:
                yield checkpoint_event
                return
            raw = await llm_call(lm_messages, prompt)
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
            ):
                yield event
            return

    # Non-streaming path
    try:
        checkpoint_event = await _run_checkpoint(checkpoint)
        if checkpoint_event is not None:
            yield checkpoint_event
            return
        raw = await llm_call(lm_messages, prompt)
    except ThinLlmError as exc:
        yield RuntimeEvent.error(exc.error)
        return
    checkpoint_event = await _run_checkpoint(checkpoint)
    if checkpoint_event is not None:
        yield checkpoint_event
        return

    envelope = parse_envelope(raw)
    if envelope is None:
        try:
            checkpoint_event = await _run_checkpoint(checkpoint)
            if checkpoint_event is not None:
                yield checkpoint_event
                return
            raw = await llm_call(lm_messages, prompt)
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
    ):
        yield event


async def _run_checkpoint(checkpoint: CheckpointFn | None) -> RuntimeEvent | None:
    if checkpoint is None:
        return None
    return await checkpoint()
