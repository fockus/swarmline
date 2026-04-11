"""Routing protocols -- role routing, context building, model selection."""

from __future__ import annotations

from typing import Any, Protocol


class RoleRouter(Protocol):
    """Port: user-to-role routing."""

    def resolve(
        self,
        user_text: str,
        explicit_role: str | None = None,
    ) -> str: ...


class ContextBuilder(Protocol):
    """Port: system_prompt assembly."""

    async def build(self, inp: Any, **kwargs: Any) -> Any: ...


class ModelSelector(Protocol):
    """Port: model selection (Sonnet/Opus)."""

    def select(self, role_id: str, tool_failure_count: int = 0) -> str: ...

    def select_for_turn(
        self,
        role_id: str,
        user_text: str,
        active_skill_count: int = 0,
        tool_failure_count: int = 0,
    ) -> str: ...


class RoleSkillsProvider(Protocol):
    """Port: role -> skills + local tools mapping."""

    def get_skills(self, role_id: str) -> list[str]: ...

    def get_local_tools(self, role_id: str) -> list[str]: ...
