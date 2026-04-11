"""LLM client functions for ThinRuntime."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

from swarmline.runtime.provider_resolver import resolve_provider
from swarmline.runtime.thin.errors import ThinLlmError, provider_runtime_crash
from swarmline.runtime.thin.llm_providers import get_cached_adapter
from swarmline.runtime.types import RuntimeConfig, RuntimeErrorData

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BufferedLlmAttempt:
    """Buffered Llm Attempt implementation."""

    raw: str
    chunks: list[str]
    used_stream: bool


async def try_stream_llm_call(
    llm_call: Callable[..., Any],
    lm_messages: list[dict[str, str]],
    prompt: str,
) -> tuple[list[str], str] | None:
    """Try stream llm call."""
    try:
        result = await llm_call(lm_messages, prompt, stream=True)
    except TypeError:
        # LLM not supports stream kwarg
        return None

    if isinstance(result, str):

        return [result], result

    if not hasattr(result, "__aiter__"):
        return None

    chunks: list[str] = []
    async for chunk in result:
        chunks.append(chunk)
    return chunks, "".join(chunks)


async def run_buffered_llm_call(
    llm_call: Callable[..., Any],
    lm_messages: list[dict[str, str]],
    prompt: str,
    *,
    retry_policy: Any | None = None,
    cancellation_token: Any | None = None,
    on_retry: Callable[[int, float], None] | None = None,
) -> BufferedLlmAttempt:
    """Run buffered llm call."""
    attempt = 0
    while True:
        try:
            _raise_if_cancelled(cancellation_token)
            try:
                result = await llm_call(lm_messages, prompt, stream=True)
            except TypeError:
                raw = await llm_call(lm_messages, prompt)
                return BufferedLlmAttempt(raw=raw, chunks=[], used_stream=False)

            if isinstance(result, str):
                return BufferedLlmAttempt(raw=result, chunks=[result], used_stream=True)

            if hasattr(result, "__aiter__"):
                chunks: list[str] = []
                async for chunk in result:
                    chunks.append(chunk)
                return BufferedLlmAttempt(raw="".join(chunks), chunks=chunks, used_stream=True)

            raw = await llm_call(lm_messages, prompt)
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
        logger.error("Ошибка LLM API (%s)", provider, exc_info=True)
        raise provider_runtime_crash(provider, exc) from exc


async def default_llm_call(
    config: RuntimeConfig,
    messages: list[dict[str, str]],
    system_prompt: str,
    **kwargs: Any,
) -> str | AsyncIterator[str]:
    """Default llm call."""
    use_stream = kwargs.pop("stream", False)

    resolved = resolve_provider(config.model, base_url=config.base_url)
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
        logger.error("Ошибка инициализации LLM адаптера (%s)", resolved.provider, exc_info=True)
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
        return await adapter.call(messages, system_prompt, **kwargs)
    except ThinLlmError:
        raise
    except Exception as exc:
        logger.error("Ошибка LLM API (%s)", resolved.provider, exc_info=True)
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
