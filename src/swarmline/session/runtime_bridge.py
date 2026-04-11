"""Runtime execution helpers for SessionManager."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from swarmline.runtime import StreamEvent
from swarmline.runtime.types import Message, RuntimeErrorData, RuntimeEvent, ToolSpec
from swarmline.session.types import SessionState

logger = logging.getLogger(__name__)


def _message_from_payload(payload: Any) -> Message:
    """Normalize a runtime history payload into a Message."""
    if isinstance(payload, Message):
        return payload
    if isinstance(payload, dict):
        return Message(**payload)
    raise TypeError(f"Unsupported runtime message payload: {type(payload)!r}")


def _messages_from_payloads(payloads: Any) -> list[Message]:
    """Normalize a list of runtime history payloads."""
    if not payloads:
        return []
    return [_message_from_payload(payload) for payload in payloads]


async def run_runtime_turn(
    state: SessionState,
    *,
    messages: list[Message],
    system_prompt: str,
    active_tools: list[ToolSpec],
    mode_hint: str | None = None,
) -> AsyncIterator[RuntimeEvent]:
    """Execute a runtime turn and normalize runtime crashes into error events."""
    if state.runtime is None:
        yield RuntimeEvent.error(
            RuntimeErrorData(
                kind="runtime_crash",
                message="Runtime not initialized in session",
                recoverable=False,
            )
        )
        return

    try:
        async for event in state.runtime.run(
            messages=messages,
            system_prompt=system_prompt,
            active_tools=active_tools,
            config=state.runtime_config,
            mode_hint=mode_hint,
        ):
            yield event
    except Exception as exc:
        yield RuntimeEvent.error(
            RuntimeErrorData(
                kind="runtime_crash",
                message=f"Runtime execution failed: {exc}",
                recoverable=False,
            )
        )


async def stream_runtime_reply(
    state: SessionState,
    user_text: str,
    *,
    persist_state: Callable[[SessionState], Awaitable[None]],
    session_key: str,
) -> AsyncIterator[StreamEvent]:
    """Bridge AgentRuntime events to legacy StreamEvent semantics."""
    if state.runtime is None:
        yield StreamEvent(type="error", text="Runtime not initialized in session")
        return

    state.runtime_messages.append(Message(role="user", content=user_text))
    await persist_state(state)

    full_text = ""
    assistant_emitted = False
    final_data: dict[str, Any] = {}
    saw_terminal_event = False

    try:
        async for runtime_event in state.runtime.run(
            messages=list(state.runtime_messages),
            system_prompt=state.system_prompt,
            active_tools=state.active_tools,
            config=state.runtime_config,
        ):
            if runtime_event.type == "assistant_delta":
                text = str(runtime_event.data.get("text", ""))
                full_text += text
                assistant_emitted = True
                yield StreamEvent(type="text_delta", text=text)
            elif runtime_event.type == "tool_call_started":
                yield StreamEvent(
                    type="tool_use_start",
                    tool_name=str(runtime_event.data.get("name", "")),
                    tool_input=runtime_event.data.get("args"),
                )
            elif runtime_event.type == "tool_call_finished":
                yield StreamEvent(
                    type="tool_use_result",
                    tool_name=str(runtime_event.data.get("name", "")),
                    tool_result=str(runtime_event.data.get("result_summary", "")),
                )
            elif runtime_event.type == "error":
                saw_terminal_event = True
                yield StreamEvent(
                    type="error",
                    text=str(runtime_event.data.get("message", "Runtime error")),
                )
                return
            elif runtime_event.type == "final":
                saw_terminal_event = True
                final_data = runtime_event.data
                final_text = str(runtime_event.data.get("text", ""))
                if final_text and not full_text:
                    full_text = final_text
                    yield StreamEvent(type="text_delta", text=final_text)
                    assistant_emitted = True
                final_new_messages = _messages_from_payloads(
                    runtime_event.data.get("new_messages")
                )
                if final_new_messages:
                    state.runtime_messages.extend(final_new_messages)
                    await persist_state(state)
                elif assistant_emitted and full_text:
                    state.runtime_messages.append(
                        Message(role="assistant", content=full_text)
                    )
                    await persist_state(state)
                done_event = StreamEvent(type="done", text=full_text, is_final=True)
                done_event.session_id = final_data.get("session_id")
                done_event.total_cost_usd = final_data.get("total_cost_usd")
                done_event.usage = final_data.get("usage")
                done_event.structured_output = final_data.get("structured_output")
                done_event.native_metadata = final_data.get("native_metadata")
                yield done_event
                return
    except Exception as exc:
        logger.exception("stream_runtime_reply[%s]: runtime.run() failed", session_key)
        yield StreamEvent(type="error", text=f"Runtime execution failed: {exc}")
        return

    if not saw_terminal_event:
        yield StreamEvent(
            type="error",
            text="runtime stream ended without final RuntimeEvent",
        )
        return

    if assistant_emitted and full_text:
        state.runtime_messages.append(Message(role="assistant", content=full_text))
        await persist_state(state)
    yield StreamEvent(type="done", text=full_text, is_final=True)
