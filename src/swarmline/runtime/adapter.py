"""Adapter module."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    Message,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from claude_agent_sdk.types import StreamEvent as SdkStreamEvent

_TASK_STARTED_MESSAGE = "TaskStartedMessage"
_TASK_PROGRESS_MESSAGE = "TaskProgressMessage"
_TASK_NOTIFICATION_MESSAGE = "TaskNotificationMessage"

logger = logging.getLogger(__name__)


@dataclass
class StreamEvent:
    """Stream Event implementation."""

    type: str  # 'text_delta' | 'tool_use_start' | 'tool_use_result' | 'status' | 'done' | 'error'
    text: str = ""
    tool_name: str = ""
    tool_input: dict[str, Any] | None = None
    tool_result: str = ""
    correlation_id: str = ""
    tool_error: bool = False
    is_final: bool = False

    session_id: str | None = None
    total_cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    structured_output: Any = None


def _extract_partial_text_delta(message: SdkStreamEvent) -> str | None:
    """Extract text delta from raw SDK StreamEvent."""
    raw_event = getattr(message, "event", None)
    if not isinstance(raw_event, dict):
        return None
    if raw_event.get("type") != "content_block_delta":
        return None
    delta = raw_event.get("delta")
    if not isinstance(delta, dict):
        return None
    if delta.get("type") != "text_delta":
        return None
    text = delta.get("text")
    return text if isinstance(text, str) and text else None


def _format_system_message(message: SystemMessage) -> str | None:
    """Format system message."""
    message_type = message.__class__.__name__
    if message_type == _TASK_STARTED_MESSAGE:
        description = getattr(message, "description", None)
        if isinstance(description, str) and description:
            return f"Task started: {description}"

    if message_type == _TASK_PROGRESS_MESSAGE:
        description = getattr(message, "description", None)
        if isinstance(description, str) and description:
            last_tool_name = getattr(message, "last_tool_name", None)
            if isinstance(last_tool_name, str) and last_tool_name:
                return f"Task progress: {description} ({last_tool_name})"
            return f"Task progress: {description}"

    if message_type == _TASK_NOTIFICATION_MESSAGE:
        status = getattr(message, "status", None)
        summary = getattr(message, "summary", None)
        if isinstance(status, str) and isinstance(summary, str) and summary:
            return f"Task {status}: {summary}"

    description = getattr(message, "description", None)
    if isinstance(description, str) and description:
        return description

    data = getattr(message, "data", None)
    if isinstance(data, dict):
        for key in ("message", "summary", "description"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value

    subtype = getattr(message, "subtype", None)
    return subtype if isinstance(subtype, str) and subtype else None


class RuntimeAdapter:
    """Runtime Adapter implementation."""

    CONNECT_TIMEOUT_SECONDS = 60.0

    def __init__(self, options: ClaudeAgentOptions) -> None:
        self._options = options
        self._client: ClaudeSDKClient | None = None
        self._tool_names_by_id: dict[str, str] = {}

    async def connect(self) -> None:
        """Connect."""
        from dataclasses import replace

        if self._options.stderr is None:
            self._options = replace(self._options, stderr=self._on_stderr)

        t0 = time.monotonic()
        self._client = ClaudeSDKClient(options=self._options)
        try:
            await asyncio.wait_for(
                self._client.connect(),
                timeout=self.CONNECT_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            elapsed = time.monotonic() - t0
            logger.error(
                "Таймаут подключения Claude SDK (%.1fs > %.1fs). "
                "Возможно, MCP серверы недоступны или медленно инициализируются.",
                elapsed,
                self.CONNECT_TIMEOUT_SECONDS,
            )

            with suppress(Exception):
                await self._client.disconnect()
            self._client = None
            raise TimeoutError(
                f"Claude SDK subprocess не инициализировался за {self.CONNECT_TIMEOUT_SECONDS}s"
            ) from None

        elapsed = time.monotonic() - t0
        logger.info("Claude SDK subprocess запущен за %.2fs", elapsed)

    async def _reconnect(self) -> None:
        """Reconnect."""
        logger.warning("Переподключение Claude SDK subprocess...")
        if self._client:
            with suppress(Exception):
                await self._client.disconnect()
            self._client = None

        t0 = time.monotonic()
        self._client = ClaudeSDKClient(options=self._options)
        try:
            await asyncio.wait_for(
                self._client.connect(),
                timeout=self.CONNECT_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            elapsed = time.monotonic() - t0
            logger.error("Таймаут reconnect (%.1fs)", elapsed)
            with suppress(Exception):
                await self._client.disconnect()
            self._client = None
            raise TimeoutError("Claude SDK reconnect timeout") from None

        elapsed = time.monotonic() - t0
        logger.info("Claude SDK subprocess переподключён за %.2fs", elapsed)

    async def disconnect(self) -> None:
        """Disconnect."""
        if self._client:
            await self._client.disconnect()
            self._client = None

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    def _require_client(self) -> ClaudeSDKClient:
        """Require client."""
        if not self._client:
            raise RuntimeError("SDK клиент не подключён")
        return self._client

    async def set_model(self, model: str) -> None:
        """Set model."""
        client = self._require_client()
        await client.set_model(model)

    async def interrupt(self) -> None:
        """Interrupt."""
        client = self._require_client()
        await client.interrupt()

    async def set_permission_mode(self, mode: str) -> None:
        """Set permission mode."""
        client = self._require_client()
        await client.set_permission_mode(mode)  # type: ignore[arg-type]

    async def get_mcp_status(self) -> dict[str, Any]:
        """Get mcp status."""
        client = self._require_client()
        return await client.get_mcp_status()  # ty: ignore[invalid-return-type]  # claude_agent_sdk McpStatusResponse is dict-compatible at runtime

    async def rewind_files(self, user_message_id: str) -> None:
        """Rewind files."""
        client = self._require_client()
        await client.rewind_files(user_message_id)

    async def stream_reply(self, user_text: str) -> AsyncIterator[StreamEvent]:
        """Stream reply."""
        if not self._client:
            yield StreamEvent(type="error", text="SDK клиент не подключён")
            return

        logger.info("stream_reply: отправка query (len=%d)", len(user_text))
        for attempt in range(2):
            try:
                await self._client.query(user_text)
                logger.info("stream_reply: query отправлен")
                break
            except (BrokenPipeError, OSError, ConnectionError) as exc:
                if attempt == 0:
                    logger.warning(
                        "BrokenPipe при query (attempt=%d): %s. Reconnect...",
                        attempt,
                        exc,
                    )
                    await self._reconnect()
                else:
                    logger.error("BrokenPipe при query после reconnect: %s", exc)
                    yield StreamEvent(
                        type="error",
                        text=f"SDK subprocess упал: {exc}",
                    )
                    return
            except Exception as exc:
                logger.error("Ошибка query: %s", exc)
                yield StreamEvent(type="error", text=f"Ошибка SDK query: {exc}")
                return

        logger.info("stream_reply: ожидание receive_response()")
        full_text = ""
        msg_count = 0
        result_meta: dict[str, Any] = {}
        saw_partial_text = False
        saw_result_message = False
        self._tool_names_by_id.clear()
        try:
            async for message in self._client.receive_response():
                msg_count += 1
                msg_type = type(message).__name__
                logger.info("stream_reply: msg #%d type=%s", msg_count, msg_type)

                if isinstance(message, ResultMessage):
                    saw_result_message = True
                    result_meta = {
                        "session_id": getattr(message, "session_id", None),
                        "total_cost_usd": getattr(message, "total_cost_usd", None),
                        "usage": getattr(message, "usage", None),
                        "structured_output": getattr(
                            message, "structured_output", None
                        ),
                    }

                if self._options.include_partial_messages and isinstance(
                    message,
                    SdkStreamEvent,
                ):
                    partial_text = _extract_partial_text_delta(message)
                    if partial_text:
                        saw_partial_text = True
                        full_text += partial_text
                        yield StreamEvent(type="text_delta", text=partial_text)
                    continue

                async for event in self._process_message(
                    message,
                    suppress_text=saw_partial_text,
                ):
                    if event.type == "text_delta":
                        full_text += event.text
                    yield event
        except (BrokenPipeError, OSError, ConnectionError) as exc:
            logger.error("BrokenPipe при чтении ответа: %s", exc)
            yield StreamEvent(
                type="error",
                text=f"SDK subprocess упал при чтении: {exc}",
            )

            with suppress(Exception):
                await self._reconnect()
            return
        except Exception as exc:
            logger.error("Ошибка чтения ответа SDK: %s", exc)
            yield StreamEvent(type="error", text=f"Ошибка SDK: {exc}")
            return

        if not saw_result_message:
            yield StreamEvent(
                type="error",
                text="SDK stream completed without final ResultMessage",
            )
            return

        yield StreamEvent(
            type="done",
            text=full_text,
            is_final=True,
            session_id=result_meta.get("session_id"),
            total_cost_usd=result_meta.get("total_cost_usd"),
            usage=result_meta.get("usage"),
            structured_output=result_meta.get("structured_output"),
        )

    @staticmethod
    def _on_stderr(line: str) -> None:
        """On stderr."""
        stripped = line.strip()
        if not stripped:
            return

        low = stripped.lower()
        if any(
            kw in low
            for kw in ("error", "fail", "timeout", "refused", "broken", "exception")
        ):
            logger.warning("claude-cli stderr: %s", stripped)
        else:
            logger.info("claude-cli stderr: %s", stripped)

    async def _process_message(
        self,
        message: Message,
        *,
        suppress_text: bool = False,
    ) -> AsyncIterator[StreamEvent]:
        """Process message."""
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    if not suppress_text:
                        yield StreamEvent(type="text_delta", text=block.text)
                elif isinstance(block, ThinkingBlock):
                    logger.debug(
                        "ThinkingBlock (len=%d)",
                        len(block.thinking),
                    )
                elif isinstance(block, ToolUseBlock):
                    correlation_id = (
                        getattr(block, "id", "")
                        or getattr(block, "tool_use_id", "")
                        or ""
                    )
                    if correlation_id:
                        self._tool_names_by_id[correlation_id] = block.name
                    yield StreamEvent(
                        type="tool_use_start",
                        tool_name=block.name,
                        tool_input=block.input,
                        correlation_id=correlation_id,
                    )
                elif isinstance(block, ToolResultBlock):
                    result_text = (
                        str(block.content) if hasattr(block, "content") else ""
                    )
                    correlation_id = getattr(block, "tool_use_id", "") or ""
                    tool_name = self._tool_names_by_id.pop(correlation_id, "")
                    yield StreamEvent(
                        type="tool_use_result",
                        tool_name=tool_name,
                        tool_result=result_text,
                        correlation_id=correlation_id,
                        tool_error=bool(getattr(block, "is_error", False)),
                    )
        elif isinstance(message, SystemMessage):
            status_text = _format_system_message(message)
            if status_text:
                yield StreamEvent(type="status", text=status_text)
        elif isinstance(message, ResultMessage):
            pass
