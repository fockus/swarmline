"""Runtime module."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator, Callable
from functools import partial
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from swarmline.hooks.dispatcher import HookDispatcher
    from swarmline.hooks.registry import HookRegistry
    from swarmline.policy.tool_policy import DefaultToolPolicy

from swarmline.runtime.cost import CostTracker, load_pricing
from swarmline.runtime.thin.builtin_tools import create_thin_builtin_tools
from swarmline.runtime.thin.errors import ThinLlmError
from swarmline.runtime.thin.executor import ToolExecutor
from swarmline.runtime.thin.helpers import _should_buffer_postprocessing
from swarmline.runtime.thin.llm_client import default_llm_call
from swarmline.runtime.thin.runtime_support import (
    auto_wrap_retriever,
    budget_exceeded_event,
    cancelled_event,
    extract_last_user_text,
    make_default_llm_call,
    run_guardrails,
    wrap_user_llm_call,
    wrap_with_event_bus,
)
from swarmline.runtime.thin.modes import detect_mode
from swarmline.runtime.thin.strategies import (
    run_conversational,
    run_planner,
    run_react,
)
from swarmline.runtime.types import (
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
        hook_registry: HookRegistry | None = None,
        tool_policy: DefaultToolPolicy | None = None,
        subagent_config: Any | None = None,
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

        # Hook dispatch (optional)
        self._hook_dispatcher = self._build_hook_dispatcher(hook_registry)

        # Merge user local_tools with sandbox built-in executors
        merged_local_tools = dict(local_tools or {})
        _builtin_specs, builtin_executors = create_thin_builtin_tools(sandbox)
        for name, executor in builtin_executors.items():
            # User tools take priority over built-ins
            if name not in merged_local_tools:
                merged_local_tools[name] = executor

        # Subagent tool wiring (spawn_agent)
        self._subagent_tool_spec: ToolSpec | None = None
        self._subagent_orchestrator: Any | None = None
        self._subagent_config_obj: Any | None = None
        if subagent_config is not None:
            from swarmline.orchestration.thin_subagent import ThinSubagentOrchestrator
            from swarmline.runtime.thin.subagent_tool import (
                SUBAGENT_TOOL_SPEC,
                create_subagent_executor,
            )

            self._subagent_orchestrator = ThinSubagentOrchestrator(
                max_concurrent=subagent_config.max_concurrent,
                llm_call=raw_llm_call,
                local_tools=merged_local_tools,
                mcp_servers=mcp_servers,
                runtime_config=self._config,
            )
            self._subagent_config_obj = subagent_config
            # Initial executor with builtin specs only; run() updates with actual active_tools
            initial_tool_specs = list(_builtin_specs.values())
            subagent_executor = create_subagent_executor(
                self._subagent_orchestrator, subagent_config,
                initial_tool_specs, current_depth=0,
            )
            merged_local_tools["spawn_agent"] = subagent_executor
            self._subagent_tool_spec = SUBAGENT_TOOL_SPEC

        self._executor = ToolExecutor(
            local_tools=merged_local_tools,
            mcp_servers=mcp_servers,
            hook_dispatcher=self._hook_dispatcher,
            tool_policy=tool_policy,
        )

        # Cost tracking
        self._cost_tracker: CostTracker | None = None
        if self._config.cost_budget is not None:
            self._cost_tracker = CostTracker(
                budget=self._config.cost_budget,
                pricing=load_pricing(),
            )

    @staticmethod
    def _build_hook_dispatcher(hook_registry: HookRegistry | None) -> HookDispatcher | None:
        """Build HookDispatcher from HookRegistry if provided."""
        if hook_registry is None:
            return None
        from swarmline.hooks.dispatcher import DefaultHookDispatcher

        return DefaultHookDispatcher(hook_registry)

    def _auto_wrap_retriever(self) -> None:
        """Auto-wrap config.retriever into input_filters if not already present."""
        auto_wrap_retriever(self._config)

    @staticmethod
    def _wrap_user_llm_call(user_fn: Callable[..., Any]) -> Callable[..., Any]:
        """Wrap a user-provided llm_call to accept (and forward) the ``config`` kwarg.

        User callables that already accept ``config`` get it as-is.
        Legacy callables that don't accept ``config`` have it silently stripped
        so existing code keeps working without modification.
        """
        return wrap_user_llm_call(user_fn)

    def _make_default_llm_call(self) -> Callable[..., Any]:
        """Make default llm call.

        Returns a callable that accepts an optional ``config`` keyword.
        When provided, the per-call config is forwarded to ``default_llm_call``
        instead of the constructor config, enabling per-call model/provider overrides.
        """
        return make_default_llm_call(self._config, default_llm_call)

    def _wrap_with_event_bus(self, llm_call: Callable[..., Any]) -> Callable[..., Any]:
        """Wrap LLM call with EventBus emit for LLM_call_start/LLM_call_end.

        Forwards the ``config`` keyword so that per-call overrides reach the
        underlying ``llm_call`` and event metadata reflects the actual model.
        """
        return wrap_with_event_bus(llm_call, self._config)

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

        # --- Subagent tool: append spec to active_tools + update executor with full tool list ---
        if self._subagent_tool_spec is not None:
            active_tools = [*active_tools, self._subagent_tool_spec]
            # Update executor with actual active_tools for correct tool inheritance
            if self._subagent_orchestrator is not None and self._subagent_config_obj is not None:
                from swarmline.runtime.thin.subagent_tool import create_subagent_executor

                updated_executor = create_subagent_executor(
                    self._subagent_orchestrator, self._subagent_config_obj,
                    active_tools, current_depth=0,
                )
                self._executor._local_tools["spawn_agent"] = updated_executor

        # --- UserPromptSubmit hook ---
        if self._hook_dispatcher is not None:
            transformed = await self._hook_dispatcher.dispatch_user_prompt(user_text)
            if transformed != user_text:
                user_text = transformed
                if messages and messages[-1].role == "user":
                    messages = list(messages)
                    messages[-1] = Message(role="user", content=user_text)

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
        last_result_text = ""

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

                # Track last result text for Stop hook
                if event.is_final:
                    last_result_text = event.data.get("text", "")

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

            # --- Stop hook on normal completion ---
            if self._hook_dispatcher is not None:
                await self._hook_dispatcher.dispatch_stop(result_text=last_result_text)

        except ThinLlmError as exc:
            # Emit any buffered retry events before the final error
            if self._retry_events:
                for retry_evt in self._retry_events:
                    yield retry_evt
                self._retry_events.clear()
            yield RuntimeEvent.error(exc.error)
            if self._hook_dispatcher is not None:
                await self._hook_dispatcher.dispatch_stop(result_text=str(exc.error.message))
        except Exception as e:
            yield RuntimeEvent.error(
                RuntimeErrorData(
                    kind="runtime_crash",
                    message=f"ThinRuntime crash: {e}",
                    recoverable=False,
                )
            )
            if self._hook_dispatcher is not None:
                await self._hook_dispatcher.dispatch_stop(result_text=str(e))

    @staticmethod
    def _extract_last_user_text(messages: list[Message]) -> str:
        """Extract last user text."""
        return extract_last_user_text(messages)

    @staticmethod
    async def _run_guardrails(
        guardrails: list[Any],
        text: str,
        config: RuntimeConfig,
    ) -> RuntimeEvent | None:
        """Run guardrails in parallel. Return error event if any fails, else None."""
        return await run_guardrails(guardrails, text, config)

    @staticmethod
    def _cancelled_event(token: Any | None) -> RuntimeEvent | None:
        return cancelled_event(token)

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
        return budget_exceeded_event(tracker, prefix=prefix)

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
