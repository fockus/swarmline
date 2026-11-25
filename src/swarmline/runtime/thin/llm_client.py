"""LLM client functions for ThinRuntime."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import math
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from swarmline.observability.redaction import redact_secrets
from swarmline.runtime.provider_resolver import resolve_provider
from swarmline.runtime.thin.errors import ThinLlmError, provider_runtime_crash
from swarmline.runtime.thin.llm_providers import get_cached_adapter
from swarmline.runtime.types import RuntimeConfig, RuntimeErrorData, RuntimeEvent

logger = logging.getLogger(__name__)

# Этап 25c fix-cycle 1 MINOR: absolute retry-attempt ceiling for `run_buffered_llm_call`,
# independent of whatever `retry_policy` is injected — the last line of defense against a
# misconfigured/buggy policy that never says "stop" (see the guard in the except-block
# below for the companion NaN/inf/negative-delay hardening).
_MAX_RETRY_ATTEMPTS_HARD_CAP = 10


@dataclass(frozen=True)
class LlmCallResult:
    """Result of a single LLM call with optional thinking content.

    ``usage`` — the REAL provider-reported token usage for THIS call (input/output/
    total, optionally cache token counts), when the adapter surfaces it. ``None`` by
    default (back-compat; no adapter populates this yet) — callers fall back to the
    honest heuristic estimate in ``finalization._build_usage`` rather than fabricate it.
    """

    text: str
    thinking: str | None = None
    usage: dict[str, Any] | None = None


@dataclass(frozen=True)
class BufferedLlmAttempt:
    """Buffered Llm Attempt implementation.

    ``attempts`` — how many provider-level HTTP attempts ``run_buffered_llm_call`` made
    for this ONE logical call (1 = succeeded first try; N>1 = ``retry_policy`` retried
    N-1 transient failures before succeeding). Reconciliation signal (Fable-gate rider,
    Этап 26): a provider MAY bill tokens for a partially-generated failed attempt (e.g.
    a mid-stream timeout) that never reaches swarmline's usage accounting — an
    attempts>1 cost-event is a flag that the billed tokens could undercount the
    provider's actual usage across the whole logical call, not just the winning attempt.
    """

    raw: str
    chunks: list[str]
    used_stream: bool
    thinking: str | None = None
    usage: dict[str, Any] | None = None
    attempts: int = 1


@dataclass(frozen=True)
class StreamingLlmAttempt:
    """Streaming LLM attempt with semantic deltas emitted during iteration.

    ``attempts`` is always 1 here — ``stream_llm_call`` has no ``retry_policy`` loop of
    its own (unlike ``run_buffered_llm_call``); kept for API symmetry with
    ``BufferedLlmAttempt`` so callers can thread ``attempts=`` uniformly either way.
    """

    raw: str
    used_stream: bool
    emitted_text_delta: bool = False
    thinking: str | None = None
    usage: dict[str, Any] | None = None
    attempts: int = 1


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
            usage=result.usage,
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
                        usage=raw.usage,
                        attempts=attempt + 1,
                    )
                return BufferedLlmAttempt(
                    raw=raw, chunks=[], used_stream=False, attempts=attempt + 1
                )

            if isinstance(result, LlmCallResult):
                return BufferedLlmAttempt(
                    raw=result.text,
                    chunks=[result.text],
                    used_stream=False,
                    thinking=result.thinking,
                    usage=result.usage,
                    attempts=attempt + 1,
                )

            if isinstance(result, str):
                return BufferedLlmAttempt(
                    raw=result, chunks=[result], used_stream=True, attempts=attempt + 1
                )

            if hasattr(result, "__aiter__"):
                chunks: list[str] = []
                async for chunk in result:
                    chunks.append(chunk)
                return BufferedLlmAttempt(
                    raw="".join(chunks),
                    chunks=chunks,
                    used_stream=True,
                    attempts=attempt + 1,
                )

            raw = await llm_call(lm_messages, prompt, **llm_kwargs)
            if isinstance(raw, LlmCallResult):
                return BufferedLlmAttempt(
                    raw=raw.text,
                    chunks=[],
                    used_stream=False,
                    thinking=raw.thinking,
                    usage=raw.usage,
                    attempts=attempt + 1,
                )
            return BufferedLlmAttempt(
                raw=raw, chunks=[], used_stream=False, attempts=attempt + 1
            )
        except ThinLlmError as exc:
            if retry_policy is None or exc.error.kind == "cancelled":
                raise

            # Этап 25c fix-cycle 1 MINOR: hard cap independent of `retry_policy` — a
            # misconfigured/buggy injectable policy with no `max_retries` of its own
            # (e.g. always returns `(True, 0.0)`) must not retry forever.
            if attempt >= _MAX_RETRY_ATTEMPTS_HARD_CAP:
                raise

            should_retry, delay = retry_policy.should_retry(exc, attempt)
            if not should_retry:
                raise

            # Fail CLOSED on a non-finite delay (NaN/inf) from a misbehaving policy:
            # `asyncio.sleep(nan)` never fires (a NaN deadline never compares >= "now" in
            # the event loop's timer heap) — a silent, CPU-spinning infinite hang, not a
            # slow retry. Do not retry rather than trust a delay we cannot act on safely.
            if not math.isfinite(delay):
                raise
            # A negative delay is a "sleep 0" bug in the policy, not "never retry" —
            # clamp instead of failing closed.
            delay = max(delay, 0.0)

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

    resolved = resolve_provider(
        config.model, base_url=config.base_url, api_key=config.api_key
    )

    # Extended thinking: inject _thinking_config for Anthropic only
    if config.thinking is not None and resolved.sdk_type == "anthropic":
        use_stream = False  # thinking API is non-streaming
        kwargs["_thinking_config"] = config.thinking

    # Stage 2 (context-engineering-manus-parity): prompt caching (cache_control
    # breakpoints, Hermes system_and_3 recipe) is Anthropic-native only. Opt-in via
    # RuntimeConfig.native_config["prompt_caching_enabled"] (generic passthrough —
    # see agent/runtime_wiring.py's native_config=dict(agent_config.native_config)).
    # Absent/False (default) never adds the kwarg at all, so the request shape stays
    # byte-identical to pre-Stage-2 behaviour; every other provider is a hard no-op
    # regardless of the flag (the kwarg is simply never forwarded).
    if resolved.sdk_type == "anthropic" and config.native_config.get(
        "prompt_caching_enabled", False
    ):
        kwargs["_prompt_caching_enabled"] = True
        # Fix-cycle 1 (MAJOR-4): TTL 5m (default) / 1h, threaded the same way as the
        # enabled flag — RuntimeConfig.native_config["prompt_caching_ttl"]. An
        # invalid/absent value falls back to "5m" (AnthropicAdapter's own default),
        # never raises here.
        kwargs["_prompt_caching_ttl"] = config.native_config.get(
            "prompt_caching_ttl", "5m"
        )

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
