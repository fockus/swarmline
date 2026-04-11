"""InMemorySessionManager - in-memory agent session management."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import AsyncIterator, Awaitable
from typing import Any

from cognitia.runtime import StreamEvent
from cognitia.runtime.types import Message, RuntimeErrorData, RuntimeEvent, ToolSpec
from cognitia.session.backends import SessionBackend
from cognitia.session.types import SessionKey, SessionState

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


class _AsyncSessionCore:
    """Async session core with persistence, TTL, and runtime execution logic."""

    def __init__(
        self,
        *,
        ttl_seconds: float,
        backend: SessionBackend | None,
    ) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._ttl_seconds = ttl_seconds
        self._backend = backend

    def key_str(self, key: SessionKey) -> str:
        return str(key)

    def get_lock(self, key: SessionKey) -> asyncio.Lock:
        """Get or create a lock for the session."""
        ks = self.key_str(key)
        if ks not in self._locks:
            self._locks[ks] = asyncio.Lock()
        return self._locks[ks]

    @staticmethod
    def serialize_state(state: SessionState) -> dict[str, Any]:
        """Persist only serializable session fields."""
        return {
            "key": {
                "user_id": state.key.user_id,
                "topic_id": state.key.topic_id,
            },
            "system_prompt": state.system_prompt,
            "active_tools": [tool.to_dict() for tool in state.active_tools],
            "role_id": state.role_id,
            "active_skill_ids": list(state.active_skill_ids),
            "runtime_messages": [
                message.to_dict() for message in state.runtime_messages
            ],
            "is_rehydrated": state.is_rehydrated,
            "tool_failure_count": state.tool_failure_count,
            # Serialize as wall-clock so it survives process restarts
            "last_activity_at": time.time()
            - (time.monotonic() - state.last_activity_at),
            "delegated_from": state.delegated_from,
            "delegation_summary": state.delegation_summary,
            "delegation_turn_count": state.delegation_turn_count,
            "pending_delegation": state.pending_delegation,
        }

    @staticmethod
    def deserialize_state(payload: dict[str, Any]) -> SessionState:
        """Restore a serializable snapshot into a live SessionState shell."""
        key_payload = payload.get("key", {})
        return SessionState(
            key=SessionKey(
                user_id=str(key_payload.get("user_id", "")),
                topic_id=str(key_payload.get("topic_id", "")),
            ),
            system_prompt=str(payload.get("system_prompt", "")),
            active_tools=[
                ToolSpec(**tool_payload)
                for tool_payload in payload.get("active_tools", [])
            ],
            role_id=str(payload.get("role_id", "default")),
            active_skill_ids=list(payload.get("active_skill_ids", [])),
            runtime_messages=[
                Message(**message_payload)
                for message_payload in payload.get("runtime_messages", [])
            ],
            is_rehydrated=bool(payload.get("is_rehydrated", False)),
            tool_failure_count=int(payload.get("tool_failure_count", 0)),
            # Convert wall-clock back to monotonic for TTL checks
            last_activity_at=time.monotonic()
            - (time.time() - float(payload.get("last_activity_at", time.time()))),
            delegated_from=payload.get("delegated_from"),
            delegation_summary=payload.get("delegation_summary"),
            delegation_turn_count=int(payload.get("delegation_turn_count", 0)),
            pending_delegation=payload.get("pending_delegation"),
        )

    async def _load_snapshot(self, key: SessionKey) -> SessionState | None:
        if self._backend is None:
            return None

        payload = await self._backend.load(self.key_str(key))
        if payload is None:
            return None

        state = self.deserialize_state(payload)
        state.is_rehydrated = True
        self._sessions[self.key_str(state.key)] = state
        return state

    async def _persist_state(self, state: SessionState) -> None:
        if self._backend is None:
            return
        await self._backend.save(self.key_str(state.key), self.serialize_state(state))

    async def _delete_snapshot(self, key: SessionKey) -> None:
        if self._backend is None:
            return
        await self._backend.delete(self.key_str(key))

    async def _evict_if_expired(
        self,
        key: SessionKey,
        state: SessionState,
        *,
        action_name: str,
    ) -> SessionState | None:
        ks = self.key_str(key)
        if (
            self._ttl_seconds > 0
            and (time.monotonic() - state.last_activity_at) > self._ttl_seconds
        ):
            logger.info(
                "%s[%s]: session expired (TTL=%.0fs), evicting",
                action_name,
                ks,
                self._ttl_seconds,
            )
            self._sessions.pop(ks, None)
            await self._delete_snapshot(key)
            return None
        return state

    async def aget(self, key: SessionKey) -> SessionState | None:
        """Async version of get. Awaits backend directly, never blocks."""
        ks = self.key_str(key)
        state = self._sessions.get(ks)
        if state is None:
            state = await self._load_snapshot(key)
            if state is None:
                return None
        return await self._evict_if_expired(key, state, action_name="aget")

    async def aregister(self, state: SessionState) -> None:
        """Register a session and persist it if a backend is configured."""
        state.last_activity_at = time.monotonic()
        self._sessions[self.key_str(state.key)] = state
        await self._persist_state(state)

    async def close(self, key: SessionKey) -> None:
        """Close the session and disconnect the runtime/adapter."""
        ks = self.key_str(key)
        state = self._sessions.pop(ks, None)
        if state:
            if state.runtime is not None:
                await state.runtime.cleanup()
            elif state.adapter and state.adapter.is_connected:
                await state.adapter.disconnect()
        await self._delete_snapshot(key)
        self._locks.pop(ks, None)

    async def close_all(self) -> None:
        """Close all sessions. Backend snapshots are preserved for rehydration."""
        keys = list(self._sessions.keys())
        for ks in keys:
            state = self._sessions.pop(ks, None)
            if state:
                if state.runtime is not None:
                    await state.runtime.cleanup()
                elif state.adapter and state.adapter.is_connected:
                    await state.adapter.disconnect()
        self._locks.clear()

    async def run_turn(
        self,
        key: SessionKey,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        mode_hint: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Execute a turn through AgentRuntime v1 (new contract)."""
        ks = self.key_str(key)
        lock = self.get_lock(key)
        logger.info("run_turn[%s]: waiting for lock (locked=%s)", ks, lock.locked())
        async with lock:
            logger.info("run_turn[%s]: lock acquired", ks)
            state = await self.aget(key)
            if state:
                state.last_activity_at = time.monotonic()
                await self._persist_state(state)
            if not state:
                logger.error("run_turn[%s]: session not found", ks)
                yield RuntimeEvent.error(
                    RuntimeErrorData(
                        kind="runtime_crash",
                        message="Session not found",
                        recoverable=False,
                    )
                )
                return

            if state.runtime is None:
                logger.error("run_turn[%s]: runtime is None", ks)
                yield RuntimeEvent.error(
                    RuntimeErrorData(
                        kind="runtime_crash",
                        message="Runtime not initialized in session",
                        recoverable=False,
                    )
                )
                return

            logger.info(
                "run_turn[%s]: calling runtime.run() (type=%s, user_text_len=%d)",
                ks,
                type(state.runtime).__name__,
                len(messages[-1].content) if messages else 0,
            )
            event_count = 0
            try:
                async for event in state.runtime.run(
                    messages=messages,
                    system_prompt=system_prompt,
                    active_tools=active_tools,
                    config=state.runtime_config,
                    mode_hint=mode_hint,
                ):
                    event_count += 1
                    yield event
            except Exception as exc:
                logger.exception("run_turn[%s]: runtime.run() failed", ks)
                yield RuntimeEvent.error(
                    RuntimeErrorData(
                        kind="runtime_crash",
                        message=f"Runtime execution failed: {exc}",
                        recoverable=False,
                    )
                )
            logger.info("run_turn[%s]: completed, events=%d", ks, event_count)
        logger.info("run_turn[%s]: lock released", ks)

    async def stream_reply(self, key: SessionKey, user_text: str) -> AsyncIterator[Any]:
        """Legacy API: send a message and stream the response."""
        lock = self.get_lock(key)
        async with lock:
            state = await self.aget(key)
            if not state:
                yield StreamEvent(type="error", text="Session not found")
                return
            state.last_activity_at = time.monotonic()
            await self._persist_state(state)

            # New runtime path (fallback for places that still call stream_reply).
            if state.runtime is not None and state.adapter is None:
                state.runtime_messages.append(Message(role="user", content=user_text))
                await self._persist_state(state)
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
                                tool_result=str(
                                    runtime_event.data.get("result_summary", "")
                                ),
                            )
                        elif runtime_event.type == "error":
                            saw_terminal_event = True
                            yield StreamEvent(
                                type="error",
                                text=str(
                                    runtime_event.data.get("message", "Runtime error")
                                ),
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
                                await self._persist_state(state)
                            elif assistant_emitted and full_text:
                                state.runtime_messages.append(
                                    Message(role="assistant", content=full_text)
                                )
                                await self._persist_state(state)
                            done_event = StreamEvent(
                                type="done", text=full_text, is_final=True
                            )
                            done_event.session_id = final_data.get("session_id")
                            done_event.total_cost_usd = final_data.get("total_cost_usd")
                            done_event.usage = final_data.get("usage")
                            done_event.structured_output = final_data.get(
                                "structured_output"
                            )
                            done_event.native_metadata = final_data.get(
                                "native_metadata"
                            )
                            yield done_event
                            return
                except Exception as exc:
                    logger.exception(
                        "stream_reply[%s]: runtime.run() failed", self.key_str(key)
                    )
                    yield StreamEvent(
                        type="error", text=f"Runtime execution failed: {exc}"
                    )
                    return

                if not saw_terminal_event:
                    yield StreamEvent(
                        type="error",
                        text="runtime stream ended without final RuntimeEvent",
                    )
                    return

                if assistant_emitted and full_text:
                    state.runtime_messages.append(
                        Message(role="assistant", content=full_text)
                    )
                    await self._persist_state(state)
                yield StreamEvent(type="done", text=full_text, is_final=True)
                return

            if not state.adapter or not state.adapter.is_connected:
                yield StreamEvent(type="error", text="SDK not connected")
                return

            async for event in state.adapter.stream_reply(user_text):
                yield event

    def list_sessions(self) -> list[SessionKey]:
        return [state.key for state in self._sessions.values()]

    async def aupdate_role(
        self, key: SessionKey, role_id: str, skill_ids: list[str]
    ) -> bool:
        """Update the session role and skills."""
        state = await self.aget(key)
        if not state:
            return False
        state.role_id = role_id
        state.active_skill_ids = skill_ids
        await self._persist_state(state)
        return True


class InMemorySessionManager:
    """Compatibility facade over the async session core.

    Async methods delegate directly to the core. Sync methods keep the legacy
    bridge for callers that still use the manager from synchronous code.
    """

    def __init__(
        self,
        ttl_seconds: float = 900.0,
        backend: SessionBackend | None = None,
    ) -> None:
        self._core = _AsyncSessionCore(ttl_seconds=ttl_seconds, backend=backend)
        # Keep legacy attributes for backward compatibility with internal tests.
        self._sessions = self._core._sessions
        self._locks = self._core._locks
        self._ttl_seconds = ttl_seconds
        self._backend = backend

    def _key_str(self, key: SessionKey) -> str:
        return self._core.key_str(key)

    def _get_lock(self, key: SessionKey) -> asyncio.Lock:
        return self._core.get_lock(key)

    @staticmethod
    def _run_awaitable_sync(awaitable: Awaitable[Any]) -> Any:
        """Synchronously execute a coroutine from sync manager APIs."""

        async def _await_value() -> Any:
            return await awaitable

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_await_value())

        result: dict[str, Any] = {}
        error: dict[str, BaseException] = {}

        def runner() -> None:
            try:
                result["value"] = asyncio.run(_await_value())
            except BaseException as exc:  # pragma: no cover - defensive bridge
                error["error"] = exc

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join()

        if "error" in error:
            raise error["error"]
        return result.get("value")

    @staticmethod
    def _serialize_state(state: SessionState) -> dict[str, Any]:
        return _AsyncSessionCore.serialize_state(state)

    @staticmethod
    def _deserialize_state(payload: dict[str, Any]) -> SessionState:
        return _AsyncSessionCore.deserialize_state(payload)

    def get(self, key: SessionKey) -> SessionState | None:
        """Get an existing session. Returns None if TTL has expired.

        Note: if a backend is configured, this uses a sync bridge that may
        block the event loop. Prefer :meth:`aget` in async contexts.
        """
        return self._run_awaitable_sync(self._core.aget(key))

    async def aget(self, key: SessionKey) -> SessionState | None:
        return await self._core.aget(key)

    def register(self, state: SessionState) -> None:
        """Register a new session.

        Note: if a backend is configured, this uses a sync bridge that may
        block the event loop. Prefer :meth:`aregister` in async contexts.
        """
        self._run_awaitable_sync(self._core.aregister(state))

    async def aregister(self, state: SessionState) -> None:
        await self._core.aregister(state)

    async def close(self, key: SessionKey) -> None:
        await self._core.close(key)

    async def close_all(self) -> None:
        await self._core.close_all()

    async def run_turn(
        self,
        key: SessionKey,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        mode_hint: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        async for event in self._core.run_turn(
            key,
            messages=messages,
            system_prompt=system_prompt,
            active_tools=active_tools,
            mode_hint=mode_hint,
        ):
            yield event

    async def stream_reply(self, key: SessionKey, user_text: str) -> AsyncIterator[Any]:
        async for event in self._core.stream_reply(key, user_text):
            yield event

    def list_sessions(self) -> list[SessionKey]:
        """List active sessions."""
        return self._core.list_sessions()

    def update_role(self, key: SessionKey, role_id: str, skill_ids: list[str]) -> bool:
        """Update the session role and skills. Returns True if the session is found.

        Note: if a backend is configured, this uses a sync bridge that may
        block the event loop. Prefer :meth:`aupdate_role` in async contexts.
        """
        return self._run_awaitable_sync(
            self._core.aupdate_role(key, role_id, skill_ids)
        )

    async def aupdate_role(
        self, key: SessionKey, role_id: str, skill_ids: list[str]
    ) -> bool:
        return await self._core.aupdate_role(key, role_id, skill_ids)
