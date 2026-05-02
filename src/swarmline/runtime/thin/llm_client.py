"""LLM client functions for ThinRuntime."""

from __future__ import annotations

import asyncio
import io
import json
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from swarmline.observability.redaction import redact_secrets
from swarmline.runtime.provider_resolver import resolve_provider
from swarmline.runtime.thin.errors import ThinLlmError, provider_runtime_crash
from swarmline.runtime.thin.llm_providers import get_cached_adapter
from swarmline.runtime.types import RuntimeConfig, RuntimeErrorData, RuntimeEvent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LlmCallResult:
    """Result of a single LLM call with optional thinking content."""

    text: str
    thinking: str | None = None


@dataclass(frozen=True)
class BufferedLlmAttempt:
    """Buffered Llm Attempt implementation."""

    raw: str
    chunks: list[str]
    used_stream: bool
    thinking: str | None = None


@dataclass(frozen=True)
class StreamingLlmAttempt:
    """Streaming LLM attempt with semantic deltas emitted during iteration."""

    raw: str
    used_stream: bool
    emitted_text_delta: bool = False
    thinking: str | None = None


class FinalMessageDeltaExtractor:
    """Incrementally extract text from a JSON ``final_message`` string value."""

    def __init__(self) -> None:
        self._in_string = False
        self._capture_value = False
        self._done = False
        self._escape = False
        self._unicode_digits: str | None = None
        self._token_raw: list[str] = []
        self._captured_value: list[str] = []
        self._awaiting_colon = False
        self._awaiting_value = False
        self._pending_value_key: str | None = None
        self._capturing_value_key: str | None = None
        self._string_depth = 0
        self._depth = 0
        self._seen_top_level_final_type = False

    def feed(self, chunk: str) -> list[str]:
        deltas: list[str] = []
        for char in chunk:
            delta = self._feed_char(char)
            if delta:
                deltas.append(delta)
        return deltas

    def _feed_char(self, char: str) -> str:
        if self._done:
            return ""

        if self._in_string:
            return self._feed_string_char(char)

        if char in "{[":
            self._depth += 1
            return ""

        if char in "}]":
            self._depth = max(0, self._depth - 1)
            self._awaiting_colon = False
            self._awaiting_value = False
            self._pending_value_key = None
            return ""

        if self._awaiting_colon:
            if char.isspace():
                return ""
            if char == ":":
                self._awaiting_colon = False
                self._awaiting_value = True
            else:
                self._awaiting_colon = False
                self._pending_value_key = None
            return ""

        if self._awaiting_value:
            if char.isspace():
                return ""
            if char == '"':
                self._start_string(capture_value=True)
            else:
                self._awaiting_value = False
                self._pending_value_key = None
            return ""

        if char == '"':
            self._start_string(capture_value=False)
        return ""

    def _start_string(self, *, capture_value: bool) -> None:
        self._in_string = True
        self._capture_value = capture_value
        self._escape = False
        self._unicode_digits = None
        self._token_raw = []
        self._captured_value = []
        self._string_depth = self._depth
        if capture_value:
            self._awaiting_value = False
            self._capturing_value_key = self._pending_value_key
            self._pending_value_key = None
        else:
            self._capturing_value_key = None

    def _feed_string_char(self, char: str) -> str:
        if self._unicode_digits is not None:
            self._unicode_digits += char
            if len(self._unicode_digits) == 4:
                digits = self._unicode_digits
                self._unicode_digits = None
                self._escape = False
                try:
                    return self._capture_decoded_char(chr(int(digits, 16)))
                except ValueError:
                    return ""
            return ""

        if self._escape:
            self._escape = False
            if char == "u":
                self._unicode_digits = ""
                return ""
            if self._capture_value:
                decoded = {
                    '"': '"',
                    "\\": "\\",
                    "/": "/",
                    "b": "\b",
                    "f": "\f",
                    "n": "\n",
                    "r": "\r",
                    "t": "\t",
                }.get(char, char)
                return self._capture_decoded_char(decoded)
            self._token_raw.append("\\" + char)
            return ""

        if char == "\\":
            self._escape = True
            if not self._capture_value:
                self._token_raw.append(char)
            return ""

        if char == '"':
            self._finish_string()
            return ""

        if self._capture_value:
            return self._capture_decoded_char(char)

        self._token_raw.append(char)
        return ""

    def _capture_decoded_char(self, char: str) -> str:
        if not self._capture_value:
            return ""
        self._captured_value.append(char)
        return char if self._capturing_value_key == "final_message" else ""

    def _finish_string(self) -> None:
        was_capture = self._capture_value
        captured_key = self._capturing_value_key
        self._in_string = False
        self._capture_value = False
        self._capturing_value_key = None
        self._escape = False
        self._unicode_digits = None

        if was_capture:
            captured_value = "".join(self._captured_value)
            self._captured_value = []
            if captured_key == "type" and captured_value == "final":
                self._seen_top_level_final_type = True
            elif captured_key == "final_message":
                self._done = True
            return

        raw = "".join(self._token_raw)
        self._token_raw = []
        try:
            value = json.loads(f'"{raw}"')
        except json.JSONDecodeError:
            return
        if self._string_depth != 1:
            return
        if value == "type":
            self._pending_value_key = "type"
            self._awaiting_colon = True
        elif value == "final_message" and self._seen_top_level_final_type:
            self._pending_value_key = "final_message"
            self._awaiting_colon = True


