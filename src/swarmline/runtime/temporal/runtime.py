"""TemporalAgentRuntime — client facade implementing ``AgentRuntime``.

Starts one ``AgentLoopWorkflow`` per ``run()`` and yields RuntimeEvents:

- **buffered mode** (default): awaits the workflow result and replays the
  events it accumulated, then the final/error event. No extra infrastructure.
- **streaming mode** (``options.stream_events=True`` + ``event_bus``): yields
  events live from the worker-side relay while the workflow runs, then the
  final/error event from the result. Requires an EventBus reachable from
  both workers and this client (Redis/NATS).

The runtime holds no tools and no LLM credentials — those live on the
Temporal workers (``swarmline.runtime.temporal.worker``).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

from swarmline.domain_types import RUNTIME_ERROR_KINDS
from swarmline.runtime.temporal.client import connect_client, workflow_id_for_run
from swarmline.runtime.temporal.options import TemporalRuntimeOptions
from swarmline.runtime.temporal.payloads import (
    WORKFLOW_NAME,
    AgentRunInput,
    AgentRunResult,
    message_from_dict,
    message_to_dict,
)
from swarmline.runtime.temporal.stream import RunEventSubscriber
from swarmline.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
    ToolSpec,
)

_STREAM_POLL_SECONDS = 0.1


class TemporalAgentRuntime:
    """AgentRuntime implementation backed by Temporal workflows.

    Parameters
    ----------
    config:
        RuntimeConfig; ``model``/``max_iterations``/``max_tool_calls`` are
        forwarded into the workflow input. ``config.extra["temporal"]`` may
        carry :class:`TemporalRuntimeOptions` fields.
    options:
        Explicit options (take precedence over ``config.extra``).
    client:
        Pre-connected ``temporalio.client.Client`` (or a duck-typed stand-in
        exposing ``start_workflow``). When ``None``, a client is connected
        lazily from ``options`` on first run.
    event_bus:
        EventBus used as the streaming relay subscriber side. Required for
        ``options.stream_events=True``.
    """

    def __init__(
        self,
        config: RuntimeConfig | None = None,
        *,
        options: TemporalRuntimeOptions | None = None,
        client: Any = None,
        event_bus: Any = None,
    ) -> None:
        self._config = config or RuntimeConfig(runtime_name="temporal")
        self._options = options or TemporalRuntimeOptions.from_config(self._config)
        self._client = client
        self._event_bus = event_bus
        self._current_handle: Any = None

    async def _ensure_client(self) -> Any:
        if self._client is None:
            self._client = await connect_client(self._options)
        return self._client

    def _build_input(
        self,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        config: RuntimeConfig,
        run_id: str,
    ) -> AgentRunInput:
        streaming = self._options.stream_events and self._event_bus is not None
        return AgentRunInput(
            messages=[message_to_dict(m) for m in messages],
            system_prompt=system_prompt,
            tools=[t.to_dict() for t in active_tools],
            run_id=run_id,
            model=config.model,
            max_iterations=config.max_iterations,
            max_tool_calls=config.max_tool_calls,
            stream_events=streaming,
            llm_timeout_seconds=self._options.llm_timeout_seconds,
            tool_timeout_seconds=self._options.tool_timeout_seconds,
            llm_retry_attempts=self._options.llm_retry_attempts,
            tool_retry_attempts=self._options.tool_retry_attempts,
            approval_timeout_seconds=self._options.approval_timeout_seconds,
            use_reference_history=self._options.use_reference_history,
            continue_after_iterations=self._options.continue_as_new_after_iterations,
        )

    @staticmethod
    def _error_event(kind: str, message: str) -> RuntimeEvent:
        if kind not in RUNTIME_ERROR_KINDS:
            kind = "runtime_crash"
        return RuntimeEvent.error(
            RuntimeErrorData(kind=kind, message=message, recoverable=False)
        )

    def _result_events(
        self, result: AgentRunResult, *, include_streamed: bool
    ) -> list[RuntimeEvent]:
        """Terminal events from a workflow result (+ replay in buffered mode)."""
        events: list[RuntimeEvent] = []
        if include_streamed:
            events.extend(
                RuntimeEvent(type=e["type"], data=e.get("data", {}))
                for e in result.events
            )
        if result.status == "ok":
            events.append(
                RuntimeEvent.final(
                    text=result.text,
                    new_messages=[message_from_dict(m) for m in result.new_messages],
                    metrics=None,
                )
            )
        else:
            events.append(
                self._error_event(
                    result.error_kind, result.error_message or "Agent run failed"
                )
            )
        return events

    async def run(
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        config: RuntimeConfig | None = None,
        mode_hint: str | None = None,  # noqa: ARG002 — mode is tool-derived in the workflow
    ) -> AsyncIterator[RuntimeEvent]:
        """Start a durable run and yield its events."""
        effective = config or self._config
        run_id = uuid.uuid4().hex

        try:
            client = await self._ensure_client()
        except Exception as exc:  # noqa: BLE001
            yield self._error_event(
                "runtime_crash", f"Temporal connection failed: {exc}"
            )
            return

        inp = self._build_input(
            messages, system_prompt, active_tools, effective, run_id
        )

        subscriber = self._make_subscriber(run_id) if inp.stream_events else None

        try:
            try:
                handle = await client.start_workflow(
                    WORKFLOW_NAME,
                    inp,
                    id=workflow_id_for_run(self._options, run_id),
                    task_queue=self._options.task_queue,
                    result_type=AgentRunResult,
                )
            except Exception as exc:  # noqa: BLE001
                yield self._error_event(
                    "runtime_crash", f"Failed to start workflow: {exc}"
                )
                return

            async for event in self._pump(handle, subscriber):
                yield event
        finally:
            self._current_handle = None
            if subscriber is not None:
                subscriber.detach()

    async def attach(self, run_id: str) -> AsyncIterator[RuntimeEvent]:
        """Reattach to a running (or finished) run by ``run_id``.

        Yields the run's remaining events exactly like ``run()``: live from
        the relay in streaming mode, or the buffered replay + final event
        once the workflow completes. Safe after a client crash or from a
        different process — durability lives in the workflow.
        """
        try:
            client = await self._ensure_client()
        except Exception as exc:  # noqa: BLE001
            yield self._error_event(
                "runtime_crash", f"Temporal connection failed: {exc}"
            )
            return

        streaming = self._options.stream_events and self._event_bus is not None
        subscriber = self._make_subscriber(run_id) if streaming else None
        try:
            handle = client.get_workflow_handle(
                workflow_id_for_run(self._options, run_id),
                result_type=AgentRunResult,
            )
            async for event in self._pump(handle, subscriber):
                yield event
        finally:
            self._current_handle = None
            if subscriber is not None:
                subscriber.detach()

    def _make_subscriber(self, run_id: str) -> RunEventSubscriber:
        subscriber = RunEventSubscriber(self._event_bus, run_id)
        subscriber.attach()
        return subscriber

    async def _pump(
        self, handle: Any, subscriber: RunEventSubscriber | None
    ) -> AsyncIterator[RuntimeEvent]:
        """Yield relay events (streaming) until the workflow result lands."""
        self._current_handle = handle

        result_task = asyncio.ensure_future(self._await_result(handle))
        try:
            if subscriber is not None:
                while True:
                    event = await subscriber.next(timeout=_STREAM_POLL_SECONDS)
                    if event is not None:
                        yield RuntimeEvent(
                            type=event["type"], data=event.get("data", {})
                        )
                        continue
                    if result_task.done():
                        for late in subscriber.drain():
                            yield RuntimeEvent(
                                type=late["type"], data=late.get("data", {})
                            )
                        break
            outcome = await result_task
        finally:
            if not result_task.done():
                result_task.cancel()

        if isinstance(outcome, AgentRunResult):
            for event in self._result_events(
                outcome, include_streamed=subscriber is None
            ):
                yield event
        else:
            yield outcome  # already a RuntimeEvent error

    async def _await_result(self, handle: Any) -> AgentRunResult | RuntimeEvent:
        """Await the workflow result, mapping failures to error events."""
        try:
            return await handle.result()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            if self._is_cancellation(exc):
                return self._error_event("cancelled", "Operation cancelled")
            return self._error_event("runtime_crash", f"Workflow failed: {exc}")

    @staticmethod
    def _is_cancellation(exc: Exception) -> bool:
        seen: Any = exc
        while seen is not None:
            if type(seen).__name__ == "CancelledError":
                return True
            seen = getattr(seen, "cause", None) or getattr(seen, "__cause__", None)
        return False

    def cancel(self) -> None:
        """Request cancellation of the in-flight workflow (cooperative)."""
        handle = self._current_handle
        if handle is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(handle.cancel())

    async def cleanup(self) -> None:
        """Release resources (the Temporal client needs no explicit close)."""

    async def __aenter__(self) -> TemporalAgentRuntime:
        """Enter async context manager."""
        return self

    async def __aexit__(self, *exc: Any) -> None:
        """Exit async context manager."""
        await self.cleanup()
