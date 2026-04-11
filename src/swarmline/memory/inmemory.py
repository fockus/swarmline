"""InMemoryMemoryProvider - dev-mode memory provider without a DB (R-521).

All data is stored in process-memory dicts.
Ideal for development, tests, and demos without Postgres.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from swarmline.memory.types import GoalState, MemoryMessage, PhaseState, ToolEvent, UserProfile


class InMemoryMemoryProvider:
    """Pluggable memory provider for dev/test without a DB.

    Implements the full MemoryProvider Protocol.
    """

    def __init__(self) -> None:
        # messages: (user_id, topic_id) -> list[MemoryMessage]
        self._messages: dict[tuple[str, str], list[MemoryMessage]] = defaultdict(list)
        # facts: (user_id, topic_id|None) -> {key: value}
        self._facts: dict[tuple[str, str | None], dict[str, Any]] = defaultdict(dict)
        # summaries: (user_id, topic_id) -> summary_text
        self._summaries: dict[tuple[str, str], str] = {}
        # goals: (user_id, topic_id) -> GoalState
        self._goals: dict[tuple[str, str], GoalState] = {}
        # session_state: (user_id, topic_id) -> dict
        self._session_states: dict[tuple[str, str], dict[str, Any]] = {}
        # users: external_id -> True
        self._users: set[str] = set()
        # phase_state: user_id -> PhaseState
        self._phase_states: dict[str, PhaseState] = {}
        # tool_events: bounded deque to prevent memory leak
        from collections import deque
        self._tool_events: deque[dict[str, Any]] = deque(maxlen=10000)

    @staticmethod
    def _copy_session_state(state: dict[str, Any]) -> dict[str, Any]:
        copied = dict(state)
        copied["active_skill_ids"] = list(state.get("active_skill_ids", []))
        return copied

    # --- Messages ---

    async def save_message(
        self,
        user_id: str,
        topic_id: str,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        """Save a message."""
        key = (user_id, topic_id)
        self._messages[key].append(MemoryMessage(role=role, content=content, tool_calls=tool_calls))

    async def get_messages(
        self,
        user_id: str,
        topic_id: str,
        limit: int = 10,
    ) -> list[MemoryMessage]:
        """Get the last N messages."""
        key = (user_id, topic_id)
        msgs = self._messages[key]
        return msgs[-limit:]

    async def count_messages(self, user_id: str, topic_id: str) -> int:
        """Message count."""
        return len(self._messages[(user_id, topic_id)])

    async def delete_messages_before(
        self,
        user_id: str,
        topic_id: str,
        keep_last: int = 10,
    ) -> int:
        """Delete old messages."""
        key = (user_id, topic_id)
        msgs = self._messages[key]
        to_delete = max(0, len(msgs) - keep_last)
        if to_delete > 0:
            self._messages[key] = msgs[-keep_last:]
        return to_delete

    # --- Facts ---

    async def upsert_fact(
        self,
        user_id: str,
        key: str,
        value: Any,
        topic_id: str | None = None,
        source: str = "user",
    ) -> None:
        """Save a fact."""
        fk = (user_id, topic_id)
        self._facts[fk][key] = value

    async def get_facts(
        self,
        user_id: str,
        topic_id: str | None = None,
    ) -> dict[str, Any]:
        """Get facts: global + topic-scoped."""
        result: dict[str, Any] = {}
        # Global
        result.update(self._facts.get((user_id, None), {}))
        # Topic-scoped
        if topic_id:
            result.update(self._facts.get((user_id, topic_id), {}))
        return result

    # --- Summaries ---

    async def save_summary(
        self,
        user_id: str,
        topic_id: str,
        summary: str,
        messages_covered: int,
    ) -> None:
        """Save a summary."""
        self._summaries[(user_id, topic_id)] = summary

    async def get_summary(self, user_id: str, topic_id: str) -> str | None:
        """Get a summary."""
        return self._summaries.get((user_id, topic_id))

    # --- Users ---

    async def ensure_user(self, external_id: str) -> str:
        """Create a user."""
        self._users.add(external_id)
        return external_id

    # --- Goals ---

    async def save_goal(self, user_id: str, goal: GoalState) -> None:
        """Save a goal."""
        self._goals[(user_id, goal.goal_id)] = goal

    async def get_active_goal(self, user_id: str, topic_id: str) -> GoalState | None:
        """Get the active goal."""
        return self._goals.get((user_id, topic_id))

    # --- Session state ---

    async def save_session_state(
        self,
        user_id: str,
        topic_id: str,
        role_id: str,
        active_skill_ids: list[str],
        prompt_hash: str = "",
        *,
        delegated_from: str | None = None,
        delegation_turn_count: int = 0,
        pending_delegation: str | None = None,
        delegation_summary: str | None = None,
    ) -> None:
        """Save session state."""
        state = {
            "role_id": role_id,
            "active_skill_ids": list(active_skill_ids),
            "prompt_hash": prompt_hash,
            "delegated_from": delegated_from,
            "delegation_turn_count": delegation_turn_count,
            "pending_delegation": pending_delegation,
            "delegation_summary": delegation_summary,
        }
        self._session_states[(user_id, topic_id)] = self._copy_session_state(state)

    async def get_session_state(
        self,
        user_id: str,
        topic_id: str,
    ) -> dict[str, Any] | None:
        """Get session state."""
        state = self._session_states.get((user_id, topic_id))
        if state is None:
            return None
        return self._copy_session_state(state)

    # --- Profile ---

    async def get_user_profile(self, user_id: str) -> UserProfile:
        """Get the profile."""
        facts = await self.get_facts(user_id, topic_id=None)
        return UserProfile(user_id=user_id, facts=facts)

    # --- Phase state ---

    async def save_phase_state(
        self,
        user_id: str,
        phase: str,
        notes: str = "",
    ) -> None:
        """Save the phase."""
        self._phase_states[user_id] = PhaseState(
            user_id=user_id,
            phase=phase,
            notes=notes,
        )

    async def get_phase_state(self, user_id: str) -> PhaseState | None:
        """Get the current phase."""
        return self._phase_states.get(user_id)

    # --- Tool events (§9.1) ---

    async def save_tool_event(
        self,
        user_id: str,
        event: ToolEvent,
    ) -> None:
        """Save a tool invocation event."""
        self._tool_events.append(
            {
                "user_id": user_id,
                "topic_id": event.topic_id,
                "tool_name": event.tool_name,
                "input_json": event.input_json,
                "output_json": event.output_json,
                "latency_ms": event.latency_ms,
            }
        )
