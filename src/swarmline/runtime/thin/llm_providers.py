"""Llm Providers module."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Iterable
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

from swarmline.runtime.provider_resolver import ResolvedProvider
from swarmline.runtime.thin.errors import dependency_missing_error

if TYPE_CHECKING:
    from swarmline.runtime.thin.llm_client import LlmCallResult


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
            msg = "anthropic SDK не установлен. Установите: pip install swarmline[thin]"
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
    ) -> str | Any:
        thinking_config = kwargs.pop("_thinking_config", None)
        api_messages = _filter_chat_messages(messages)

        create_kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "system": system_prompt,
            "messages": api_messages,
        }
        if thinking_config is not None:
            create_kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": thinking_config.budget_tokens,
            }

        response = await self._client.messages.create(**create_kwargs)  # type: ignore[arg-type]

        if thinking_config is not None:
            text_parts: list[str] = []
            thinking_parts: list[str] = []
            for block in response.content:
                if hasattr(block, "thinking") and getattr(block, "type", None) == "thinking":
                    thinking_parts.append(block.thinking)
                elif hasattr(block, "text"):
                    text_parts.append(block.text)

            text = "".join(text_parts)
            if thinking_parts:
                from swarmline.runtime.thin.llm_client import LlmCallResult

                return LlmCallResult(text=text, thinking="".join(thinking_parts))
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
        api_messages = _filter_chat_messages(messages)
        async with self._client.messages.stream(
            model=self._model,
            max_tokens=kwargs.get("max_tokens", 4096),
            system=system_prompt,
            messages=api_messages,  # type: ignore[arg-type]
        ) as stream:
            async for text in stream.text_stream:
                yield text

    async def call_with_tools(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        tools: list[dict[str, Any]],
        **kwargs: Any,
    ) -> Any:
        """Call Anthropic API with native tool calling."""
        from swarmline.runtime.thin.native_tools import NativeToolCall, NativeToolCallResult

        api_messages = _filter_chat_messages(messages)
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=kwargs.get("max_tokens", 4096),
            system=system_prompt,
            messages=api_messages,  # type: ignore[arg-type]
            tools=tools,  # type: ignore[arg-type]
        )
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
        )


class OpenAICompatAdapter:
    """Open A I Compat Adapter implementation."""

    def __init__(self, model: str, *, base_url: str | None = None) -> None:
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

    async def call_with_tools(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        tools: list[dict[str, Any]],
        **kwargs: Any,
    ) -> Any:
        """Call OpenAI-compatible API with native tool calling."""
        import json as _json

        from swarmline.runtime.thin.native_tools import NativeToolCall, NativeToolCallResult

        api_messages = self._prepare(messages, system_prompt)
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=api_messages,  # type: ignore[arg-type]
            max_tokens=kwargs.get("max_tokens", 4096),
            tools=tools,  # type: ignore[arg-type]
        )
        choice = response.choices[0]
        text = choice.message.content or ""
        tool_calls: list[NativeToolCall] = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                tool_calls.append(
                    NativeToolCall(
                        id=tc.id,
                        name=tc.function.name,  # type: ignore[union-attr]
                        args=_json.loads(tc.function.arguments) if tc.function.arguments else {},  # type: ignore[union-attr]
                    )
                )
        return NativeToolCallResult(
            text=text,
            tool_calls=tuple(tool_calls),
            stop_reason=choice.finish_reason or "stop",
        )


class GoogleAdapter:
    """Adapter for Google GenAI SDK."""

    def __init__(self, model: str, *, base_url: str | None = None) -> None:
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

    async def call_with_tools(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        tools: list[dict[str, Any]],
        **kwargs: Any,
    ) -> Any:
        """Call Google Gemini API with native tool calling."""
        import google.genai as genai

        from swarmline.runtime.thin.native_tools import NativeToolCall, NativeToolCallResult

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
                tools=google_tools,  # type: ignore[arg-type]
                **config_kwargs,
            ),
        )
        text = ""
        tool_calls: list[NativeToolCall] = []
        if response.candidates:
            for part in response.candidates[0].content.parts:  # type: ignore[union-attr]
                if hasattr(part, "text") and part.text:
                    text += part.text
                elif hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    tool_calls.append(
                        NativeToolCall(
                            id=str(fc.id) if hasattr(fc, "id") and fc.id else f"google_{len(tool_calls)}",
                            name=str(fc.name) if fc.name else f"unknown_{len(tool_calls)}",
                            args=dict(fc.args) if fc.args else {},
                        )
                    )
        return NativeToolCallResult(
            text=text,
            tool_calls=tuple(tool_calls),
            stop_reason="end_turn" if not tool_calls else "tool_use",
        )


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
