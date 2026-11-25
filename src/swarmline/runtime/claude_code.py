"""ClaudeCodeRuntime - wrapper around Claude-agent-SDK for the AgentRuntime v1 contract.

Ownership: the runtime does not own history. The SDK manages the conversation
internally (warm handle), but the source of truth is SessionManager.

Logic:
1. Extract the last user message from messages
2. Delegate to the existing RuntimeAdapter.stream_reply(user_text)
3. Convert StreamEvent -> RuntimeEvent
4. Collect full_text and build new_messages in the final event
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from swarmline.observability.redaction import redact_secrets
from swarmline.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
    ToolSpec,
    TurnMetrics,
)

logger = logging.getLogger(__name__)


def _usage_int(usage: Any, key: str) -> int:
    """Read a token counter from a usage dict, defensively."""
    if not isinstance(usage, dict):
        return 0
    try:
        return int(usage.get(key) or 0)
    except (TypeError, ValueError):
        return 0


class ClaudeCodeRuntime:
    """AgentRuntime wrapper around Claude-agent-SDK.

    Uses the existing RuntimeAdapter to communicate with the SDK.
    The SDK manages its own history internally (warm subprocess handle).
    """

    def __init__(
        self,
        config: RuntimeConfig | None = None,
        adapter: Any = None,
    ) -> None:
        """Initialize the runtime.

        Args:
          config: Runtime configuration (model and budgets are used).
          adapter: Existing RuntimeAdapter (DIP: injected from outside).
               If None, it is created on first use.
        """
        self._config = config or RuntimeConfig(runtime_name="claude_sdk")
        self._adapter = adapter
        self._cancel_requested = False
        self._interrupt_task: Any = None

    @property
    def adapter(self) -> Any:
        """Access the underlying RuntimeAdapter."""
        return self._adapter

    @adapter.setter
    def adapter(self, value: Any) -> None:
        self._adapter = value

    async def run(
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        config: RuntimeConfig | None = None,
        mode_hint: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Execute one turn through Claude-agent-SDK.

        Extracts the last user message, delegates to the SDK,
        and converts StreamEvent -> RuntimeEvent.
        """
        logger.info(
            "ClaudeCodeRuntime.run(): начало (adapter=%s)",
            type(self._adapter).__name__ if self._adapter else "None",
        )

        if self._adapter is None:
            logger.error("ClaudeCodeRuntime.run(): adapter is None")
            yield RuntimeEvent.error(
                RuntimeErrorData(
                    kind="runtime_crash",
                    message="RuntimeAdapter не инициализирован. Создайте сессию через SessionFactory.",
                    recoverable=False,
                )
            )
            return

        logger.info(
            "ClaudeCodeRuntime.run(): is_connected=%s", self._adapter.is_connected
        )
        if not self._adapter.is_connected:
            yield RuntimeEvent.error(
                RuntimeErrorData(
                    kind="runtime_crash",
                    message="SDK клиент не подключён.",
                    recoverable=False,
                )
            )
            return

        self._cancel_requested = False

        # Extract the last user message
        user_text = self._extract_last_user_text(messages)
        if not user_text:
            logger.error("ClaudeCodeRuntime.run(): нет user message в messages")
            yield RuntimeEvent.error(
                RuntimeErrorData(
                    kind="runtime_crash",
                    message="Нет user message в messages.",
                    recoverable=False,
                )
            )
            return

        logger.info(
            "ClaudeCodeRuntime.run(): передаю в adapter.stream_reply(%r)",
            user_text[:50],
        )

        # Stream through the SDK
        full_text = ""
        tool_calls_count = 0
        new_messages: list[Message] = []
        result_meta: dict[str, Any] = {}

        try:
            async for stream_event in self._adapter.stream_reply(user_text):
                if self._cancel_requested:
                    yield RuntimeEvent.error(
                        RuntimeErrorData(
                            kind="cancelled",
                            message="Run cancelled by user.",
                            recoverable=False,
                        )
                    )
                    return
                runtime_event = self._convert_event(stream_event)
                if runtime_event is not None:
                    if runtime_event.type == "error":
                        yield runtime_event
                        return

                    # Accumulate text
                    if runtime_event.type == "assistant_delta":
                        full_text += runtime_event.data.get("text", "")
                    elif runtime_event.type == "tool_call_started":
                        tool_calls_count += 1

                    # Do not forward done - we build the final event ourselves
                    if stream_event.type != "done":
                        yield runtime_event
                if stream_event.type == "done":
                    result_meta = {
                        "session_id": getattr(stream_event, "session_id", None),
                        "total_cost_usd": getattr(stream_event, "total_cost_usd", None),
                        "usage": getattr(stream_event, "usage", None),
                        "structured_output": getattr(
                            stream_event, "structured_output", None
                        ),
                    }
        except Exception as e:
            redacted = redact_secrets(str(e))
            logger.error(
                "ClaudeCodeRuntime.run(): ошибка стриминга exc_type=%s error=%s",
                type(e).__name__,
                redacted,
            )
            yield RuntimeEvent.error(
                RuntimeErrorData(
                    kind="runtime_crash",
                    message=f"Ошибка SDK стриминга ({type(e).__name__}): {redacted}",
                    recoverable=False,
                )
            )
            return

        # Build new_messages
        if full_text:
            new_messages.append(
                Message(
                    role="assistant",
                    content=full_text,
                )
            )

        # Final event — mirror native usage into TurnMetrics so consumers
        # reading metrics see the same numbers as the usage dict (parity
        # with thin/deepagents/openai_agents/pi_sdk).
        usage = result_meta.get("usage")
        metrics = TurnMetrics(
            tokens_in=_usage_int(usage, "input_tokens"),
            tokens_out=_usage_int(usage, "output_tokens"),
            tool_calls_count=tool_calls_count,
            model=self._config.model,
        )
        yield RuntimeEvent.final(
            text=full_text,
            new_messages=new_messages,
            metrics=metrics,
            session_id=result_meta.get("session_id"),
            total_cost_usd=result_meta.get("total_cost_usd"),
            usage=usage,
            structured_output=result_meta.get("structured_output"),
        )

    def cancel(self) -> None:
        """Request cancellation: native SDK interrupt plus a cooperative flag.

        The AgentRuntime protocol's cancel() is synchronous, while the SDK's
        interrupt is async — schedule it on the running loop when possible
        and rely on the cooperative flag checked in the stream loop otherwise.
        """
        import asyncio

        self._cancel_requested = True
        adapter = self._adapter
        if adapter is None or not getattr(adapter, "is_connected", False):
            return
        interrupt = getattr(adapter, "interrupt", None)
        if interrupt is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        async def _safe_interrupt() -> None:
            try:
                await interrupt()
            except Exception as exc:
                logger.warning("SDK interrupt failed after cancel(): %s", exc)

        task = loop.create_task(_safe_interrupt())
        # Keep a reference so the task isn't garbage-collected mid-flight.
        self._interrupt_task = task
        task.add_done_callback(lambda _t: setattr(self, "_interrupt_task", None))

    async def cleanup(self) -> None:
        """Disconnect the SDK adapter."""
        if self._adapter and self._adapter.is_connected:
            await self._adapter.disconnect()

    @staticmethod
    def _extract_last_user_text(messages: list[Message]) -> str:
        """Extract the text of the last user message."""
        for msg in reversed(messages):
            if msg.role == "user" and msg.content:
                return msg.content
        return ""

    @staticmethod
    def _convert_event(stream_event: Any) -> RuntimeEvent | None:
        """Convert StreamEvent -> RuntimeEvent.

        Mapping:
        - text_delta -> assistant_delta
        - thinking_delta -> thinking_delta
        - tool_use_start -> tool_call_started
        - tool_use_result -> tool_call_finished
        - error -> error
        - done -> None (we build final ourselves)
        """
        etype = stream_event.type

        if etype == "text_delta":
            return RuntimeEvent.assistant_delta(stream_event.text)

        if etype == "thinking_delta":
            return RuntimeEvent.thinking_delta(stream_event.text)

        if etype == "tool_use_start":
            return RuntimeEvent.tool_call_started(
                name=stream_event.tool_name,
                args=stream_event.tool_input,
                correlation_id=stream_event.correlation_id or None,
            )

        if etype == "tool_use_result":
            return RuntimeEvent.tool_call_finished(
                name=stream_event.tool_name or "",
                correlation_id=stream_event.correlation_id or "",
                ok=not bool(getattr(stream_event, "tool_error", False)),
                result_summary=stream_event.tool_result,
            )

        if etype == "error":
            message = redact_secrets(stream_event.text)
            return RuntimeEvent.error(
                RuntimeErrorData(
                    kind="runtime_crash",
                    message=message,
                    recoverable=False,
                )
            )

        if etype == "done":
            return None  # Build final ourselves

        # Unknown type - status
        return RuntimeEvent.status(stream_event.text or etype)