async def stream_llm_call(
    llm_call: Callable[..., Any],
    lm_messages: list[dict[str, str]],
    prompt: str,
    *,
    emit_final_message_delta: bool = True,
    **kwargs: Any,
) -> AsyncIterator[RuntimeEvent | StreamingLlmAttempt]:
    """Try an LLM streaming call and yield semantic text deltas plus final raw JSON."""
    try:
        result = await llm_call(lm_messages, prompt, stream=True, **kwargs)
    except TypeError:
        return

    if isinstance(result, LlmCallResult):
        if result.thinking:
            logger.warning(
                "Thinking content in streaming path will not be emitted as event. "
                "Ensure _should_buffer_postprocessing returns True when thinking is configured.",
            )
        yield StreamingLlmAttempt(
            raw=result.text,
            used_stream=False,
            emitted_text_delta=False,
            thinking=result.thinking,
        )
        return

    if isinstance(result, str):
        yield StreamingLlmAttempt(
            raw=result, used_stream=True, emitted_text_delta=False
        )
        return

    if not hasattr(result, "__aiter__"):
        return

    raw_buffer = io.StringIO()
    extractor = FinalMessageDeltaExtractor()
    emitted = False
    async for chunk in result:
        raw_buffer.write(chunk)
        if not emit_final_message_delta:
            continue
        for delta in extractor.feed(chunk):
            emitted = True
            yield RuntimeEvent.assistant_delta(delta)
    yield StreamingLlmAttempt(
        raw=raw_buffer.getvalue(),
        used_stream=True,
        emitted_text_delta=emitted,
    )


async def try_stream_llm_call(
    llm_call: Callable[..., Any],
    lm_messages: list[dict[str, str]],
    prompt: str,
    **kwargs: Any,
) -> StreamingLlmAttempt | None:
    """Try a streaming LLM call and return raw output without buffering chunks."""
    attempt: StreamingLlmAttempt | None = None
    async for item in stream_llm_call(
        llm_call,
        lm_messages,
        prompt,
        emit_final_message_delta=False,
        **kwargs,
    ):
        if isinstance(item, StreamingLlmAttempt):
            attempt = item
    return attempt


async def run_buffered_llm_call(
    llm_call: Callable[..., Any],
    lm_messages: list[dict[str, str]],
    prompt: str,
    *,
    retry_policy: Any | None = None,
    cancellation_token: Any | None = None,
    on_retry: Callable[[int, float], None] | None = None,
    llm_kwargs: dict[str, Any] | None = None,
) -> BufferedLlmAttempt:
    """Run buffered llm call."""
    llm_kwargs = dict(llm_kwargs or {})
    attempt = 0
    while True:
        try:
            _raise_if_cancelled(cancellation_token)
            try:
                result = await llm_call(lm_messages, prompt, stream=True, **llm_kwargs)
            except TypeError:
                raw = await llm_call(lm_messages, prompt, **llm_kwargs)
                if isinstance(raw, LlmCallResult):
                    return BufferedLlmAttempt(
                        raw=raw.text,
                        chunks=[],
                        used_stream=False,
                        thinking=raw.thinking,
                    )
                return BufferedLlmAttempt(raw=raw, chunks=[], used_stream=False)

            if isinstance(result, LlmCallResult):
                return BufferedLlmAttempt(
                    raw=result.text,
                    chunks=[result.text],
                    used_stream=False,
                    thinking=result.thinking,
                )

            if isinstance(result, str):
                return BufferedLlmAttempt(raw=result, chunks=[result], used_stream=True)

            if hasattr(result, "__aiter__"):
                chunks: list[str] = []
                async for chunk in result:
                    chunks.append(chunk)
                return BufferedLlmAttempt(
                    raw="".join(chunks), chunks=chunks, used_stream=True
                )

            raw = await llm_call(lm_messages, prompt, **llm_kwargs)
            if isinstance(raw, LlmCallResult):
                return BufferedLlmAttempt(
                    raw=raw.text,
                    chunks=[],
                    used_stream=False,
                    thinking=raw.thinking,
                )
            return BufferedLlmAttempt(raw=raw, chunks=[], used_stream=False)
        except ThinLlmError as exc:
            if retry_policy is None or exc.error.kind == "cancelled":
                raise

            should_retry, delay = retry_policy.should_retry(exc, attempt)
            if not should_retry:
                raise

            logger.info(
                "Retry attempt %d, delay %.1fs during buffered stream: %s",
                attempt + 1,
                delay,
                exc,
            )
            if on_retry is not None:
                on_retry(attempt + 1, delay)
            await _sleep_with_cancellation(delay, cancellation_token)
            attempt += 1


