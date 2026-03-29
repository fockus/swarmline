"""Runtime module."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator, Callable
from functools import partial
from typing import Any

from cognitia.guardrails import GuardrailContext, GuardrailResult
from cognitia.runtime.cost import CostTracker, load_pricing
from cognitia.runtime.thin.builtin_tools import create_thin_builtin_tools
from cognitia.runtime.thin.errors import ThinLlmError
from cognitia.runtime.thin.executor import ToolExecutor
from cognitia.runtime.thin.helpers import _should_buffer_postprocessing
from cognitia.runtime.thin.llm_client import default_llm_call
from cognitia.runtime.thin.modes import detect_mode
from cognitia.runtime.thin.strategies import (
    run_conversational,
    run_planner,
    run_react,
)
from cognitia.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
    ToolSpec,
)


class ThinRuntime:
    """Thin Runtime implementation."""

    def __init__(
        self,
        config: RuntimeConfig | None = None,
        llm_call: Callable[..., Any] | None = None,
        local_tools: dict[str, Callable[..., Any]] | None = None,
        mcp_servers: dict[str, Any] | None = None,
        react_patterns: list[re.Pattern[str]] | None = None,
        planner_patterns: list[re.Pattern[str]] | None = None,
        sandbox: Any | None = None,
    ) -> None:
        self._config = config or RuntimeConfig(runtime_name="thin")
        self._auto_wrap_retriever()
        self._retry_events: list[RuntimeEvent] = []
        if llm_call is not None:
            raw_llm_call = self._wrap_user_llm_call(llm_call)
        else:
            raw_llm_call = self._make_default_llm_call()
        if self._config.event_bus is not None:
            raw_llm_call = self._wrap_with_event_bus(raw_llm_call)
        self._llm_call = raw_llm_call
        self._react_patterns = react_patterns
        self._planner_patterns = planner_patterns

        # Merge user local_tools with sandbox built-in executors
        merged_local_tools = dict(local_tools or {})
        _builtin_specs, builtin_executors = create_thin_builtin_tools(sandbox)
        for name, executor in builtin_executors.items():
            # User tools take priority over built-ins
            if name not in merged_local_tools:
                merged_local_tools[name] = executor

        self._executor = ToolExecutor(
            local_tools=merged_local_tools,
            mcp_servers=mcp_servers,
        )

        # Cost tracking
        self._cost_tracker: CostTracker | None = None
        if self._config.cost_budget is not None:
            self._cost_tracker = CostTracker(
                budget=self._config.cost_budget,
                pricing=load_pricing(),
            )

    def _auto_wrap_retriever(self) -> None:
        """Auto-wrap config.retriever into input_filters if not already present."""
        if self._config.retriever is None:
            return

        from cognitia.rag import RagInputFilter

        # Check if RagInputFilter is already in input_filters
        for f in self._config.input_filters:
            if isinstance(f, RagInputFilter):
                return

        rag_filter = RagInputFilter(retriever=self._config.retriever)
        self._config.input_filters.insert(0, rag_filter)

    @staticmethod
    def _wrap_user_llm_call(user_fn: Callable[..., Any]) -> Callable[..., Any]:
        """Wrap a user-provided llm_call to accept (and forward) the ``config`` kwarg.

        User callables that already accept ``config`` get it as-is.
        Legacy callables that don't accept ``config`` have it silently stripped
        so existing code keeps working without modification.
        """
        import inspect

        sig = inspect.signature(user_fn)
        params = sig.parameters
        accepts_config = (
            "config" in params
            or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
        )
        if accepts_config:
            return user_fn

        async def _adapted(
            messages: list[dict[str, str]],
            system_prompt: str,
            *,
            config: RuntimeConfig | None = None,  # noqa: ARG001
            **kwargs: Any,
        ) -> Any:
            return await user_fn(messages, system_prompt, **kwargs)

        return _adapted

    def _make_default_llm_call(self) -> Callable[..., Any]:
        """Make default llm call.

        Returns a callable that accepts an optional ``config`` keyword.
        When provided, the per-call config is forwarded to ``default_llm_call``
        instead of the constructor config, enabling per-call model/provider overrides.
        """
        fallback_config = self._config

        async def _call(
            messages: list[dict[str, str]],
            system_prompt: str,
            *,
            config: RuntimeConfig | None = None,
            **kwargs: Any,
        ) -> str | AsyncIterator[str]:
            effective = config or fallback_config
            return await default_llm_call(effective, messages, system_prompt, **kwargs)

        return _call

    def _wrap_with_event_bus(self, llm_call: Callable[..., Any]) -> Callable[..., Any]:
        """Wrap LLM call with EventBus emit for LLM_call_start/LLM_call_end.

        Forwards the ``config`` keyword so that per-call overrides reach the
        underlying ``llm_call`` and event metadata reflects the actual model.
        """
        bus = self._config.event_bus
        if bus is None:
            raise ValueError("event_bus must not be None")
        fallback_config = self._config

        async def _instrumented_call(
            messages: list[dict[str, str]],
            system_prompt: str,
            *,
            config: RuntimeConfig | None = None,
            **kwargs: Any,
        ) -> str | AsyncIterator[str]:
            effective = config or fallback_config
            await bus.emit("llm_call_start", {"model": effective.model})
            try:
                result = await llm_call(messages, system_prompt, config=config, **kwargs)
                await bus.emit("llm_call_end", {"model": effective.model})
                return result
            except Exception:
                await bus.emit("llm_call_end", {"model": effective.model, "error": True})
                raise

        return _instrumented_call

    def cancel(self) -> None:
        """Cancel the current operation via CancellationToken."""
        if self._config.cancellation_token is not None:
            self._config.cancellation_token.cancel()

    async def __aenter__(self) -> ThinRuntime:
        """Enter async context manager."""
        return self

    async def __aexit__(self, *exc: Any) -> None:
        """Exit async context manager - calls cleanup()."""
        await self.cleanup()

    async def run(
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        config: RuntimeConfig | None = None,
        mode_hint: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Run."""
        effective_config = config or self._config
        start_time = time.monotonic()
        tracker = self._cost_tracker

        cancelled_event = self._cancelled_event(effective_config.cancellation_token)
        if cancelled_event is not None:
            yield cancelled_event
            return

        # Pre-call budget check
        if tracker is not None and tracker.check_budget() == "exceeded":
            yield self._budget_exceeded_event(tracker, prefix="Cost budget exceeded before call")
            return


        user_text = self._extract_last_user_text(messages)

        # --- Input guardrails ---
        if effective_config.input_guardrails:
            guard_error = await self._run_guardrails(
                effective_config.input_guardrails,
                user_text,
                effective_config,
            )
            if guard_error is not None:
                yield guard_error
                return

        # --- Input filters ---
        if effective_config.input_filters:
            for f in effective_config.input_filters:
                messages, system_prompt = await f.filter(messages, system_prompt)

        mode = detect_mode(
            user_text,
            mode_hint,
            react_patterns=self._react_patterns,
            planner_patterns=self._planner_patterns,
        )

        yield RuntimeEvent.status(f"Mode: {mode}")

        # Flush any buffered retry events from previous calls
        self._retry_events.clear()
        buffered_postprocessing = _should_buffer_postprocessing(effective_config)
        emitted_text_delta = False

        async def checkpoint() -> RuntimeEvent | None:
            return self._cancelled_event(effective_config.cancellation_token)

        # Bind effective config into llm_call so strategies use the correct
        # model/provider without needing signature changes.
        llm_call: Callable[..., Any] = partial(self._llm_call, config=effective_config)

        # Collect events; intercept final for output guardrails
        try:
            strategy: AsyncIterator[RuntimeEvent]
            if mode == "conversational":
                strategy = run_conversational(
                    llm_call,
                    messages,
                    system_prompt,
                    effective_config,
                    start_time,
                    checkpoint=checkpoint,
                    on_retry=self._buffer_retry_status,
                )
            elif mode == "react":
                strategy = run_react(
                    llm_call,
                    self._executor,
                    messages,
                    system_prompt,
                    active_tools,
                    effective_config,
                    start_time,
                    checkpoint=checkpoint,
                    on_retry=self._buffer_retry_status,
                )
            else:
                strategy = run_planner(
                    llm_call,
                    self._executor,
                    messages,
                    system_prompt,
                    active_tools,
                    effective_config,
                    start_time,
                    checkpoint=checkpoint,
                )

            # EventBus reference for emitting tool call events
            event_bus = effective_config.event_bus

            async for event in strategy:
                # --- Emit buffered retry status events ---
                if self._retry_events:
                    for retry_evt in self._retry_events:
                        yield retry_evt
                    self._retry_events.clear()

                # --- EventBus: emit tool call events ---
                if event_bus is not None:
                    if event.type == "tool_call_started":
                        await event_bus.emit("tool_call_start", event.data)
                    elif event.type == "tool_call_finished":
                        await event_bus.emit("tool_call_end", event.data)

                if event.type == "assistant_delta":
                    emitted_text_delta = True

                if event.type in {
                    "assistant_delta",
                    "tool_call_started",
                    "tool_call_finished",
                    "final",
                }:
                    cancelled_event = self._cancelled_event(effective_config.cancellation_token)
                    if cancelled_event is not None:
                        yield cancelled_event
                        return

                # --- Cost tracking on final event ---
                budget_status = "ok"
                if event.is_final and tracker is not None:
                    usage = event.data.get("usage", {})
                    metrics = event.data.get("metrics", {})
                    tokens_in = int(usage.get("input_tokens", metrics.get("tokens_in", 0)) or 0)
                    tokens_out = int(usage.get("output_tokens", metrics.get("tokens_out", 0)) or 0)
                    model = metrics.get("model", effective_config.model)
                    tracker.record(model, tokens_in, tokens_out)
                    event.data["total_cost_usd"] = tracker.total_cost_usd
                    budget_status = tracker.check_budget()

                # --- Output guardrails on final event ---
                if (
                    event.is_final
                    and effective_config.output_guardrails
                ):
                    response_text = event.data.get("text", "")
                    guard_error = await self._run_guardrails(
                        effective_config.output_guardrails,
                        response_text,
                        effective_config,
                    )
                    if guard_error is not None:
                        yield guard_error
                        return

                if event.is_final and tracker is not None:
                    if budget_status == "warning":
                        yield RuntimeEvent.status(
                            "Budget warning: "
                            f"${tracker.total_cost_usd:.4f} spent, "
                            f"{tracker.total_tokens} tokens used"
                        )
                    elif budget_status == "exceeded":
                        yield self._budget_exceeded_event(
                            tracker,
                            prefix="Cost budget exceeded after response",
                        )
                        return

                if (
                    event.is_final
                    and buffered_postprocessing
                    and not emitted_text_delta
                    and event.data.get("text", "")
                ):
                    yield RuntimeEvent.assistant_delta(str(event.data["text"]))
                    emitted_text_delta = True

                yield event

        except ThinLlmError as exc:
            # Emit any buffered retry events before the final error
            if self._retry_events:
                for retry_evt in self._retry_events:
                    yield retry_evt
                self._retry_events.clear()
            yield RuntimeEvent.error(exc.error)
        except Exception as e:
            yield RuntimeEvent.error(
                RuntimeErrorData(
                    kind="runtime_crash",
                    message=f"ThinRuntime crash: {e}",
                    recoverable=False,
                )
            )

    @staticmethod
    def _extract_last_user_text(messages: list[Message]) -> str:
        """Extract last user text."""
        for msg in reversed(messages):
            if msg.role == "user" and msg.content:
                return msg.content
        return ""

    @staticmethod
    async def _run_guardrails(
        guardrails: list[Any],
        text: str,
        config: RuntimeConfig,
    ) -> RuntimeEvent | None:
        """Run guardrails in parallel. Return error event if any fails, else None."""
        ctx = GuardrailContext(
            model=config.model,
            session_id=config.extra.get("session_id") if config.extra else None,
        )
        results: list[GuardrailResult] = await asyncio.gather(
            *[g.check(ctx, text) for g in guardrails]
        )
        for result in results:
            if not result.passed:
                return RuntimeEvent.error(
                    RuntimeErrorData(
                        kind="guardrail_tripwire",
                        message=result.reason or "Guardrail check failed",
                        recoverable=not result.tripwire,
                    )
                )
        return None

    @staticmethod
    def _cancelled_event(token: Any | None) -> RuntimeEvent | None:
        if token is None or not token.is_cancelled:
            return None
        return RuntimeEvent.error(
            RuntimeErrorData(
                kind="cancelled",
                message="Operation cancelled",
                recoverable=False,
            )
        )

    @staticmethod
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

    @staticmethod
    def _budget_exceeded_event(
        tracker: CostTracker,
        *,
        prefix: str,
    ) -> RuntimeEvent:
        return RuntimeEvent.error(
            RuntimeErrorData(
                kind="budget_exceeded",
                message=(
                    f"{prefix}: "
                    f"${tracker.total_cost_usd:.4f} spent, "
                    f"{tracker.total_tokens} tokens used"
                ),
                recoverable=False,
            )
        )

    async def _sleep_with_cancellation(self, delay: float, token: Any | None) -> None:
        if delay <= 0:
            return
        if token is None:
            await asyncio.sleep(delay)
            return

        remaining = delay
        step = 0.05
        while remaining > 0:
            self._raise_if_cancelled(token)
            wait_for = min(step, remaining)
            await asyncio.sleep(wait_for)
            remaining -= wait_for
        self._raise_if_cancelled(token)

    def _buffer_retry_status(self, attempt: int, delay: float) -> None:
        self._retry_events.append(
            RuntimeEvent.status(
                f"Retry attempt {attempt}, delay {delay:.1f}s"
            )
        )

    async def cleanup(self) -> None:
        """Cleanup."""
