"""Test doubles for LlmAdapter and NativeToolCallAdapter — no network required.

Both :class:`FunctionModel` and :class:`TestModel` implement:

* :class:`~swarmline.runtime.thin.llm_providers.LlmAdapter` — ``call`` + ``stream``
* :class:`~swarmline.runtime.thin.native_tools.NativeToolCallAdapter` — ``call_with_tools``

Wire them via ``ThinRuntime(llm_call=model.as_llm_call())`` for JSON-in-text tests or
``ThinRuntime(native_adapter=model, config=RuntimeConfig(use_native_tools=True))`` for
native tool-calling tests.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from typing import Any, Literal, cast

from swarmline.runtime.thin.native_tools import NativeToolCall, NativeToolCallResult


def _json_schema_sample(schema: dict[str, Any]) -> Any:
    """Generate a deterministic sample value from a JSON Schema fragment.

    Rules (pure, no external deps):

    * ``enum`` present → first enum value (takes priority over ``type``).
    * ``string`` → ``"a"``
    * ``integer`` → ``0``
    * ``number`` → ``0.0``
    * ``boolean`` → ``False``
    * ``array`` → ``[]``
    * ``object`` → dict with required props filled recursively.
      **When ``required`` is absent all ``properties`` are filled.**  A schema without
      ``required`` implies "any combination is valid"; filling all properties produces
      the most useful sample and avoids silently empty dicts.
    * Unknown or absent ``type`` → ``None``.

    Deterministic: the same schema always produces the same sample (seed ignored).
    """
    if "enum" in schema:
        return schema["enum"][0]

    t = schema.get("type")

    if t == "string":
        return "a"
    if t == "integer":
        return 0
    if t == "number":
        return 0.0
    if t == "boolean":
        return False
    if t == "array":
        return []
    if t == "object":
        props: dict[str, Any] = schema.get("properties", {})
        required: list[str] = schema.get("required", list(props.keys()))
        return {k: _json_schema_sample(props[k]) for k in required if k in props}

    return None


class FunctionModel:
    """LLM test double that delegates to a user-supplied function.

    ``fn`` receives the current message list and must return a string — typically a
    JSON envelope (``{"type":"tool_call",...}`` or ``{"type":"final",...}``) for the
    thin react loop, or free text for conversational tests.  Both sync and ``async``
    callables are accepted.

    Usage::

        responses = [tool_call_envelope, final_envelope]
        it = iter(responses)
        model = FunctionModel(fn=lambda _: next(it))

        runtime = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin"),
            llm_call=model.as_llm_call(),
            local_tools={"my_tool": my_tool_fn},
        )
    """

    def __init__(
        self,
        fn: Callable[[list[dict[str, str]]], str | Awaitable[str]],
    ) -> None:
        self._fn = fn
        self._is_async: bool = inspect.iscoroutinefunction(fn)

    async def _invoke(self, messages: list[dict[str, str]]) -> str:
        """Invoke fn, awaiting if it is a coroutine function."""
        if self._is_async:
            return await cast(Awaitable[str], self._fn(messages))
        return cast(str, self._fn(messages))

    async def call(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        **kwargs: Any,
    ) -> str:
        """LlmAdapter.call — delegates to fn(messages)."""
        del system_prompt, kwargs
        return await self._invoke(messages)

    def stream(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """LlmAdapter.stream — yields fn(messages) as a single chunk."""
        del system_prompt, kwargs

        async def _gen() -> AsyncGenerator[str, None]:
            yield await self._invoke(messages)

        return _gen()

    async def call_with_tools(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        tools: list[dict[str, Any]],
        **kwargs: Any,
    ) -> NativeToolCallResult:
        """NativeToolCallAdapter.call_with_tools — wraps fn output (no tool calls)."""
        del system_prompt, tools, kwargs
        text = await self._invoke(messages)
        return NativeToolCallResult(text=text, tool_calls=())

    def as_llm_call(self) -> Callable[..., Any]:
        """Return a callable for ``ThinRuntime(llm_call=...)``.

        Handles both streaming (``stream=True``) and non-streaming paths.  The
        ``**kwargs`` signature satisfies ``wrap_user_llm_call``'s config-pass-through
        check without needing a separate ``config`` parameter.
        """

        async def _call(
            messages: list[dict[str, str]],
            system_prompt: str,
            *,
            stream: bool = False,
            **kwargs: Any,
        ) -> str | AsyncIterator[str]:
            del system_prompt, kwargs
            text = await self._invoke(messages)
            if stream:

                async def _gen() -> AsyncGenerator[str, None]:
                    yield text

                return _gen()
            return text

        return _call


class TestModel:
    """Deterministic LLM test double with auto-generated tool args from JSON Schema.

    Satisfies both :class:`~swarmline.runtime.thin.llm_providers.LlmAdapter` and
    :class:`~swarmline.runtime.thin.native_tools.NativeToolCallAdapter` protocols so it
    can be used in two distinct ways:

    1. ``ThinRuntime(llm_call=model.as_llm_call())`` — JSON-in-text loop; always emits
       a ``{"type":"final","final_message":...}`` envelope.
    2. ``ThinRuntime(native_adapter=model, config=RuntimeConfig(use_native_tools=True))``
       — native tool-calling loop; on the **first** invocation emits one
       :class:`~swarmline.runtime.thin.native_tools.NativeToolCall` per selected tool
       with args auto-filled from the tool's ``parameters`` JSON Schema; on the **second**
       invocation emits the final text so the react loop terminates.

    ``__test__ = False`` prevents pytest from collecting this class.

    .. note::
       Native tool-calling is **one round-trip per instance**: the internal call
       counter is instance-lifetime, so a single ``TestModel`` supports exactly one
       tool round-trip. Reusing one instance across multiple ``ThinRuntime.run()``
       calls exhausts tool calling after the first run (subsequent runs return final
       immediately). Create a fresh ``TestModel`` per run when you need tools each time.

    Parameters
    ----------
    custom_output_text:
        Final text returned after tools (default ``"success"``).
    custom_output_args:
        When set, ``json.dumps(custom_output_args)`` is used as the final text — useful
        for structured output validation tests.
    call_tools:
        ``"all"`` (default) calls every offered tool; a list of names filters to those
        tools; ``[]`` skips tool calling entirely and returns final immediately.
    seed:
        Reserved for future deterministic randomness (currently ignored).
    """

    __test__ = False  # Suppress pytest collection of any Test* class

    def __init__(
        self,
        *,
        custom_output_text: str | None = None,
        custom_output_args: dict[str, Any] | None = None,
        call_tools: list[str] | Literal["all"] = "all",
        seed: int = 0,
    ) -> None:
        self._custom_output_text = custom_output_text
        self._custom_output_args = custom_output_args
        self._call_tools = call_tools
        self._seed = seed  # reserved
        self._native_call_count: int = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _final_text(self) -> str:
        if self._custom_output_args is not None:
            return json.dumps(self._custom_output_args)
        return self._custom_output_text or "success"

    def _final_envelope(self) -> str:
        """Thin-loop final JSON envelope wrapping the final text."""
        return json.dumps(
            {
                "type": "final",
                "final_message": self._final_text(),
                "citations": [],
                "next_suggestions": [],
            }
        )

    # ------------------------------------------------------------------
    # NativeToolCallAdapter
    # ------------------------------------------------------------------

    async def call_with_tools(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        tools: list[dict[str, Any]],
        **kwargs: Any,
    ) -> NativeToolCallResult:
        """Auto-generate tool calls on first invocation; return final on subsequent.

        The ``_native_call_count`` counter ensures the react loop terminates after
        exactly one tool round-trip, regardless of message content.
        """
        del system_prompt, messages, kwargs
        call_idx = self._native_call_count
        self._native_call_count += 1

        # Second+ call, no tools provided, or tool calling disabled → final answer
        if call_idx > 0 or not tools or self._call_tools == []:
            return NativeToolCallResult(
                text=self._final_text(),
                tool_calls=(),
                stop_reason="end_turn",
            )

        # First call — select tools
        if self._call_tools == "all":
            selected = list(tools)
        else:
            allowed: list[str] = self._call_tools  # type: ignore[assignment]
            selected = [t for t in tools if t.get("name") in allowed]

        if not selected:
            return NativeToolCallResult(
                text=self._final_text(),
                tool_calls=(),
                stop_reason="end_turn",
            )

        tool_calls: list[NativeToolCall] = []
        for i, tool_def in enumerate(selected):
            params: dict[str, Any] = tool_def.get("parameters", {})
            raw_args = _json_schema_sample(params)
            tool_calls.append(
                NativeToolCall(
                    id=f"test_{i}",
                    name=tool_def.get("name", f"tool_{i}"),
                    args=raw_args if isinstance(raw_args, dict) else {},
                )
            )

        return NativeToolCallResult(
            text="",
            tool_calls=tuple(tool_calls),
            stop_reason="tool_use",
        )

    # ------------------------------------------------------------------
    # LlmAdapter
    # ------------------------------------------------------------------

    async def call(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        **kwargs: Any,
    ) -> str:
        """Return a thin-loop final envelope (JSON-in-text conversational mode)."""
        del messages, system_prompt, kwargs
        return self._final_envelope()

    def stream(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Yield the final envelope as a single streaming chunk."""
        del messages, system_prompt, kwargs
        envelope = self._final_envelope()

        async def _gen() -> AsyncGenerator[str, None]:
            yield envelope

        return _gen()

    def as_llm_call(self) -> Callable[..., Any]:
        """Return a callable for ``ThinRuntime(llm_call=...)`` (JSON-in-text loop).

        Always emits a ``{"type":"final","final_message":...}`` envelope so the
        conversational and react strategies terminate on the first LLM call.
        The ``**kwargs`` passes ``config=`` through transparently.
        """

        async def _call(
            messages: list[dict[str, str]],
            system_prompt: str,
            *,
            stream: bool = False,
            **kwargs: Any,
        ) -> str | AsyncIterator[str]:
            del messages, system_prompt, kwargs
            envelope = self._final_envelope()
            if stream:

                async def _gen() -> AsyncGenerator[str, None]:
                    yield envelope

                return _gen()
            return envelope

        return _call
