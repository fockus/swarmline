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

from swarmline.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
    ToolSpec,
    TurnMetrics,
)

logger = logging.getLogger(__name__)


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

        logger.info("ClaudeCodeRuntime.run(): is_connected=%s", self._adapter.is_connected)
        if not self._adapter.is_connected:
            yield RuntimeEvent.error(
                RuntimeErrorData(
                    kind="runtime_crash",
                    message="SDK клиент не подключён.",
                    recoverable=False,
                )
            )
            return

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

        logger.info("ClaudeCodeRuntime.run(): передаю в adapter.stream_reply(%r)", user_text[:50])

        # Stream through the SDK
        full_text = ""
        tool_calls_count = 0
        new_messages: list[Message] = []
        result_meta: dict[str, Any] = {}

        try:
            async for stream_event in self._adapter.stream_reply(user_text):
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
                        "structured_output": getattr(stream_event, "structured_output", None),
                    }
        except Exception as e:
            logger.exception("ClaudeCodeRuntime.run(): ошибка стриминга")
            yield RuntimeEvent.error(
                RuntimeErrorData(
                    kind="runtime_crash",
                    message=f"Ошибка SDK стриминга: {e}",
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

        # Final event
        metrics = TurnMetrics(
            tool_calls_count=tool_calls_count,
            model=self._config.model,
        )
        yield RuntimeEvent.final(
            text=full_text,
            new_messages=new_messages,
            metrics=metrics,
            session_id=result_meta.get("session_id"),
            total_cost_usd=result_meta.get("total_cost_usd"),
            usage=result_meta.get("usage"),
            structured_output=result_meta.get("structured_output"),
        )

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
    - tool_use_start -> tool_call_started
    - tool_use_result -> tool_call_finished
    - error -> error
    - done -> None (we build final ourselves)
    """
        etype = stream_event.type

        if etype == "text_delta":
            return RuntimeEvent.assistant_delta(stream_event.text)

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
            return RuntimeEvent.error(
                RuntimeErrorData(
                    kind="runtime_crash",
                    message=stream_event.text,
                    recoverable=False,
                )
            )

        if etype == "done":
            return None  # Build final ourselves

        # Unknown type - status
        return RuntimeEvent.status(stream_event.text or etype)
