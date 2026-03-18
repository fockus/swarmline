"""Session management types."""

from __future__ import annotations

import time
import warnings
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cognitia.protocols import RuntimePort
    from cognitia.runtime.base import AgentRuntime
    from cognitia.runtime.types import Message, RuntimeConfig, ToolSpec


@dataclass(frozen=True)
class SessionKey:
    """Session key = (user, topic)."""

    user_id: str
    topic_id: str

    def __str__(self) -> str:
        return f"{self._escape_component(self.user_id)}:{self._escape_component(self.topic_id)}"

    @staticmethod
    def _escape_component(value: str) -> str:
        return value.replace("%", "%25").replace(":", "%3A")


@dataclass
class SessionState:
    """Active session state."""

    key: SessionKey
    adapter: RuntimePort | None = None
    # AgentRuntime v1 contract. SessionManager prefers this path.
    runtime: AgentRuntime | None = None
    runtime_config: RuntimeConfig | None = None
    system_prompt: str = ""
    active_tools: list[ToolSpec] = field(default_factory=list)
    role_id: str = "default"
    active_skill_ids: list[str] = field(default_factory=list)
    # History for the legacy stream_reply path (runtime without adapter).
    runtime_messages: list[Message] = field(default_factory=list)
    is_rehydrated: bool = False
    tool_failure_count: int = 0

    # --- Session TTL ---
    # Last activity time (monotonic clock). Used by SessionManager for eviction.
    last_activity_at: float = field(default_factory=time.monotonic)

    # --- Orchestrator delegation ---
    # role_id from which delegation originated (None = no active delegation)
    delegated_from: str | None = None
    # Summary passed during delegation / return
    delegation_summary: str | None = None
    # Turn counter inside delegated role (for auto-return)
    delegation_turn_count: int = 0
    # Deferred delegation: role_id for the next turn (set by delegate_to_role)
    pending_delegation: str | None = None

    def __post_init__(self) -> None:
        if self.adapter is not None:
            warnings.warn(
                "SessionState.adapter (RuntimePort) is deprecated. "
                "Use SessionState.runtime (AgentRuntime) instead.",
                DeprecationWarning,
                stacklevel=2,
            )
