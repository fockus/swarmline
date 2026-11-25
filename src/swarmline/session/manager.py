"""InMemorySessionManager - in-memory agent session management."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable
from typing import Any

from swarmline.durable.time_travel import fork, get_state_history
from swarmline.protocols.checkpoint import Checkpoint, Checkpointer
from swarmline.runtime import StreamEvent
from swarmline.runtime.types import Message, RuntimeErrorData, RuntimeEvent, ToolSpec
from swarmline.session._sync_bridge import run_awaitable_sync
from swarmline.session.backends import SessionBackend
from swarmline.session.runtime_bridge import run_runtime_turn, stream_runtime_reply
from swarmline.session.snapshot_store import SessionSnapshotStore
from swarmline.session.types import SessionKey, SessionState

logger = logging.getLogger(__name__)


class _AsyncSessionCore:
    """Async session core with persistence, TTL, and runtime execution logic."""

    def __init__(
        self,
        *,
        ttl_seconds: float,
        backend: SessionBackend | None,
        checkpointer: Checkpointer | None = None,
    ) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._ttl_seconds = ttl_seconds
        self._snapshots = SessionSnapshotStore(backend)
        self._checkpointer = checkpointer

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
        return SessionSnapshotStore.serialize_state(state)

    @staticmethod
    def deserialize_state(payload: dict[str, Any]) -> SessionState:
        """Restore a serializable snapshot into a live SessionState shell."""
        return SessionSnapshotStore.deserialize_state(payload)

    async def _load_snapshot(self, key: SessionKey) -> SessionState | None:
        state = await self._snapshots.load(self.key_str(key))
        if state is None:
            return None

        self._sessions[self.key_str(state.key)] = state
        return state

    async def _persist_state(self, state: SessionState) -> None:
        await self._snapshots.save(state, self.key_str(state.key))

    async def _delete_snapshot(self, key: SessionKey) -> None:
        await self._snapshots.delete(self.key_str(key))

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

    async def acheckpoint(
        self, key: SessionKey, *, resource_id: str | None = None
    ) -> str | None:
        """Snapshot state (opt-in); None if unconfigured/missing (REQ-014/016)."""
        if self._checkpointer is None:
            return None
        state = await self.aget(key)
        if state is None:
            return None
        payload = self.serialize_state(state)
        return await self._checkpointer.put(
            self.key_str(key), payload, resource_id=resource_id or key.user_id
        )

    async def arestore(
        self, key: SessionKey, *, checkpoint_id: str | None = None
    ) -> bool:
        """Restore session from checkpoint (opt-in); False if unconfigured/missing."""
        if self._checkpointer is None:
            return False
        ks = self.key_str(key)
        cp = await self._checkpointer.get(ks, checkpoint_id=checkpoint_id)
        if cp is None:
            return False
        await self.aregister(self.deserialize_state(dict(cp.state)))
        return True

    async def aget_state_history(self, key: SessionKey) -> list[Checkpoint]:
        """Time-travel: full checkpoint history, oldest-first; [] without a
        checkpointer configured (backward compat)."""
        if self._checkpointer is None:
            return []
        return await get_state_history(self._checkpointer, self.key_str(key))

    async def afork(self, key: SessionKey, *, checkpoint_id: str) -> str | None:
        """Time-travel: branch a new checkpoint off ``checkpoint_id``; None
        without a checkpointer configured (backward compat)."""
        if self._checkpointer is None:
            return None
        return await fork(self._checkpointer, self.key_str(key), checkpoint_id)

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
            async for event in run_runtime_turn(
                state,
                messages=messages,
                system_prompt=system_prompt,
                active_tools=active_tools,
                mode_hint=mode_hint,
            ):
                event_count += 1
                yield event
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
                async for event in stream_runtime_reply(
                    state,
                    user_text,
                    persist_state=self._persist_state,
                    session_key=self.key_str(key),
                ):
                    yield event
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
    """Compatibility facade over the async session core: async methods
    delegate directly; sync methods bridge for synchronous callers."""

    def __init__(
        self,
        ttl_seconds: float = 900.0,
        backend: SessionBackend | None = None,
        checkpointer: Checkpointer | None = None,
    ) -> None:
        self._core = _AsyncSessionCore(
            ttl_seconds=ttl_seconds, backend=backend, checkpointer=checkpointer
        )
        # Keep legacy attributes for backward compatibility with internal tests.
        self._sessions = self._core._sessions
        self._locks = self._core._locks
        self._ttl_seconds = ttl_seconds
        self._backend = backend
        self._checkpointer = checkpointer

    def _key_str(self, key: SessionKey) -> str:
        return self._core.key_str(key)

    def _get_lock(self, key: SessionKey) -> asyncio.Lock:
        return self._core.get_lock(key)

    @staticmethod
    def _run_awaitable_sync(awaitable: Awaitable[Any]) -> Any:
        """Sync bridge (body: ``session._sync_bridge``, C1.3 line-cap move)."""
        return run_awaitable_sync(awaitable)

    @staticmethod
    def _serialize_state(state: SessionState) -> dict[str, Any]:
        return _AsyncSessionCore.serialize_state(state)

    @staticmethod
    def _deserialize_state(payload: dict[str, Any]) -> SessionState:
        return _AsyncSessionCore.deserialize_state(payload)

    def get(self, key: SessionKey) -> SessionState | None:
        """Get an existing session (None if TTL expired). Sync bridge may
        block the loop if a backend is configured — prefer :meth:`aget`."""
        return self._run_awaitable_sync(self._core.aget(key))

    async def aget(self, key: SessionKey) -> SessionState | None:
        return await self._core.aget(key)

    def register(self, state: SessionState) -> None:
        """Register a session. Sync bridge may block the loop if a backend
        is configured — prefer :meth:`aregister` in async contexts."""
        self._run_awaitable_sync(self._core.aregister(state))

    async def aregister(self, state: SessionState) -> None:
        await self._core.aregister(state)

    async def acheckpoint(
        self, key: SessionKey, *, resource_id: str | None = None
    ) -> str | None:
        return await self._core.acheckpoint(key, resource_id=resource_id)

    async def arestore(
        self, key: SessionKey, *, checkpoint_id: str | None = None
    ) -> bool:
        return await self._core.arestore(key, checkpoint_id=checkpoint_id)

    async def aget_state_history(self, key: SessionKey) -> list[Checkpoint]:
        return await self._core.aget_state_history(key)

    async def afork(self, key: SessionKey, *, checkpoint_id: str) -> str | None:
        return await self._core.afork(key, checkpoint_id=checkpoint_id)

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
        """Update role/skills (True if found). Sync bridge may block the
        loop if a backend is configured — prefer :meth:`aupdate_role`."""
        return self._run_awaitable_sync(
            self._core.aupdate_role(key, role_id, skill_ids)
        )

    async def aupdate_role(
        self, key: SessionKey, role_id: str, skill_ids: list[str]
    ) -> bool:
        return await self._core.aupdate_role(key, role_id, skill_ids)
