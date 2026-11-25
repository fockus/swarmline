"""Llm Providers module."""

from __future__ import annotations

import inspect
import logging
from collections.abc import AsyncIterator, Iterable
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

from swarmline.context.prompt_caching import (
    CacheTTL,
    build_cached_system,
    mark_last_message_breakpoints,
)
from swarmline.runtime.provider_resolver import ResolvedProvider
from swarmline.runtime.thin.errors import dependency_missing_error
from swarmline.runtime.thin.usage import (
    anthropic_call_usage,
    cache_counts,
    google_call_usage,
    openai_call_usage,
    record_native_usage,
)

if TYPE_CHECKING:
    from swarmline.runtime.thin.llm_client import LlmCallResult

logger = logging.getLogger(__name__)


@runtime_checkable
class LlmAdapter(Protocol):
    """Llm Adapter protocol."""

    async def call(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        **kwargs: Any,
    ) -> str | LlmCallResult: ...

    def stream(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        **kwargs: Any,
    ) -> AsyncIterator[str]: ...


def _filter_chat_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter out user/assistant messages, fallback on empty user."""
    filtered: list[dict[str, Any]] = []
    for m in messages:
        if m["role"] in ("user", "assistant"):
            d: dict[str, Any] = {"role": m["role"], "content": m["content"]}
            if "content_blocks" in m:
                d["content_blocks"] = m["content_blocks"]
            filtered.append(d)
    if not filtered:
        filtered = [{"role": "user", "content": ""}]
    return filtered


def _convert_content_blocks_anthropic(
    content_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert serialized ContentBlock dicts to Anthropic vision format."""
    result: list[dict[str, Any]] = []
    for block in content_blocks:
        if block.get("type") == "image":
            result.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": block["media_type"],
                        "data": block["data"],
                    },
                }
            )
        else:
            result.append({"type": "text", "text": block.get("text", "")})
    return result


