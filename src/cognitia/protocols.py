"""Протоколы (порты) Cognitia — ISP/DIP-совместимые интерфейсы.

Все Protocol ≤5 методов (ISP из RULES.MD).
Зависимости: только от cognitia.types и стандартной библиотеки.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any, Protocol, runtime_checkable

from cognitia.memory.types import GoalState, MemoryMessage, PhaseState, ToolEvent, UserProfile
from cognitia.types import TurnContext

# ---------------------------------------------------------------------------
# Memory — ISP: разбиваем на маленькие порты (≤4 метода каждый)
# ---------------------------------------------------------------------------


@runtime_checkable
class MessageStore(Protocol):
    """Порт: хранилище сообщений."""

    async def save_message(
        self,
        user_id: str,
        topic_id: str,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
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
    """Порт: хранилище фактов."""

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
    """Порт: хранилище rolling summary."""

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
    """Порт: хранилище целей."""

    async def save_goal(self, user_id: str, goal: GoalState) -> None: ...

    async def get_active_goal(
        self,
        user_id: str,
        topic_id: str,
    ) -> GoalState | None: ...


@runtime_checkable
class SessionStateStore(Protocol):
    """Порт: хранилище состояния сессий."""

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
    """Порт: управление пользователями."""

    async def ensure_user(self, external_id: str) -> str: ...

    async def get_user_profile(self, user_id: str) -> UserProfile: ...


@runtime_checkable
class PhaseStore(Protocol):
    """Порт: хранилище состояния фазы пользователя."""

    async def save_phase_state(
        self,
        user_id: str,
        phase: str,
        notes: str = "",
    ) -> None: ...

    async def get_phase_state(self, user_id: str) -> PhaseState | None: ...


@runtime_checkable
class ToolEventStore(Protocol):
    """Порт: хранилище событий вызовов инструментов (§9.1)."""

    async def save_tool_event(
        self,
        user_id: str,
        event: ToolEvent,
    ) -> None: ...


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------


class RuntimePort(Protocol):
    """Порт: runtime-адаптер для SDK (DIP вместо конкретного RuntimeAdapter).

    DEPRECATED: используйте AgentRuntime из cognitia.runtime.base для нового кода.
    RuntimePort сохранён для backward compat с существующим SessionManager.
    """

    @property
    def is_connected(self) -> bool: ...

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    def stream_reply(self, user_text: str) -> AsyncIterator[Any]: ...


# Re-export AgentRuntime v1 Protocol
# Определён в cognitia.runtime.base, но доступен и через protocols
import contextlib

with contextlib.suppress(ImportError):
    from cognitia.runtime.base import AgentRuntime  # noqa: F401


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


class ToolIdCodec(Protocol):
    """Порт: нормализация имён инструментов (секция 4.4)."""

    def matches(self, tool_name: str, server_id: str) -> bool: ...

    def encode(self, server_id: str, tool_name: str) -> str: ...

    def extract_server(self, tool_name: str) -> str | None: ...


class ModelSelector(Protocol):
    """Порт: выбор модели (Sonnet/Opus)."""

    def select(self, role_id: str, tool_failure_count: int = 0) -> str: ...

    def select_for_turn(
        self,
        role_id: str,
        user_text: str,
        active_skill_count: int = 0,
        tool_failure_count: int = 0,
    ) -> str: ...


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


class RoleRouter(Protocol):
    """Порт: маршрутизация пользователя к роли."""

    def resolve(
        self,
        user_text: str,
        explicit_role: str | None = None,
    ) -> str: ...


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


class ContextBuilder(Protocol):
    """Порт: сборка system_prompt."""

    async def build(self, inp: Any, **kwargs: Any) -> Any: ...


# ---------------------------------------------------------------------------
# Session Management
# ---------------------------------------------------------------------------


class SessionFactory(Protocol):
    """Порт: создание SDK-сессий (DIP для AgentService приложения)."""

    @property
    def last_prompt_hash(self) -> str: ...

    async def create(
        self,
        user_id: str,
        topic_id: str,
        role_id: str,
    ) -> Any | None: ...


class SessionManager(Protocol):
    """Порт: управление активными сессиями."""

    def get(self, key: Any) -> Any | None: ...

    def register(self, state: Any) -> None: ...

    def stream_reply(
        self,
        key: Any,
        user_text: str,
    ) -> AsyncIterator[Any]: ...

    def run_turn(
        self,
        key: Any,
        *,
        messages: list[Any],
        system_prompt: str,
        active_tools: list[Any],
        mode_hint: str | None = None,
    ) -> AsyncIterator[Any]: ...

    async def close(self, key: Any) -> None: ...

    async def close_all(self) -> None: ...


class SessionRehydrator(Protocol):
    """Порт: восстановление состояния сессии."""

    async def build_rehydration_payload(
        self,
        ctx: TurnContext,
    ) -> Mapping[str, Any]: ...


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class RoleSkillsProvider(Protocol):
    """Порт: маппинг роль → skills + local tools."""

    def get_skills(self, role_id: str) -> list[str]: ...

    def get_local_tools(self, role_id: str) -> list[str]: ...


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class LocalToolResolver(Protocol):
    """Порт: резолвер локальных инструментов (ISP, 2 метода).

    Приложение реализует этот Protocol, чтобы библиотека могла получить
    callable по имени tool_name. Библиотека не знает о конкретных инструментах.
    """

    def resolve(self, tool_name: str) -> Any | None:
        """Получить callable для локального инструмента по имени.

        Returns:
            Callable или None если инструмент не найден.
        """
        ...

    def list_tools(self) -> list[str]:
        """Список доступных локальных инструментов."""
        ...


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


@runtime_checkable
class SummaryGenerator(Protocol):
    """Порт: генерация rolling summary из истории сообщений (ISP, 1 метод)."""

    def summarize(self, messages: list[MemoryMessage]) -> str: ...
