"""Conversational strategy — single LLM call -> final."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

from cognitia.runtime.structured_output import (
    append_structured_output_instruction,
    extract_structured_output,
)
from cognitia.runtime.thin.helpers import _build_metrics, _messages_to_lm
from cognitia.runtime.thin.llm_client import try_stream_llm_call
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
) -> AsyncIterator[RuntimeEvent]:
    """Single LLM call -> final. С поддержкой token streaming."""
    prompt = build_conversational_prompt(
        append_structured_output_instruction(
            system_prompt,
            config.output_format,
            final_response_field="final_message",
        )
    )
    lm_messages = _messages_to_lm(messages)

    # Пробуем streaming
    stream_result = await try_stream_llm_call(llm_call, lm_messages, prompt)

    if stream_result is not None:
        chunks, raw = stream_result

        # Emit per-chunk deltas
        for chunk in chunks:
            yield RuntimeEvent.assistant_delta(chunk)

        # Парсим envelope из собранного текста
        envelope = parse_envelope(raw)
        if envelope is not None and envelope.type == "final" and envelope.final_message:
            text = envelope.final_message
            new_messages = [Message(role="assistant", content=text)]
            structured_output = extract_structured_output(text, config.output_format)
            yield RuntimeEvent.final(
                text=text,
                new_messages=new_messages,
                metrics=_build_metrics(start_time, config, iterations=1),
                structured_output=structured_output,
            )
            return

        # Streaming завершился, но envelope некорректный -- fallback
        raw = await llm_call(lm_messages, prompt)
        envelope = parse_envelope(raw)
        if envelope is not None and envelope.type == "final" and envelope.final_message:
            text = envelope.final_message
            new_messages = [Message(role="assistant", content=text)]
            structured_output = extract_structured_output(text, config.output_format)
            yield RuntimeEvent.final(
                text=text,
                new_messages=new_messages,
                metrics=_build_metrics(start_time, config, iterations=1),
                structured_output=structured_output,
            )
            return

    # Non-streaming path
    raw = await llm_call(lm_messages, prompt)

    envelope = parse_envelope(raw)
    if envelope is None:
        raw = await llm_call(lm_messages, prompt)
        envelope = parse_envelope(raw)

    if envelope is None:
        yield RuntimeEvent.error(
            RuntimeErrorData(
                kind="bad_model_output",
                message="LLM вернула некорректный JSON после 2 попыток",
                recoverable=False,
            )
        )
        return

    if envelope.type == "final" and envelope.final_message:
        text = envelope.final_message
    else:
        text = raw

    new_messages = [Message(role="assistant", content=text)]
    structured_output = extract_structured_output(text, config.output_format)

    yield RuntimeEvent.assistant_delta(text)
    yield RuntimeEvent.final(
        text=text,
        new_messages=new_messages,
        metrics=_build_metrics(start_time, config, iterations=1),
        structured_output=structured_output,
    )
