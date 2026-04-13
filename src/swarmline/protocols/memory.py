"""Memory protocols -- ISP-compliant storage interfaces (<=5 methods each)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from swarmline.memory.types import GoalState, MemoryMessage, PhaseState, ToolEvent, UserProfile


@runtime_checkable
class MessageStore(Protocol):
    """Port: message storage."""

    async def save_message(
        self,
        user_id: str,
        topic_id: str,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        *,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
        content_blocks: list[dict[str, Any]] | None = None,
    ) -> None: ...

    async def get_messages(
        self,
        user_id: str,
        topic_id: str,
        limit: int = 10,
    ) -> list[MemoryMessage]: ...

    async def count_messages(self, user_id: str, topic_id: str) -> int: ...

    async def delete_messages_before(
        self,
        user_id: str,
        topic_id: str,
        keep_last: int = 10,
    ) -> int: ...


@runtime_checkable
class FactStore(Protocol):
    """Port: fact storage."""

    async def upsert_fact(
        self,
        user_id: str,
        key: str,
        value: Any,
        topic_id: str | None = None,
        source: str = "user",
    ) -> None: ...

    async def get_facts(
        self,
        user_id: str,
        topic_id: str | None = None,
    ) -> dict[str, Any]: ...


@runtime_checkable
class SummaryStore(Protocol):
    """Port: rolling summary storage."""

    async def save_summary(
        self,
        user_id: str,
        topic_id: str,
        summary: str,
        messages_covered: int,
    ) -> None: ...

    async def get_summary(self, user_id: str, topic_id: str) -> str | None: ...


@runtime_checkable
class GoalStore(Protocol):
    """Port: goal storage."""

    async def save_goal(self, user_id: str, goal: GoalState) -> None: ...

    async def get_active_goal(
        self,
        user_id: str,
        topic_id: str,
    ) -> GoalState | None: ...


@runtime_checkable
class SessionStateStore(Protocol):
    """Port: session state storage."""

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
    ) -> None: ...

    async def get_session_state(
        self,
        user_id: str,
        topic_id: str,
    ) -> dict[str, Any] | None: ...


@runtime_checkable
class UserStore(Protocol):
    """Port: user management."""

    async def ensure_user(self, external_id: str) -> str: ...

    async def get_user_profile(self, user_id: str) -> UserProfile: ...


@runtime_checkable
class PhaseStore(Protocol):
    """Port: user phase state storage."""

    async def save_phase_state(
        self,
        user_id: str,
        phase: str,
        notes: str = "",
    ) -> None: ...

    async def get_phase_state(self, user_id: str) -> PhaseState | None: ...


@runtime_checkable
class ToolEventStore(Protocol):
    """Port: tool event storage."""

    async def save_tool_event(
        self,
        user_id: str,
        event: ToolEvent,
    ) -> None: ...


@runtime_checkable
class SummaryGenerator(Protocol):
    """Port: rolling summary generation from message history (ISP, 1 method)."""

    def summarize(self, messages: list[MemoryMessage]) -> str: ...
