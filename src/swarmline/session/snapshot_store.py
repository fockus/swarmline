"""Snapshot codec/persistence helpers for SessionManager."""

from __future__ import annotations

import time
from typing import Any

from swarmline.runtime.types import Message, ToolSpec
from swarmline.session.backends import SessionBackend
from swarmline.session.types import SessionKey, SessionState


class SessionSnapshotStore:
    """Owns session snapshot serialization and backend persistence."""

    def __init__(self, backend: SessionBackend | None) -> None:
        self._backend = backend

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
            # Serialize as wall-clock so it survives process restarts.
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
            # Convert wall-clock back to monotonic for TTL checks.
            last_activity_at=time.monotonic()
            - (time.time() - float(payload.get("last_activity_at", time.time()))),
            delegated_from=payload.get("delegated_from"),
            delegation_summary=payload.get("delegation_summary"),
            delegation_turn_count=int(payload.get("delegation_turn_count", 0)),
            pending_delegation=payload.get("pending_delegation"),
        )

    async def load(self, key: str) -> SessionState | None:
        """Load a snapshot and rehydrate it into SessionState."""
        if self._backend is None:
            return None

        payload = await self._backend.load(key)
        if payload is None:
            return None

        state = self.deserialize_state(payload)
        state.is_rehydrated = True
        return state

    async def save(self, state: SessionState, key: str) -> None:
        """Persist a state snapshot if backend persistence is configured."""
        if self._backend is None:
            return
        await self._backend.save(key, self.serialize_state(state))

    async def delete(self, key: str) -> None:
        """Delete a persisted snapshot if backend persistence is configured."""
        if self._backend is None:
            return
        await self._backend.delete(key)
