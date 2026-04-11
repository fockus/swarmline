"""React strategy -- loop (LLM -> tool_call | final)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from swarmline.runtime.structured_output import append_structured_output_instruction
from swarmline.runtime.thin.executor import ToolExecutor
from swarmline.runtime.thin.errors import ThinLlmError
from swarmline.runtime.thin.finalization import CheckpointFn, finalize_with_validation
from swarmline.runtime.thin.helpers import _messages_to_lm, _should_buffer_postprocessing
from swarmline.runtime.thin.llm_client import run_buffered_llm_call, try_stream_llm_call
from swarmline.runtime.thin.parsers import extract_text_fallback, parse_envelope
from swarmline.runtime.thin.prompts import build_react_prompt
from swarmline.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
    ToolSpec,
)


async def run_react(  # noqa: C901
    llm_call: Callable[..., Any],
    executor: ToolExecutor,
    messages: list[Message],
    system_prompt: str,
    tools: list[ToolSpec],
    config: RuntimeConfig,
    start_time: float,
    checkpoint: CheckpointFn | None = None,
    on_retry: Callable[[int, float], None] | None = None,
) -> AsyncIterator[RuntimeEvent]:
    """Run react."""
    prompt = build_react_prompt(
        append_structured_output_instruction(
            system_prompt,
            config.output_format,
            final_response_field="final_message",
        ),
        tools,
    )
    lm_messages = _messages_to_lm(messages)
    new_messages: list[Message] = []

    iterations = 0
    tool_calls_count = 0
    retries = 0
    last_raw = ""
    stream_chunks: list[str] = []
    buffered_postprocessing = _should_buffer_postprocessing(config)

    while iterations < config.max_iterations:
        iterations += 1


        try:
            checkpoint_event = await _run_checkpoint(checkpoint)
            if checkpoint_event is not None:
                yield checkpoint_event
                return
            if buffered_postprocessing:
                attempt = await run_buffered_llm_call(
                    llm_call,
                    lm_messages,
                    prompt,
                    retry_policy=config.retry_policy,
                    cancellation_token=config.cancellation_token,
                    on_retry=on_retry,
                )
                stream_chunks = attempt.chunks
                raw = attempt.raw
            else:
                stream_result = await try_stream_llm_call(llm_call, lm_messages, prompt)
                if stream_result is not None:
                    stream_chunks, raw = stream_result
                else:
                    checkpoint_event = await _run_checkpoint(checkpoint)
                    if checkpoint_event is not None:
                        yield checkpoint_event
                        return
                    raw = await llm_call(lm_messages, prompt)
                    stream_chunks = []
        except ThinLlmError as exc:
            yield RuntimeEvent.error(exc.error)
            return

        checkpoint_event = await _run_checkpoint(checkpoint)
        if checkpoint_event is not None:
            yield checkpoint_event
            return

        last_raw = raw
        envelope = parse_envelope(raw)

        if envelope is None:
            retries += 1
            if retries > config.max_model_retries:
                fallback_text = extract_text_fallback(last_raw)
                if fallback_text:
                    checkpoint_event = await _run_checkpoint(checkpoint)
                    if checkpoint_event is not None:
                        yield checkpoint_event
                        return
                    yield RuntimeEvent.status("LLM returned non-JSON output; using text fallback")
                    async for event in finalize_with_validation(
                        fallback_text,
                        config,
                        lm_messages,
                        prompt,
                        llm_call,
                        start_time,
                        iterations=iterations,
                        tool_calls=tool_calls_count,
                        new_messages_prefix=new_messages,
                        checkpoint=checkpoint,
                    ):
                        if not buffered_postprocessing and event.type == "final":
                            yield RuntimeEvent.assistant_delta(fallback_text)
                        yield event
                    return
                yield RuntimeEvent.error(
                    RuntimeErrorData(
                        kind="bad_model_output",
                        message=f"LLM returned invalid JSON {retries} times in a row",
                        recoverable=False,
                    )
                )
                return
            continue

        retries = 0

        # --- tool_call ---
        if envelope.type == "tool_call" and envelope.tool:
            tc = envelope.tool

            # Budget check
            if tool_calls_count >= config.max_tool_calls:
                yield RuntimeEvent.error(
                    RuntimeErrorData(
                        kind="budget_exceeded",
                        message=f"Превышен лимит tool_calls ({config.max_tool_calls})",
                        recoverable=False,
                    )
                )
                return

            cid = tc.correlation_id or f"c{tool_calls_count + 1}"

            checkpoint_event = await _run_checkpoint(checkpoint)
            if checkpoint_event is not None:
                yield checkpoint_event
                return
            yield RuntimeEvent.tool_call_started(
                name=tc.name,
                args=tc.args,
                correlation_id=cid,
            )


            result = await executor.execute(tc.name, tc.args)

            checkpoint_event = await _run_checkpoint(checkpoint)
            if checkpoint_event is not None:
                yield checkpoint_event
                return


            tool_ok = True
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict) and "error" in parsed:
                    tool_ok = False
            except (json.JSONDecodeError, TypeError):
                pass

            yield RuntimeEvent.tool_call_finished(
                name=tc.name,
                correlation_id=cid,
                ok=tool_ok,
                result_summary=result[:200],
            )

            tool_calls_count += 1


            new_messages.append(
                Message(
                    role="assistant",
                    content=tc.assistant_message if hasattr(tc, "assistant_message") else "",
                    metadata={"tool_call": tc.name},
                )
            )
            new_messages.append(
                Message(
                    role="tool",
                    content=result,
                    name=tc.name,
                )
            )
            lm_messages.append({"role": "assistant", "content": f"Вызываю {tc.name}"})
            lm_messages.append({"role": "user", "content": f"Результат {tc.name}: {result}"})

            if envelope.assistant_message:
                yield RuntimeEvent.status(envelope.assistant_message)

            continue

        # --- final ---
        if envelope.type == "final" and envelope.final_message:
            text = envelope.final_message
            checkpoint_event = await _run_checkpoint(checkpoint)
            if checkpoint_event is not None:
                yield checkpoint_event
                return
            if not buffered_postprocessing and stream_chunks:
                for chunk in stream_chunks:
                    yield RuntimeEvent.assistant_delta(chunk)
            elif not buffered_postprocessing:
                yield RuntimeEvent.assistant_delta(text)
            async for event in finalize_with_validation(
                text,
                config,
                lm_messages,
                prompt,
                llm_call,
                start_time,
                iterations=iterations,
                tool_calls=tool_calls_count,
                new_messages_prefix=new_messages,
                checkpoint=checkpoint,
            ):
                yield event
            return

        # --- clarify ---
        if envelope.type == "clarify":
            text = envelope.assistant_message or "Please clarify."
            if envelope.questions:
                qs = "\n".join(f"- {q.text}" for q in envelope.questions)
                text = f"{text}\n\n{qs}"

            checkpoint_event = await _run_checkpoint(checkpoint)
            if checkpoint_event is not None:
                yield checkpoint_event
                return
            if not buffered_postprocessing and stream_chunks:
                for chunk in stream_chunks:
                    yield RuntimeEvent.assistant_delta(chunk)
            elif not buffered_postprocessing:
                yield RuntimeEvent.assistant_delta(text)
            async for event in finalize_with_validation(
                text,
                config,
                lm_messages,
                prompt,
                llm_call,
                start_time,
                iterations=iterations,
                tool_calls=tool_calls_count,
                new_messages_prefix=new_messages,
                checkpoint=checkpoint,
            ):
                yield event
            return

    # Loop limit reached
    yield RuntimeEvent.error(
        RuntimeErrorData(
            kind="loop_limit",
            message=f"Превышен лимит итераций ({config.max_iterations})",
            recoverable=False,
        )
    )


async def _run_checkpoint(checkpoint: CheckpointFn | None) -> RuntimeEvent | None:
    if checkpoint is None:
        return None
    return await checkpoint()
