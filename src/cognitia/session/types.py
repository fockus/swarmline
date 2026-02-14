"""Типы для управления сессиями."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cognitia.protocols import RuntimePort
    from cognitia.runtime.base import AgentRuntime
    from cognitia.runtime.types import Message, RuntimeConfig, ToolSpec


@dataclass(frozen=True)
class SessionKey:
    """Ключ сессии = (пользователь, тема)."""

    user_id: str
    topic_id: str

    def __str__(self) -> str:
        return f"{self.user_id}:{self.topic_id}"


@dataclass
class SessionState:
    """Состояние активной сессии."""

    key: SessionKey
    adapter: RuntimePort | None = None
    # Новый runtime-контракт (AgentRuntime v1). SessionManager использует его в приоритете.
    runtime: AgentRuntime | None = None
    runtime_config: RuntimeConfig | None = None
    system_prompt: str = ""
    active_tools: list[ToolSpec] = field(default_factory=list)
    role_id: str = "default"
    active_skill_ids: list[str] = field(default_factory=list)
    # История для legacy stream_reply-path (runtime без adapter).
    runtime_messages: list[Message] = field(default_factory=list)
    is_rehydrated: bool = False
    tool_failure_count: int = 0

    # --- Session TTL ---
    # Время последней активности (monotonic clock). Используется SessionManager для eviction.
    last_activity_at: float = field(default_factory=time.monotonic)

    # --- Orchestrator delegation ---
    # role_id из которого пришла делегация (None = нет активной делегации)
    delegated_from: str | None = None
    # Summary, переданный при делегировании / возврате
    delegation_summary: str | None = None
    # Счётчик turn'ов внутри делегированной роли (для автовозврата)
    delegation_turn_count: int = 0
    # Отложенная делегация: role_id для следующего turn'а (установлен delegate_to_role)
    pending_delegation: str | None = None