async def _stream_with_error_normalization(
    adapter: Any,
    provider: str,
    messages: list[dict[str, str]],
    system_prompt: str,
    **kwargs: Any,
) -> AsyncIterator[str]:
    """Wrap adapter.stream() so iteration-time failures become typed errors."""
    try:
        async for chunk in adapter.stream(messages, system_prompt, **kwargs):
            yield chunk
    except ThinLlmError:
        raise
    except Exception as exc:
        logger.error(
            "LLM API error (%s, %s): %s",
            provider,
            type(exc).__name__,
            redact_secrets(str(exc)),
            extra={"provider": provider, "exc_type": type(exc).__name__},
        )
        raise provider_runtime_crash(provider, exc) from exc


async def default_llm_call(
    config: RuntimeConfig,
    messages: list[dict[str, str]],
    system_prompt: str,
    **kwargs: Any,
) -> str | LlmCallResult | AsyncIterator[str]:
    """Default llm call."""
    use_stream = kwargs.pop("stream", False)

    resolved = resolve_provider(config.model, base_url=config.base_url)

    # Extended thinking: inject _thinking_config for Anthropic only
    if config.thinking is not None and resolved.sdk_type == "anthropic":
        use_stream = False  # thinking API is non-streaming
        kwargs["_thinking_config"] = config.thinking

    logger.info(
        "LLM запрос: model=%s, provider=%s, sdk=%s, stream=%s",
        resolved.model_id,
        resolved.provider,
        resolved.sdk_type,
        use_stream,
    )

    try:
        adapter = get_cached_adapter(resolved)
    except ThinLlmError:
        raise
    except Exception as exc:
        logger.error(
            "Ошибка инициализации LLM адаптера (%s, %s): %s",
            resolved.provider,
            type(exc).__name__,
            redact_secrets(str(exc)),
            extra={"provider": resolved.provider, "exc_type": type(exc).__name__},
        )
        raise provider_runtime_crash(resolved.provider, exc) from exc

    try:
        if use_stream:
            return _stream_with_error_normalization(
                adapter,
                resolved.provider,
                messages,
                system_prompt,
                **kwargs,
            )
        result = await adapter.call(messages, system_prompt, **kwargs)
        if isinstance(result, LlmCallResult):
            return result
        return result
    except ThinLlmError:
        raise
    except Exception as exc:
        logger.error(
            "LLM API error (%s, %s): %s",
            resolved.provider,
            type(exc).__name__,
            redact_secrets(str(exc)),
            extra={"provider": resolved.provider, "exc_type": type(exc).__name__},
        )
        raise provider_runtime_crash(resolved.provider, exc) from exc


def _raise_if_cancelled(token: Any | None) -> None:
    if token is None or not token.is_cancelled:
        return
    raise ThinLlmError(
        RuntimeErrorData(
            kind="cancelled",
            message="Operation cancelled",
            recoverable=False,
        )
    )


async def _sleep_with_cancellation(delay: float, token: Any | None) -> None:
    if delay <= 0:
        return
    if token is None:
        await asyncio.sleep(delay)
        return

    remaining = delay
    step = 0.05
    while remaining > 0:
        _raise_if_cancelled(token)
        wait_for = min(step, remaining)
        await asyncio.sleep(wait_for)
        remaining -= wait_for
    _raise_if_cancelled(token)