def _convert_content_blocks_openai(
    content_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert serialized ContentBlock dicts to OpenAI vision format."""
    result: list[dict[str, Any]] = []
    for block in content_blocks:
        if block.get("type") == "image":
            data_uri = f"data:{block['media_type']};base64,{block['data']}"
            result.append({"type": "image_url", "image_url": {"url": data_uri}})
        else:
            result.append({"type": "text", "text": block.get("text", "")})
    return result


def _convert_content_blocks_google(
    content_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert serialized ContentBlock dicts to Google Gemini parts format."""
    result: list[dict[str, Any]] = []
    for block in content_blocks:
        if block.get("type") == "image":
            result.append(
                {
                    "inline_data": {
                        "mime_type": block["media_type"],
                        "data": block["data"],
                    }
                }
            )
        else:
            result.append({"text": block.get("text", "")})
    return result


def _apply_content_blocks(
    messages: list[dict[str, Any]],
    converter: Any,
) -> list[dict[str, Any]]:
    """Apply content_blocks conversion to messages that have them."""
    result: list[dict[str, Any]] = []
    for m in messages:
        if "content_blocks" in m:
            converted = converter(m["content_blocks"])
            result.append({**m, "content": converted})
            # Remove the raw content_blocks key from the final dict
            result[-1].pop("content_blocks", None)
        else:
            result.append(m)
    return result


def _compact_kwargs(kwargs: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    """Return only explicitly provided provider kwargs."""
    return {
        key: value
        for key, value in kwargs.items()
        if key in allowed and value is not None
    }


def _fold_reasoning_into_extra_body(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Move the unified ``reasoning`` option inside ``extra_body`` for OpenAI-compat proxies.

    Aggregators (polza.ai, OpenRouter) accept the ``reasoning`` control ONLY as an
    ``extra_body`` member — the openai SDK rejects it as a top-level kwarg, and the
    ``_compact_kwargs`` allowlist would silently drop it, so ``ModelRequestOptions.reasoning``
    never reached the wire. An explicit ``extra_body["reasoning"]`` wins over the folded one
    (setdefault). Returns a new dict; the caller's kwargs are not mutated.
    """
    reasoning = kwargs.get("reasoning")
    if reasoning is None:
        return kwargs
    extra_body = dict(kwargs.get("extra_body") or {})
    extra_body.setdefault("reasoning", reasoning)
    return {**kwargs, "extra_body": extra_body}


def _to_openai_function_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """Wrap a flat ``{name, description, parameters}`` tool dict in OpenAI's function envelope.

    The thin react loop builds tools as flat dicts; the OpenAI/OpenRouter chat API requires
    ``{"type": "function", "function": {"name", "description", "parameters"}}``. Without the
    envelope the provider ignores the tools entirely and the model can never call them. Idempotent:
    a tool already carrying a ``function`` key (or a non-function ``type``) is returned unchanged.
    """
    if "function" in tool or tool.get("type") not in (None, "function"):
        return tool
    return {
        "type": "function",
        "function": {
            "name": tool.get("name"),
            "description": tool.get("description", ""),
            "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
        },
    }


def _capture_usage(
    adapter: Any,
    usage_obj: Any,
    input_attr: str,
    output_attr: str,
) -> None:
    """Record real provider usage on the adapter and in the ContextVar channel.

    ``adapter.last_usage`` always reflects the MOST RECENT call: it is reset to
    None first so a response without usage does not leave stale numbers behind.
    The ContextVar channel accumulates across all calls of the current run.
    Non-int (missing/None) counts from the provider are treated as absent.
    """
    adapter.last_usage = None
    if usage_obj is None:
        return
    raw_input = getattr(usage_obj, input_attr, None)
    raw_output = getattr(usage_obj, output_attr, None)
    input_tokens = raw_input if isinstance(raw_input, int) else None
    output_tokens = raw_output if isinstance(raw_output, int) else None
    if input_tokens is None and output_tokens is None:
        return
    adapter.last_usage = {
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
    }
    cache_read, cache_write = cache_counts(usage_obj)
    record_native_usage(
        input_tokens,
        output_tokens,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
    )


def _response_text(response: object) -> str:
    """Extract text from SDK response objects with duck-typed return models."""
    text = getattr(response, "text", "")
    return text if isinstance(text, str) else str(text)


def _anthropic_usage(response: object) -> dict[str, Any] | None:
    """Extract REAL token usage from an Anthropic Messages API response.

    Returns ``None`` when the response carries no usable ``usage`` block (e.g. a test
    double) — callers must then fall back to the honest heuristic estimate rather than
    fabricate zeros. Cache token counts (``cache_read_tokens``/``cache_write_tokens``)
    are included when the SDK reports them — needed to make cache hit-rate measurable.
    """
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", None) if usage is not None else None
    output_tokens = getattr(usage, "output_tokens", None) if usage is not None else None
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        return None

    result: dict[str, Any] = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }
    cache_read = getattr(usage, "cache_read_input_tokens", None)
    if isinstance(cache_read, int):
        result["cache_read_tokens"] = cache_read
    cache_write = getattr(usage, "cache_creation_input_tokens", None)
    if isinstance(cache_write, int):
        result["cache_write_tokens"] = cache_write
    return result


def _log_anthropic_cache_usage(usage: object) -> None:
    """Log cache_read_input_tokens/cache_creation_input_tokens for ONE completed call.

    Stage 2 (context-engineering-manus-parity): KV cache hit-rate is Manus's metric
    #1 for context-engineering. Fix-cycle 1 (MAJOR-3): logged on EVERY completed
    Anthropic call — ``call()``, ``stream()``, AND ``call_with_tools()`` — regardless
    of whether prompt caching is enabled for this call (an un-cached call
    legitimately reports 0 cache tokens, which is itself useful signal) or whether
    the provider/response object even carries the fields at all. Missing/non-int
    values are normalized to ``0`` so the log line is unconditionally present and
    greppable for hit-rate monitoring — never silently skipped.
    """
    cache_read = (
        getattr(usage, "cache_read_input_tokens", None) if usage is not None else None
    )
    cache_creation = (
        getattr(usage, "cache_creation_input_tokens", None)
        if usage is not None
        else None
    )
    normalized_read = cache_read if isinstance(cache_read, int) else 0
    normalized_creation = cache_creation if isinstance(cache_creation, int) else 0
    logger.info(
        "LLM usage (cache): cache_read_input_tokens=%s cache_creation_input_tokens=%s",
        normalized_read,
        normalized_creation,
        extra={
            "cache_read_input_tokens": normalized_read,
            "cache_creation_input_tokens": normalized_creation,
        },
    )


def _apply_prompt_caching(
    system_prompt: str,
    api_messages: list[dict[str, Any]],
    *,
    enabled: bool,
    ttl: CacheTTL,
) -> tuple[str | list[dict[str, Any]], list[dict[str, Any]]]:
    """Decorate ``system_prompt``/``api_messages`` with ``cache_control`` breakpoints
    when ``enabled``; a no-op passthrough otherwise.

    Fix-cycle 1 (MAJOR-5, guarded decoration): ANY error raised while building the
    cache_control decoration is caught here and falls back to the ORIGINAL, uncached
    system_prompt/messages — a bug in the (best-effort) caching feature must never
    break the underlying LLM call itself.
    """
    if not enabled:
        return system_prompt, api_messages
    try:
        return (
            build_cached_system(system_prompt, ttl=ttl),
            mark_last_message_breakpoints(api_messages, ttl=ttl),
        )
    except Exception:
        logger.warning(
            "Prompt-caching decoration failed; falling back to an uncached request.",
            exc_info=True,
        )
        return system_prompt, api_messages


class AnthropicAdapter:
    """Adapter for Anthropic SDK (messages API)."""

    def __init__(
        self, model: str, *, base_url: str | None = None, api_key: str | None = None
    ) -> None:
        try:
            import anthropic
        except ImportError:
            msg = "anthropic SDK не установлен. Установите: pip install swarmline[thin]"
            raise dependency_missing_error(
                msg,
                provider="anthropic",
                package="anthropic",
            ) from None

        self._model = model
        self._base_url = base_url
        self.last_usage: dict[str, int] | None = None
        client_kwargs: dict[str, Any] = {}
        if base_url:
            client_kwargs["base_url"] = base_url
        # Swarmline's retry policy owns retries. The SDK default (max_retries=2) STACKS with
        # it: one swarmline attempt silently became up to 3 HTTP attempts x timeout (90s+
        # observed in prod) before the caller even saw the error.
        client_kwargs["max_retries"] = 0
        if api_key:
            client_kwargs["api_key"] = api_key
        self._client = anthropic.AsyncAnthropic(**client_kwargs)

    async def call(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        **kwargs: Any,
    ) -> str | Any:
        thinking_config = kwargs.pop("_thinking_config", None)
        prompt_caching_enabled = kwargs.pop("_prompt_caching_enabled", False)
        prompt_caching_ttl: CacheTTL = kwargs.pop("_prompt_caching_ttl", "5m")
        api_messages = _filter_chat_messages(messages)
        api_messages = _apply_content_blocks(
            api_messages, _convert_content_blocks_anthropic
        )
        api_system, api_messages = _apply_prompt_caching(
            system_prompt,
            api_messages,
            enabled=prompt_caching_enabled,
            ttl=prompt_caching_ttl,
        )

        create_kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "system": api_system,
            "messages": api_messages,
            **_compact_kwargs(kwargs, {"temperature", "timeout"}),
        }
        if thinking_config is not None:
            create_kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": thinking_config.budget_tokens,
            }

        response = await self._client.messages.create(**create_kwargs)  # type: ignore[arg-type]
        _capture_usage(
            self, getattr(response, "usage", None), "input_tokens", "output_tokens"
        )
        _log_anthropic_cache_usage(getattr(response, "usage", None))

        if thinking_config is not None:
            text_parts: list[str] = []
            thinking_parts: list[str] = []
            for block in response.content:
                if (
                    hasattr(block, "thinking")
                    and getattr(block, "type", None) == "thinking"
                ):
                    thinking_parts.append(block.thinking)
                elif hasattr(block, "text"):
                    text_parts.append(block.text)

            text = "".join(text_parts)
            if thinking_parts:
                from swarmline.runtime.thin.llm_client import LlmCallResult

                return LlmCallResult(
                    text=text,
                    thinking="".join(thinking_parts),
                    usage=_anthropic_usage(response),
                )
            return text

        return "".join(
            block.text for block in response.content if hasattr(block, "text")
        )

    async def stream(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        prompt_caching_enabled = kwargs.pop("_prompt_caching_enabled", False)
        prompt_caching_ttl: CacheTTL = kwargs.pop("_prompt_caching_ttl", "5m")
        api_messages = _filter_chat_messages(messages)
        api_messages = _apply_content_blocks(
            api_messages, _convert_content_blocks_anthropic
        )
        api_system, api_messages = _apply_prompt_caching(
            system_prompt,
            api_messages,
            enabled=prompt_caching_enabled,
            ttl=prompt_caching_ttl,
        )
        async with self._client.messages.stream(
            model=self._model,
            max_tokens=kwargs.get("max_tokens", 4096),
            system=api_system,  # ty: ignore[invalid-argument-type]  # Anthropic TextBlockParam strict; runtime dict list matches (system, cache_control)
            messages=api_messages,  # ty: ignore[invalid-argument-type]  # Anthropic MessageParam strict; runtime dict matches (stream)
            **_compact_kwargs(kwargs, {"temperature", "timeout"}),
        ) as stream:
            async for text in stream.text_stream:
                yield text
            # The SDK accumulates usage from message_start / message_delta events
            # into the final message snapshot; capture it once the stream is done.
            final_message: Any = None
            try:
                final_message = await stream.get_final_message()
            except Exception:  # noqa: BLE001 - usage capture must never break streaming
                final_message = None
            _capture_usage(
                self,
                getattr(final_message, "usage", None),
                "input_tokens",
                "output_tokens",
            )
            _log_anthropic_cache_usage(getattr(final_message, "usage", None))

    async def call_with_tools(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        tools: list[dict[str, Any]],
        **kwargs: Any,
    ) -> Any:
        """Call Anthropic API with native tool calling."""
        from swarmline.runtime.thin.native_tools import (
            NativeToolCall,
            NativeToolCallResult,
        )

        api_messages = _filter_chat_messages(messages)
        api_messages = _apply_content_blocks(
            api_messages, _convert_content_blocks_anthropic
        )
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=kwargs.get("max_tokens", 4096),
            system=system_prompt,
            messages=api_messages,  # ty: ignore[invalid-argument-type]  # Anthropic MessageParam strict; runtime dict matches (create)
            tools=tools,  # ty: ignore[invalid-argument-type]  # Anthropic ToolParam strict; runtime dict matches (create tools)
        )
        _capture_usage(
            self, getattr(response, "usage", None), "input_tokens", "output_tokens"
        )
        _log_anthropic_cache_usage(getattr(response, "usage", None))
        text_parts: list[str] = []
        tool_calls: list[NativeToolCall] = []
        for block in response.content:
            if hasattr(block, "text"):
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    NativeToolCall(
                        id=block.id,
                        name=block.name,
                        args=dict(block.input) if block.input else {},
                    )
                )
        return NativeToolCallResult(
            text="".join(text_parts),
            tool_calls=tuple(tool_calls),
            stop_reason=getattr(response, "stop_reason", "end_turn") or "end_turn",
            usage=anthropic_call_usage(getattr(response, "usage", None)),
        )


class OpenAICompatAdapter:
    """Open A I Compat Adapter implementation."""

    def __init__(
        self, model: str, *, base_url: str | None = None, api_key: str | None = None
    ) -> None:
        try:
            import openai
        except ImportError:
            msg = "openai SDK не установлен. Установите: pip install swarmline[thin]"
            raise dependency_missing_error(
                msg,
                provider="openai",
                package="openai",
            ) from None

        self._model = model
        self._base_url = base_url
        self.last_usage: dict[str, int] | None = None
        client_kwargs: dict[str, Any] = {}
        if base_url:
            client_kwargs["base_url"] = base_url
        if api_key:
            client_kwargs["api_key"] = api_key
        # Swarmline's retry policy owns retries. The SDK default (max_retries=2) STACKS with
        # it: one swarmline attempt silently became up to 3 HTTP attempts x timeout (90s+
        # observed in prod) before the caller even saw the error.
        client_kwargs["max_retries"] = 0
        self._client = openai.AsyncOpenAI(**client_kwargs)

    @staticmethod
    def _prepare(
        messages: list[dict[str, Any]], system_prompt: str
    ) -> list[dict[str, Any]]:
        api_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]
        for m in messages:
            if m["role"] in ("user", "assistant"):
                d: dict[str, Any] = {"role": m["role"], "content": m["content"]}
                if "content_blocks" in m:
                    d["content_blocks"] = m["content_blocks"]
                api_messages.append(d)
        return api_messages

    async def call(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        **kwargs: Any,
    ) -> str:
        kwargs = _fold_reasoning_into_extra_body(kwargs)
        api_messages = self._prepare(messages, system_prompt)
        api_messages = _apply_content_blocks(
            api_messages, _convert_content_blocks_openai
        )
        response = await self._client.chat.completions.create(  # ty: ignore[no-matching-overload]  # OpenAI ChatCompletion overload — runtime dict structure matches (call)
            model=self._model,
            messages=api_messages,
            max_tokens=kwargs.get("max_tokens", 4096),
            **_compact_kwargs(
                kwargs,
                {"temperature", "timeout", "response_format", "extra_body"},
            ),
        )
        _capture_usage(
            self,
            getattr(response, "usage", None),
            "prompt_tokens",
            "completion_tokens",
        )
        return response.choices[0].message.content or ""

    async def stream(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        kwargs = _fold_reasoning_into_extra_body(kwargs)
        api_messages = self._prepare(messages, system_prompt)
        api_messages = _apply_content_blocks(
            api_messages, _convert_content_blocks_openai
        )
        create_kwargs: dict[str, Any] = dict(
            model=self._model,
            messages=api_messages,
            max_tokens=kwargs.get("max_tokens", 4096),
            stream=True,
            # Ask the provider for a final usage chunk (OpenAI streaming protocol).
            stream_options={"include_usage": True},
            **_compact_kwargs(
                kwargs,
                {"temperature", "timeout", "response_format", "extra_body"},
            ),
        )
        try:
            response = await self._client.chat.completions.create(**create_kwargs)
        except Exception as exc:  # noqa: BLE001 - provider SDKs raise varied error types
            # Some OpenAI-compatible servers/proxies reject unknown streaming
            # params — retry once without stream_options (usage falls back to
            # the estimated source) instead of failing the whole call.
            if "stream_options" not in str(exc):
                raise
            logger.warning(
                "Провайдер отклонил stream_options (%s) — повтор без учёта usage",
                exc,
            )
            create_kwargs.pop("stream_options", None)
            response = await self._client.chat.completions.create(**create_kwargs)
        stream_usage: Any = None
        async for chunk in cast(AsyncIterator[Any], response):
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage is not None:
                stream_usage = chunk_usage
            content = chunk.choices[0].delta.content if chunk.choices else None
            if content:
                yield content
        _capture_usage(self, stream_usage, "prompt_tokens", "completion_tokens")

    async def call_with_tools(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        tools: list[dict[str, Any]],
        **kwargs: Any,
    ) -> Any:
        """Call OpenAI-compatible API with native tool calling."""
        import json as _json

        from swarmline.runtime.thin.native_tools import (
            NativeToolCall,
            NativeToolCallResult,
        )

        kwargs = _fold_reasoning_into_extra_body(kwargs)
        api_messages = self._prepare(messages, system_prompt)
        api_messages = _apply_content_blocks(
            api_messages, _convert_content_blocks_openai
        )
        # The react loop hands tools as flat ``{name, description, parameters}`` dicts. The
        # OpenAI/OpenRouter chat API requires the ``{"type": "function", "function": {...}}``
        # envelope — without it the provider silently ignores the tools and the model can never
        # call them (it answers directly / fabricates). Wrap here (idempotent: an already-wrapped
        # tool with a ``function`` key is passed through untouched).
        openai_tools = [_to_openai_function_tool(tool) for tool in tools]
        response = await self._client.chat.completions.create(  # ty: ignore[no-matching-overload]  # OpenAI params strict; runtime dicts + **kwargs splat match at runtime (call_with_tools)
            model=self._model,
            messages=api_messages,
            max_tokens=kwargs.get("max_tokens", 4096),
            tools=openai_tools,
            **_compact_kwargs(kwargs, {"temperature", "timeout", "extra_body"}),
        )
        _capture_usage(
            self,
            getattr(response, "usage", None),
            "prompt_tokens",
            "completion_tokens",
        )
        choice = response.choices[0]
        text = choice.message.content or ""
        tool_calls: list[NativeToolCall] = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                tool_calls.append(
                    NativeToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        args=_json.loads(tc.function.arguments)
                        if tc.function.arguments
                        else {},
                    )
                )
        return NativeToolCallResult(
            text=text,
            tool_calls=tuple(tool_calls),
            stop_reason=choice.finish_reason or "stop",
            usage=openai_call_usage(getattr(response, "usage", None)),
        )


class GoogleAdapter:
    """Adapter for Google GenAI SDK."""

    def __init__(
        self, model: str, *, base_url: str | None = None, api_key: str | None = None
    ) -> None:
        try:
            import google.genai as genai
        except ImportError:
            msg = "google-genai SDK не установлен. Установите: pip install swarmline[thin]"
            raise dependency_missing_error(
                msg,
                provider="google",
                package="google-genai",
            ) from None

        self._model = model
        self._base_url = base_url
        self.last_usage: dict[str, int] | None = None
        client_kwargs: dict[str, Any] = {}
        if base_url:
            client_kwargs["http_options"] = genai.types.HttpOptions(base_url=base_url)
        if api_key:
            client_kwargs["api_key"] = api_key
        self._client = genai.Client(**client_kwargs)

    @staticmethod
    def _prepare(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        _role_map = {"user": "user", "assistant": "model"}
        contents: list[dict[str, Any]] = []
        for m in messages:
            if m["role"] not in ("user", "assistant"):
                continue
            role = _role_map.get(m["role"], "user")
            if "content_blocks" in m:
                parts = _convert_content_blocks_google(m["content_blocks"])
            else:
                parts = [{"text": m["content"]}]
            contents.append({"role": role, "parts": parts})
        if not contents:
            contents = [{"role": "user", "parts": [{"text": ""}]}]
        return contents

    async def call(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        **kwargs: Any,
    ) -> str:
        contents = self._prepare(messages)
        response: Any = self._client.models.generate_content(
            model=self._model,
            contents=cast(Any, contents),
            config=cast(
                Any,
                {
                    "system_instruction": system_prompt,
                    **_compact_kwargs(kwargs, {"temperature"}),
                },
            ),
        )
        if inspect.isawaitable(response):
            response = await response
        _capture_usage(
            self,
            getattr(response, "usage_metadata", None),
            "prompt_token_count",
            "candidates_token_count",
        )
        return _response_text(response)

    async def stream(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        contents = self._prepare(messages)
        response: Any = self._client.models.generate_content_stream(
            model=self._model,
            contents=cast(Any, contents),
            config={"system_instruction": system_prompt},
        )
        if inspect.isawaitable(response):
            response = await response

        stream_usage: Any = None
        if hasattr(response, "__aiter__"):
            async for chunk in cast(AsyncIterator[Any], response):
                chunk_usage = getattr(chunk, "usage_metadata", None)
                if chunk_usage is not None:
                    stream_usage = chunk_usage
                text = chunk.text
                if text:
                    yield text
            _capture_usage(
                self, stream_usage, "prompt_token_count", "candidates_token_count"
            )
            return

        for chunk in cast(Iterable[Any], response):
            chunk_usage = getattr(chunk, "usage_metadata", None)
            if chunk_usage is not None:
                stream_usage = chunk_usage
            text = chunk.text
            if text:
                yield text
        _capture_usage(
            self, stream_usage, "prompt_token_count", "candidates_token_count"
        )

    async def call_with_tools(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        tools: list[dict[str, Any]],
        **kwargs: Any,
    ) -> Any:
        """Call Google Gemini API with native tool calling."""
        import google.genai as genai

        from swarmline.runtime.thin.native_tools import (
            NativeToolCall,
            NativeToolCallResult,
        )

        contents = self._prepare(messages)
        tool_declarations = [genai.types.FunctionDeclaration(**t) for t in tools]
        google_tools = [genai.types.Tool(function_declarations=tool_declarations)]

        config_kwargs: dict[str, Any] = {"system_instruction": system_prompt}
        if self._base_url:
            config_kwargs["http_options"] = {"base_url": self._base_url}

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=contents,  # type: ignore[arg-type]
            config=genai.types.GenerateContentConfig(
                tools=google_tools,  # ty: ignore[invalid-argument-type]  # Google Tool union strict; runtime list matches
                **config_kwargs,
            ),
        )
        _capture_usage(
            self,
            getattr(response, "usage_metadata", None),
            "prompt_token_count",
            "candidates_token_count",
        )
        text = ""
        tool_calls: list[NativeToolCall] = []
        if response.candidates:
            for part in response.candidates[0].content.parts:  # ty: ignore[unresolved-attribute, not-iterable]  # Gemini Content.parts — gated by candidates truthy check
                if hasattr(part, "text") and part.text:
                    text += part.text
                elif hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    tool_calls.append(
                        NativeToolCall(
                            id=str(fc.id)
                            if hasattr(fc, "id") and fc.id
                            else f"google_{len(tool_calls)}",
                            name=str(fc.name)
                            if fc.name
                            else f"unknown_{len(tool_calls)}",
                            args=dict(fc.args) if fc.args else {},
                        )
                    )
        return NativeToolCallResult(
            text=text,
            tool_calls=tuple(tool_calls),
            stop_reason="end_turn" if not tool_calls else "tool_use",
            usage=google_call_usage(getattr(response, "usage_metadata", None)),
        )


def create_llm_adapter(resolved: ResolvedProvider) -> LlmAdapter:
    """Create llm adapter."""
    if resolved.sdk_type == "anthropic":
        return AnthropicAdapter(
            model=resolved.model_id,
            base_url=resolved.base_url,
            api_key=resolved.api_key,
        )
    if resolved.sdk_type == "openai_compat":
        return OpenAICompatAdapter(
            model=resolved.model_id,
            base_url=resolved.base_url,
            api_key=resolved.api_key,
        )
    if resolved.sdk_type == "google":
        return GoogleAdapter(
            model=resolved.model_id,
            base_url=resolved.base_url,
            api_key=resolved.api_key,
        )
    msg = f"Неизвестный sdk_type: {resolved.sdk_type!r}"
    raise ValueError(msg)


_adapter_cache: dict[tuple[str, str, str | None, str | None], LlmAdapter] = {}


def get_cached_adapter(resolved: ResolvedProvider) -> LlmAdapter:
    """Get cached adapter."""
    key = (resolved.model_id, resolved.provider, resolved.base_url, resolved.api_key)
    if key not in _adapter_cache:
        _adapter_cache[key] = create_llm_adapter(resolved)
    return _adapter_cache[key]
