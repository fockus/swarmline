"""SessionRehydrator - restore session state from Postgres (architecture section 8.4).

Contract: build_rehydration_payload(ctx: TurnContext) -> Mapping
Restores: role_id, active_skill_ids, summary, last_N messages, goals, phase, prompt_hash.

ISP/DIP: depends on small Protocols (<=5 methods each), not a monolithic provider.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from swarmline.memory.semantic_recall import SemanticRecall
from swarmline.memory.types import MemoryMessage
from swarmline.protocols import (
    GoalStore,
    MessageStore,
    PhaseStore,
    SessionStateStore,
    SummaryStore,
)
from swarmline.types import TurnContext


class DefaultSessionRehydrator:
    """Postgres rehydration implementation.

    Order (from section 8.4):
    1. Session state (role_id, skills) from the topics table
    2. Rolling summary
    3. Last N messages (current topic)
    4. Active goal + phase_state

    Conflict resolution: summary vs last_N -> last_N wins.

    ISP: depends on 5 small protocols rather than a monolithic MemoryProvider.
    """

    def __init__(
        self,
        messages: MessageStore,
        summaries: SummaryStore,
        goals: GoalStore,
        sessions: SessionStateStore,
        phases: PhaseStore,
        last_n_messages: int = 10,
        semantic_recall: SemanticRecall | None = None,
    ) -> None:
        self._messages = messages
        self._summaries = summaries
        self._goals = goals
        self._sessions = sessions
        self._phases = phases
        self._last_n = last_n_messages
        self._semantic_recall = semantic_recall

    async def build_rehydration_payload(self, ctx: TurnContext) -> dict[str, Any]:
        """Build the full rehydration payload (§8.4).

        Order:
        1. Session state (role_id, skills) from the topics table
        2. Rolling summary
        3. Last N messages (current topic)
        4. Active goal + phase_state
        """
        # 1. Session state from the database
        session_state = await self._sessions.get_session_state(
            ctx.user_id, ctx.topic_id
        )

        if session_state:
            role_id = session_state["role_id"]
            active_skill_ids = session_state.get("active_skill_ids", [])
            prompt_hash = session_state.get("prompt_hash", "")
        else:
            # No database data available - fall back to ctx
            role_id = ctx.role_id
            active_skill_ids = (
                list(ctx.active_skill_ids) if ctx.active_skill_ids else []
            )
            prompt_hash = ""

        # 2. Summary
        summary = await self._summaries.get_summary(ctx.user_id, ctx.topic_id)

        # 3. Last N messages
        last_messages = await self._messages.get_messages(
            ctx.user_id, ctx.topic_id, limit=self._last_n
        )

        # 4. Active goal
        goal = await self._goals.get_active_goal(ctx.user_id, ctx.topic_id)

        # 5. Phase state
        phase_state = await self._phases.get_phase_state(ctx.user_id)

        payload: dict[str, Any] = {
            "role_id": role_id,
            "active_skill_ids": active_skill_ids,
            "prompt_hash": prompt_hash,
            "summary": summary,
            "last_messages": last_messages,
            "goal": goal,
            "phase_state": phase_state,
        }

        # 6. Semantic recall (Stage C2.2, opt-in) -- additive: the "recalled"
        # key is present ONLY when a semantic_recall was injected, so the
        # default (None) payload stays byte-identical to pre-C2.2 behavior.
        if self._semantic_recall is not None:
            recall_query = self._extract_last_user_text(last_messages).strip()
            # Guard at the wiring boundary: an empty/whitespace query short-
            # circuits to [] WITHOUT awaiting arecall (SemanticRecall.arecall
            # already guards this internally too, but skipping the call here
            # avoids an unnecessary embed/store round-trip on a blank turn).
            if recall_query:
                payload["recalled"] = await self._semantic_recall.arecall(recall_query)
            else:
                payload["recalled"] = []

        return payload

    @staticmethod
    def _extract_last_user_text(messages: Sequence[MemoryMessage]) -> str:
        """Last user-role message's content in ``messages`` (the query
        source for semantic recall) -- "" if none (empty query -> arecall
        returns [] without embedding/querying, see SemanticRecall.arecall)."""
        for msg in reversed(messages):
            if msg.role == "user" and msg.content:
                return msg.content
        return ""
