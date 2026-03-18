"""Llm Providers module."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Iterable
from typing import Any, Protocol, cast, runtime_checkable

from cognitia.runtime.provider_resolver import ResolvedProvider
from cognitia.runtime.thin.errors import dependency_missing_error


@runtime_checkable
class LlmAdapter(Protocol):
    """Llm Adapter protocol."""

    async def call(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        **kwargs: Any,
    ) -> str: ...

    def stream(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        **kwargs: Any,
    ) -> AsyncIterator[str]: ...


def _filter_chat_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Filter out user/assistant messages, fallback on empty user."""
    filtered = [
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if m["role"] in ("user", "assistant")
    ]
    if not filtered:
        filtered = [{"role": "user", "content": ""}]
    return filtered


class AnthropicAdapter:
    """Adapter for Anthropic SDK (messages API)."""

    def __init__(self, model: str, *, base_url: str | None = None) -> None:
        try:
            import anthropic
        except ImportError:
            msg = "anthropic SDK не установлен. Установите: pip install cognitia[thin]"
            raise dependency_missing_error(
                msg,
                provider="anthropic",
                package="anthropic",
            ) from None

        self._model = model
        self._base_url = base_url
        client_kwargs: dict[str, Any] = {}
        if base_url:
            client_kwargs["base_url"] = base_url
        self._client = anthropic.AsyncAnthropic(**client_kwargs)

    async def call(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        **kwargs: Any,
    ) -> str:
        api_messages = _filter_chat_messages(messages)
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=kwargs.get("max_tokens", 4096),
            system=system_prompt,
            messages=api_messages,  # type: ignore[arg-type]
        )
        return "".join(
            block.text for block in response.content if hasattr(block, "text")
        )

    async def stream(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        api_messages = _filter_chat_messages(messages)
        async with self._client.messages.stream(
            model=self._model,
            max_tokens=kwargs.get("max_tokens", 4096),
            system=system_prompt,
            messages=api_messages,  # type: ignore[arg-type]
        ) as stream:
            async for text in stream.text_stream:
                yield text


class OpenAICompatAdapter:
    """Open A I Compat Adapter implementation."""

    def __init__(self, model: str, *, base_url: str | None = None) -> None:
        try:
            import openai
        except ImportError:
            msg = "openai SDK не установлен. Установите: pip install cognitia[thin]"
            raise dependency_missing_error(
                msg,
                provider="openai",
                package="openai",
            ) from None

        self._model = model
        self._base_url = base_url
        client_kwargs: dict[str, Any] = {}
        if base_url:
            client_kwargs["base_url"] = base_url
        self._client = openai.AsyncOpenAI(**client_kwargs)

    @staticmethod
    def _prepare(messages: list[dict[str, str]], system_prompt: str) -> list[dict[str, str]]:
        api_messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        api_messages.extend(
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m["role"] in ("user", "assistant")
        )
        return api_messages

    async def call(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        **kwargs: Any,
    ) -> str:
        api_messages = self._prepare(messages, system_prompt)
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=api_messages,  # type: ignore[arg-type]
            max_tokens=kwargs.get("max_tokens", 4096),
        )
        return response.choices[0].message.content or ""

    async def stream(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        api_messages = self._prepare(messages, system_prompt)
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=api_messages,  # type: ignore[arg-type]
            max_tokens=kwargs.get("max_tokens", 4096),
            stream=True,
        )
        async for chunk in cast(AsyncIterator[Any], response):
            content = chunk.choices[0].delta.content if chunk.choices else None
            if content:
                yield content


class GoogleAdapter:
    """Adapter for Google GenAI SDK."""

    def __init__(self, model: str, *, base_url: str | None = None) -> None:
        try:
            import google.genai as genai
        except ImportError:
            msg = "google-genai SDK не установлен. Установите: pip install cognitia[thin]"
            raise dependency_missing_error(
                msg,
                provider="google",
                package="google-genai",
            ) from None

        self._model = model
        self._base_url = base_url
        client_kwargs: dict[str, Any] = {}
        if base_url:
            client_kwargs["http_options"] = genai.types.HttpOptions(base_url=base_url)
        self._client = genai.Client(**client_kwargs)

    @staticmethod
    def _prepare(messages: list[dict[str, str]]) -> list[dict[str, Any]]:
        _role_map = {"user": "user", "assistant": "model"}
        contents: list[dict[str, Any]] = [
            {"role": _role_map.get(m["role"], "user"), "parts": [{"text": m["content"]}]}
            for m in messages
            if m["role"] in ("user", "assistant")
        ]
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
            config={"system_instruction": system_prompt},
        )
        if inspect.isawaitable(response):
            response = await response
        return response.text  # type: ignore[return-value]

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

        if hasattr(response, "__aiter__"):
            async for chunk in cast(AsyncIterator[Any], response):
                text = chunk.text
                if text:
                    yield text
            return

        for chunk in cast(Iterable[Any], response):
            text = chunk.text
            if text:
                yield text


def create_llm_adapter(resolved: ResolvedProvider) -> LlmAdapter:
    """Create llm adapter."""
    if resolved.sdk_type == "anthropic":
        return AnthropicAdapter(model=resolved.model_id, base_url=resolved.base_url)
    if resolved.sdk_type == "openai_compat":
        return OpenAICompatAdapter(model=resolved.model_id, base_url=resolved.base_url)
    if resolved.sdk_type == "google":
        return GoogleAdapter(model=resolved.model_id, base_url=resolved.base_url)
    msg = f"Неизвестный sdk_type: {resolved.sdk_type!r}"
    raise ValueError(msg)


_adapter_cache: dict[tuple[str, str, str | None], LlmAdapter] = {}


def get_cached_adapter(resolved: ResolvedProvider) -> LlmAdapter:
    """Get cached adapter."""
    key = (resolved.model_id, resolved.provider, resolved.base_url)
    if key not in _adapter_cache:
        _adapter_cache[key] = create_llm_adapter(resolved)
    return _adapter_cache[key]
